#!/usr/bin/env python3
"""Read LangSmith experiment results for Harness Evolver v3.

Reads experiment results from LangSmith and formats them for agents
(proposer, critic, architect). Handles comparison between candidates.

Usage:
    python3 read_results.py \
        --experiments v001a,v001b,v001c,v001d,v001e \
        --config .evolver.json \
        [--output results.json]

    python3 read_results.py \
        --experiment v001a \
        --config .evolver.json \
        --format markdown

Requires: pip install langsmith
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_langsmith_api_key


def weighted_score(scores, weights=None):
    """Calculate weighted average of evaluator scores.

    If weights provided, use them. Otherwise flat average.
    Weights are normalized (don't need to sum to 1).
    """
    if not scores:
        return 0.0
    if not weights:
        return sum(scores.values()) / len(scores)

    total_weight = 0
    weighted_sum = 0
    for key, val in scores.items():
        w = weights.get(key, 1.0)
        weighted_sum += val * w
        total_weight += w

    return weighted_sum / total_weight if total_weight > 0 else 0.0


def read_experiment(client, experiment_name, weights=None):
    """Read results from a single LangSmith experiment."""
    try:
        # List runs for this experiment
        runs = list(client.list_runs(
            project_name=experiment_name,
            is_root=True,
            limit=100,
        ))

        if not runs:
            return None

        per_example = {}
        total_tokens = 0
        total_latency_ms = 0
        errors = 0

        # Batch-fetch all feedback in one API call instead of N+1
        all_run_ids = [run.id for run in runs]
        all_feedbacks = list(client.list_feedback(run_ids=all_run_ids))
        fb_map = {}
        for fb in all_feedbacks:
            fb_map.setdefault(str(fb.run_id), []).append(fb)

        for run in runs:
            example_id = str(run.reference_example_id or run.id)
            tokens = run.total_tokens or 0
            total_tokens += tokens

            latency_ms = 0
            if run.end_time and run.start_time:
                latency_ms = int((run.end_time - run.start_time).total_seconds() * 1000)
            total_latency_ms += latency_ms

            has_error = bool(run.error)
            if has_error:
                errors += 1

            # Read feedback/scores from pre-fetched batch
            feedbacks = fb_map.get(str(run.id), [])
            scores = {}
            feedback_comments = {}
            for fb in feedbacks:
                if fb.score is not None:
                    scores[fb.key] = fb.score
                if fb.comment:
                    feedback_comments[fb.key] = fb.comment

            per_example[example_id] = {
                "score": weighted_score(scores, weights),
                "scores": scores,
                "feedback": feedback_comments,
                "tokens": tokens,
                "latency_ms": latency_ms,
                "error": run.error[:200] if run.error else None,
                "input_preview": str(run.inputs)[:200] if run.inputs else "",
                "output_preview": str(run.outputs)[:200] if run.outputs else "",
            }

        num_examples = len(per_example)

        # Exclude rate-limited runs from combined score (they're infra failures, not agent failures)
        rate_limit_keywords = ("429", "rate", "resource_exhausted", "quota")
        scored_examples = {}
        rate_limited_count = 0
        for eid, data in per_example.items():
            error_text = (data.get("error") or "").lower()
            output_text = (data.get("output_preview") or "").lower()
            is_rate_limited = any(kw in error_text or kw in output_text for kw in rate_limit_keywords)
            if is_rate_limited:
                rate_limited_count += 1
                data["rate_limited"] = True
            else:
                scored_examples[eid] = data

        all_scores = [v["score"] for v in scored_examples.values()]
        combined_score = sum(all_scores) / len(all_scores) if all_scores else 0.0

        return {
            "experiment": experiment_name,
            "combined_score": combined_score,
            "num_examples": num_examples,
            "num_scored": len(scored_examples),
            "rate_limited_count": rate_limited_count,
            "total_tokens": total_tokens,
            "avg_latency_ms": total_latency_ms // max(num_examples, 1),
            "error_count": errors,
            "error_rate": errors / max(num_examples, 1),
            "per_example": per_example,
        }

    except Exception as e:
        return {"experiment": experiment_name, "error": str(e), "combined_score": 0.0}


def pareto_front(candidates):
    """Find Pareto-optimal candidates (not dominated on any evaluator).

    A candidate is dominated if another scores >= on ALL evaluators
    and strictly > on at least one.
    """
    if len(candidates) <= 1:
        return candidates

    front = []
    for i, ci in enumerate(candidates):
        dominated = False
        ci_scores = ci.get("evaluator_scores", {})
        if not ci_scores:
            front.append(ci)
            continue

        for j, cj in enumerate(candidates):
            if i == j:
                continue
            cj_scores = cj.get("evaluator_scores", {})
            if not cj_scores:
                continue

            all_geq = True
            any_gt = False
            for key in ci_scores:
                if key in cj_scores:
                    if cj_scores[key] < ci_scores[key]:
                        all_geq = False
                        break
                    if cj_scores[key] > ci_scores[key]:
                        any_gt = True

            if all_geq and any_gt:
                dominated = True
                break

        if not dominated:
            front.append(ci)

    return front if front else candidates[:1]


def compare_experiments(results_list):
    """Compare multiple experiment results and find winner + per-task champion."""
    if not results_list:
        return None

    valid = [r for r in results_list if "error" not in r and r.get("combined_score", 0) > 0]
    if not valid:
        valid = results_list

    # Overall winner
    winner = max(valid, key=lambda r: r.get("combined_score", 0))

    # Per-task champion (candidate that beats winner on most individual tasks)
    task_wins = {}
    winner_examples = winner.get("per_example", {})

    for result in valid:
        if result["experiment"] == winner["experiment"]:
            continue

        wins = 0
        for example_id, data in result.get("per_example", {}).items():
            winner_score = winner_examples.get(example_id, {}).get("score", 0)
            if data.get("score", 0) > winner_score:
                wins += 1

        if wins > 0:
            task_wins[result["experiment"]] = wins

    champion = None
    if task_wins:
        champion_name = max(task_wins, key=task_wins.get)
        champion = {
            "experiment": champion_name,
            "task_wins": task_wins[champion_name],
        }

    # Compute per-evaluator averages for Pareto analysis
    for result in valid:
        eval_avgs = {}
        for ex_data in result.get("per_example", {}).values():
            for ev_key, ev_score in ex_data.get("scores", {}).items():
                eval_avgs.setdefault(ev_key, []).append(ev_score)
        result["evaluator_scores"] = {k: sum(v) / len(v) for k, v in eval_avgs.items()}

    front = pareto_front(valid)

    # MAP-Elites diversity grid: map each lens/candidate to its best score.
    # Extract lens category from experiment name suffix (e.g., "v001-2-abc123" → "lens-2").
    diversity_grid = {}
    for result in results_list:
        exp_name = result.get("experiment", "")
        parts = exp_name.split("-")
        # Heuristic: if there are at least 3 parts, the second-to-last numeric segment is the lens index
        lens_label = exp_name  # fallback to full name
        for i, part in enumerate(parts):
            if i > 0 and part.isdigit():
                lens_label = f"lens-{part}"
                break
        score = result.get("combined_score", 0)
        if lens_label not in diversity_grid or score > diversity_grid[lens_label]["score"]:
            diversity_grid[lens_label] = {
                "lens": lens_label,
                "experiment": exp_name,
                "score": score,
            }

    return {
        "winner": {
            "experiment": winner["experiment"],
            "score": winner["combined_score"],
        },
        "champion": champion,
        "pareto_front": [
            {"experiment": r["experiment"], "score": r["combined_score"],
             "evaluator_scores": r.get("evaluator_scores", {})}
            for r in front
        ],
        "all_candidates": [
            {
                "experiment": r["experiment"],
                "score": r.get("combined_score", 0),
                "tokens": r.get("total_tokens", 0),
                "latency_ms": r.get("avg_latency_ms", 0),
                "errors": r.get("error_count", 0),
            }
            for r in results_list
        ],
        "diversity_grid": list(diversity_grid.values()),
    }


def pairwise_compare(client, exp_a, exp_b, evaluator_key="correctness", split_ids=None):
    """Head-to-head comparison of two experiments on shared examples.

    For each example present in both experiments, compares the per-example
    score on the given evaluator key and counts wins for A vs B.

    Returns:
        dict with winner ("A", "B", or "tie"), consistency flag, win counts,
        margin, and experiment names.
    """
    runs_a = list(client.list_runs(project_name=exp_a, is_root=True, limit=100))
    runs_b = list(client.list_runs(project_name=exp_b, is_root=True, limit=100))

    # Build example_id → run mapping for each experiment
    def _build_example_scores(runs):
        run_ids = [r.id for r in runs]
        if not run_ids:
            return {}
        feedbacks = list(client.list_feedback(run_ids=run_ids))
        fb_map = {}
        for fb in feedbacks:
            fb_map.setdefault(str(fb.run_id), []).append(fb)

        scores = {}
        for run in runs:
            example_id = str(run.reference_example_id or run.id)
            run_feedbacks = fb_map.get(str(run.id), [])
            for fb in run_feedbacks:
                if fb.key == evaluator_key and fb.score is not None:
                    scores[example_id] = fb.score
                    break
        return scores

    scores_a = _build_example_scores(runs_a)
    scores_b = _build_example_scores(runs_b)

    # Only compare shared examples, filtered by split if provided
    shared = set(scores_a.keys()) & set(scores_b.keys())
    if split_ids is not None:
        shared = shared & split_ids

    a_wins = 0
    b_wins = 0
    for eid in shared:
        sa = scores_a[eid]
        sb = scores_b[eid]
        if sa > sb:
            a_wins += 1
        elif sb > sa:
            b_wins += 1

    total = a_wins + b_wins
    if total == 0:
        winner = "tie"
        margin = 0.0
    elif a_wins > b_wins:
        winner = "A"
        margin = (a_wins - b_wins) / total
    elif b_wins > a_wins:
        winner = "B"
        margin = (b_wins - a_wins) / total
    else:
        winner = "tie"
        margin = 0.0

    return {
        "winner": winner,
        "consistent": margin > 0.20,
        "a_wins": a_wins,
        "b_wins": b_wins,
        "margin": round(margin, 4),
        "experiment_a": exp_a,
        "experiment_b": exp_b,
    }


def format_summary(results):
    """Compact summary — key metrics only, no per-example data. ~200 tokens vs ~5K."""
    r = results
    num = r.get("num_examples", 0)
    score = r.get("combined_score", 0)
    errors = r.get("error_count", 0)

    # Aggregate per-evaluator scores
    eval_avgs = {}
    for ex_data in r.get("per_example", {}).values():
        for k, v in ex_data.get("scores", {}).items():
            eval_avgs.setdefault(k, []).append(v)
    eval_summary = {k: round(sum(v) / len(v), 3) for k, v in eval_avgs.items()}

    # Identify failure pattern
    failing = [ex for ex in r.get("per_example", {}).values() if ex.get("score", 0) <= 0.5]
    failure_pattern = "none"
    if failing:
        # Check if failures share a common error
        error_msgs = [ex.get("error", "") or "" for ex in failing if ex.get("error")]
        if error_msgs and len(set(e[:50] for e in error_msgs)) == 1:
            failure_pattern = f"uniform: {error_msgs[0][:80]}"
        else:
            failure_pattern = f"{len(failing)}/{num} failing"

    # Top failing inputs (max 3) — include score <= 0.5 (not just < 0.5)
    top_failing = []
    for eid, data in sorted(r.get("per_example", {}).items(), key=lambda x: x[1].get("score", 0))[:3]:
        if data.get("score", 0) <= 0.5:
            fb = data.get("feedback", {})
            fb_text = next(iter(fb.values()), "") if fb else ""
            top_failing.append({
                "input": data.get("input_preview", "")[:80],
                "output": data.get("output_preview", "")[:80],
                "score": data["score"],
                "scores": data.get("scores", {}),
                "feedback": fb_text[:120],
            })

    return {
        "experiment": r.get("experiment"),
        "combined_score": score,
        "num_examples": num,
        "error_count": errors,
        "per_evaluator": eval_summary,
        "failure_pattern": failure_pattern,
        "top_failing": top_failing,
        "tokens": r.get("total_tokens", 0),
        "avg_latency_ms": r.get("avg_latency_ms", 0),
    }


def format_markdown(results):
    """Format experiment results as markdown for agents."""
    lines = [f"# Experiment Results: {results['experiment']}", ""]

    lines.append(f"**Combined Score**: {results.get('combined_score', 0):.3f}")
    lines.append(f"**Examples**: {results.get('num_examples', 0)}")
    lines.append(f"**Total Tokens**: {results.get('total_tokens', 0)}")
    lines.append(f"**Avg Latency**: {results.get('avg_latency_ms', 0)}ms")
    lines.append(f"**Errors**: {results.get('error_count', 0)} ({results.get('error_rate', 0):.1%})")
    lines.append("")

    per_example = results.get("per_example", {})
    if per_example:
        # Failing examples
        failing = {k: v for k, v in per_example.items() if v.get("score", 0) < 0.5}
        if failing:
            lines.append("## Failing Examples")
            lines.append("")
            for eid, data in sorted(failing.items(), key=lambda x: x[1].get("score", 0)):
                lines.append(f"- **{eid}**: score={data['score']:.2f}")
                if data.get("error"):
                    lines.append(f"  Error: {data['error']}")
                lines.append(f"  Input: {data.get('input_preview', 'N/A')}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Read LangSmith experiment results")
    parser.add_argument("--experiments", default=None, help="Comma-separated experiment names to compare")
    parser.add_argument("--experiment", default=None, help="Single experiment to read")
    parser.add_argument("--config", default=".evolver.json", help="Path to .evolver.json")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--format", default="json", choices=["json", "markdown", "summary"], help="Output format (summary = compact ~200 tokens)")
    parser.add_argument("--split", default=None, help="Filter by dataset split (e.g., 'train')")
    parser.add_argument("--pairwise", default=None, help="Pairwise comparison: 'exp_a,exp_b' (optionally append :evaluator_key)")
    args = parser.parse_args()
    ensure_langsmith_api_key()

    # Load evaluator weights from config if available
    weights = None
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg = json.load(f)
        weights = cfg.get("evaluator_weights")

    from langsmith import Client
    client = Client()

    if args.pairwise:
        # Pairwise head-to-head comparison
        parts = args.pairwise.split(",")
        if len(parts) < 2:
            print("--pairwise requires 'exp_a,exp_b'", file=sys.stderr)
            sys.exit(1)
        exp_a = parts[0].strip()
        exp_b = parts[1].strip()
        evaluator_key = "correctness"
        if len(parts) >= 3:
            evaluator_key = parts[2].strip()

        # Apply split filter to pairwise comparison (same as multi-experiment)
        split_ids = None
        if args.split and os.path.exists(args.config):
            with open(args.config) as f:
                cfg_pw = json.load(f)
            split_ids = set()
            for ex in client.list_examples(dataset_name=cfg_pw["dataset"], splits=[args.split]):
                split_ids.add(str(ex.id))
            if not split_ids:
                print(f"ERROR: Split '{args.split}' has 0 examples.", file=sys.stderr)
                sys.exit(1)

        result = pairwise_compare(client, exp_a, exp_b, evaluator_key=evaluator_key, split_ids=split_ids)
        output = json.dumps(result, indent=2, default=str)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        print(output)

    elif args.experiment:
        # Single experiment
        result = read_experiment(client, args.experiment, weights=weights)
        if not result:
            print(f"No results found for experiment: {args.experiment}", file=sys.stderr)
            sys.exit(1)

        if args.split and result and "per_example" in result:
            with open(args.config) as f:
                cfg = json.load(f)
            split_example_ids = set()
            for ex in client.list_examples(dataset_name=cfg["dataset"], splits=[args.split]):
                split_example_ids.add(str(ex.id))
            result["per_example"] = {k: v for k, v in result["per_example"].items() if k in split_example_ids}
            all_scores = [v["score"] for v in result["per_example"].values()]
            result["combined_score"] = sum(all_scores) / len(all_scores) if all_scores else 0.0
            result["num_examples"] = len(result["per_example"])

        if args.format == "summary":
            output = json.dumps(format_summary(result), indent=2, default=str)
        elif args.format == "markdown":
            output = format_markdown(result)
        else:
            output = json.dumps(result, indent=2, default=str)

        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        print(output)

    elif args.experiments:
        # Compare multiple experiments
        experiment_names = [e.strip() for e in args.experiments.split(",")]
        results_list = []

        # Load split filter if requested
        split_example_ids = None
        if args.split:
            with open(args.config) as f:
                cfg_for_split = json.load(f)
            split_example_ids = set()
            for ex in client.list_examples(dataset_name=cfg_for_split["dataset"], splits=[args.split]):
                split_example_ids.add(str(ex.id))

            # Fail hard if requested split has zero examples
            if not split_example_ids:
                print(f"ERROR: Split '{args.split}' has 0 examples in dataset '{cfg_for_split['dataset']}'.", file=sys.stderr)
                print(f"Run /harness:health to create train/held_out splits before comparing.", file=sys.stderr)
                sys.exit(1)

        for name in experiment_names:
            print(f"Reading experiment: {name}...", file=sys.stderr)
            result = read_experiment(client, name, weights=weights)
            if result:
                # Apply split filter to each experiment
                if split_example_ids is not None and "per_example" in result:
                    result["per_example"] = {k: v for k, v in result["per_example"].items() if k in split_example_ids}
                    all_scores = [v["score"] for v in result["per_example"].values()]
                    if not all_scores:
                        print(f"  WARNING: {name} has 0 examples after '{args.split}' filter — skipping", file=sys.stderr)
                        continue
                    result["combined_score"] = sum(all_scores) / len(all_scores)
                    result["num_examples"] = len(result["per_example"])
                results_list.append(result)

        if not results_list:
            print("No experiment results found.", file=sys.stderr)
            sys.exit(1)

        comparison = compare_experiments(results_list)
        output = json.dumps({
            "comparison": comparison,
            "experiments": results_list,
        }, indent=2, default=str)

        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        print(output)

    else:
        print("Provide --experiment or --experiments", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
