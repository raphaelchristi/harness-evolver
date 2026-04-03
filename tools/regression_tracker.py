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
import platform
import random
import sys


def ensure_langsmith_api_key():
    """Load LANGSMITH_API_KEY from env, project .env, or global credentials.

    Priority: env var > project .env (CWD or --config dir) > global credentials.
    Project .env takes precedence over global credentials because the project-local
    key is more likely to be correct and up-to-date.
    """
    if os.environ.get("LANGSMITH_API_KEY"):
        return True
    # Check .env in CWD and in --config directory FIRST (project-local > global)
    env_candidates = [".env"]
    for i, arg in enumerate(sys.argv):
        if arg == "--config" and i + 1 < len(sys.argv):
            cfg_dir = os.path.dirname(os.path.abspath(sys.argv[i + 1]))
            env_candidates.append(os.path.join(cfg_dir, ".env"))
        elif arg.startswith("--config="):
            cfg_dir = os.path.dirname(os.path.abspath(arg.split("=", 1)[1]))
            env_candidates.append(os.path.join(cfg_dir, ".env"))
    for env_path in env_candidates:
        if os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("LANGSMITH_API_KEY=") and not line.startswith("#"):
                            key = line.split("=", 1)[1].strip().strip("'\"")
                            if key:
                                os.environ["LANGSMITH_API_KEY"] = key
                                return True
            except OSError:
                pass
    # Fallback: global langsmith-cli credentials file
    if platform.system() == "Darwin":
        creds_path = os.path.expanduser("~/Library/Application Support/langsmith-cli/credentials")
    else:
        creds_path = os.path.expanduser("~/.config/langsmith-cli/credentials")
    if os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    return False


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
                "input": str(run.inputs)[:500] if run.inputs else "",
                "output": str(run.outputs)[:500] if run.outputs else "",
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

    result = {
        "previous": args.previous_experiment,
        "current": args.current_experiment,
        "fixed_count": len(transitions),
        "regression_count": len(regressions),
        "guards_added": added,
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
