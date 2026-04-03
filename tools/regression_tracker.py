#!/usr/bin/env python3
"""Track regression examples across evolution iterations.

Compares per-example scores between consecutive iterations.
When an example transitions from failing (<0.5) to passing (>0.8),
adds a variation to the dataset as a regression guard.

Usage:
    python3 regression_tracker.py \
        --config .evolver.json \
        --previous-experiment v001a \
        --current-experiment v002c \
        --output regression_report.json
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_langsmith_api_key


def get_per_example_scores(client, experiment_name):
    """Get per-example scores from an experiment."""
    scores = {}
    try:
        runs = list(client.list_runs(project_name=experiment_name, is_root=True, limit=100))
        all_run_ids = [run.id for run in runs]
        all_feedbacks = list(client.list_feedback(run_ids=all_run_ids))
        fb_map = {}
        for fb in all_feedbacks:
            fb_map.setdefault(str(fb.run_id), []).append(fb)
        for run in runs:
            example_id = str(run.reference_example_id or run.id)
            feedbacks = fb_map.get(str(run.id), [])
            fb_scores = {}
            for fb in feedbacks:
                if fb.score is not None:
                    fb_scores[fb.key] = fb.score
            avg = sum(fb_scores.values()) / len(fb_scores) if fb_scores else 0.0
            scores[example_id] = {
                "score": avg,
                "input": run.inputs if isinstance(run.inputs, dict) else (str(run.inputs)[:500] if run.inputs else ""),
                "output": run.outputs if isinstance(run.outputs, dict) else (str(run.outputs)[:500] if run.outputs else ""),
                "split": getattr(run, "split", None),
            }
    except Exception as e:
        print(f"Error reading {experiment_name}: {e}", file=sys.stderr)
    return scores


def find_transitions(prev_scores, curr_scores, fail_threshold=0.5, pass_threshold=0.8):
    """Find examples that transitioned from failing to passing."""
    transitions = []
    regressions = []

    for example_id in set(prev_scores) & set(curr_scores):
        prev = prev_scores[example_id]["score"]
        curr = curr_scores[example_id]["score"]

        if prev < fail_threshold and curr >= pass_threshold:
            transitions.append({
                "example_id": example_id,
                "prev_score": prev,
                "curr_score": curr,
                "type": "fixed",
                "input": curr_scores[example_id]["input"],
            })
        elif prev >= pass_threshold and curr < fail_threshold:
            regressions.append({
                "example_id": example_id,
                "prev_score": prev,
                "curr_score": curr,
                "type": "regressed",
                "input": curr_scores[example_id]["input"],
            })

    return transitions, regressions


def add_regression_guards(client, dataset_id, transitions, max_guards=5, config=None):
    """Add regression guard examples to the dataset."""
    config = config or {}
    added = 0
    for t in transitions[:max_guards]:
        try:
            input_data = json.loads(t["input"]) if t["input"].startswith("{") else {"input": t["input"]}
            split = "train" if random.random() < 0.7 else "held_out"
            client.create_example(
                inputs=input_data,
                dataset_id=dataset_id,
                metadata={
                    "source": "regression_guard",
                    "original_example_id": t["example_id"],
                    "added_at_iteration": config.get("iterations", 0),
                },
                split=split,
            )
            added += 1
        except Exception as e:
            print(f"Failed to add guard for {t['example_id']}: {e}", file=sys.stderr)
    return added


def main():
    parser = argparse.ArgumentParser(description="Track regressions across iterations")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--previous-experiment", required=True, help="Previous iteration experiment name")
    parser.add_argument("--current-experiment", required=True, help="Current iteration experiment name")
    parser.add_argument("--output", default=None, help="Output JSON report")
    parser.add_argument("--add-guards", action="store_true", help="Add regression guard examples to dataset")
    parser.add_argument("--max-guards", type=int, default=5, help="Max guard examples to add")
    parser.add_argument("--auto-guard-failures", action="store_true",
                        help="Also add currently-failing examples as guards (marks them as known-hard)")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    ensure_langsmith_api_key()
    from langsmith import Client
    client = Client()

    prev_scores = get_per_example_scores(client, args.previous_experiment)
    curr_scores = get_per_example_scores(client, args.current_experiment)

    transitions, regressions = find_transitions(prev_scores, curr_scores)

    added = 0
    if args.add_guards and transitions:
        added = add_regression_guards(client, config["dataset_id"], transitions, args.max_guards, config=config)

    if added > 0:
        report_guard_details = [
            {"input": t["input"][:100], "prev_score": t["prev_score"], "curr_score": t["curr_score"]}
            for t in transitions[:args.max_guards]
        ]
    else:
        report_guard_details = []

    if args.auto_guard_failures:
        # Only guard failures from train split — never contaminate held_out
        # Also check original split via LangSmith example lookup
        train_example_ids = None  # None = couldn't determine, skip entirely (fail-closed)
        try:
            train_example_ids = set()
            for ex in client.list_examples(dataset_id=config["dataset_id"], splits=["train"]):
                train_example_ids.add(str(ex.id))
        except Exception:
            train_example_ids = None  # API failed — fail closed, don't risk held_out contamination

        if train_example_ids is None or len(train_example_ids) == 0:
            reason = "API failed" if train_example_ids is None else "train split empty or missing"
            print(f"  WARNING: {reason} — skipping auto-guard to protect held_out", file=sys.stderr)
            failing = []
        else:
            failing = [
                eid for eid, data in curr_scores.items()
                if data["score"] < 0.5 and eid in train_example_ids
            ]
        hard_added = 0

        # Deduplicate: check which example_ids already have hard_failure guards
        existing_guards = set()
        try:
            for ex in client.list_examples(dataset_id=config["dataset_id"], limit=500):
                meta = getattr(ex, "metadata", None) or {}
                if meta.get("source") == "hard_failure":
                    orig_id = meta.get("original_example_id", "")
                    if orig_id:
                        existing_guards.add(orig_id)
        except Exception:
            pass

        for eid in failing[:3]:
            if eid in existing_guards:
                continue  # Already guarded from a prior iteration
            try:
                # Use dict inputs directly (not str repr)
                input_data = curr_scores[eid].get("input", {})
                if isinstance(input_data, str):
                    try:
                        input_data = json.loads(input_data)
                    except (json.JSONDecodeError, ValueError):
                        input_data = {"input": input_data}
                client.create_example(
                    inputs=input_data,
                    dataset_id=config["dataset_id"],
                    metadata={
                        "source": "hard_failure",
                        "original_example_id": eid,
                        "failure_score": curr_scores[eid]["score"],
                        "added_at_iteration": config.get("iterations", 0),
                    },
                    split="train",
                )
                hard_added += 1
            except Exception as e:
                print(f"Failed to add hard guard for {eid}: {e}", file=sys.stderr)
    else:
        hard_added = 0

    result = {
        "previous": args.previous_experiment,
        "current": args.current_experiment,
        "fixed_count": len(transitions),
        "regression_count": len(regressions),
        "guards_added": added,
        "guard_details": report_guard_details,
        "hard_guards_added": hard_added,
        "fixed": transitions,
        "regressions": regressions,
    }

    output = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    print(output)

    if regressions:
        print(f"\nWARNING: {len(regressions)} regressions detected!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
