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
import platform
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
        all_scores = [v["score"] for v in per_example.values()]
        combined_score = sum(all_scores) / len(all_scores) if all_scores else 0.0

        return {
            "experiment": experiment_name,
            "combined_score": combined_score,
            "num_examples": num_examples,
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

    if args.experiment:
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

        for name in experiment_names:
            print(f"Reading experiment: {name}...", file=sys.stderr)
            result = read_experiment(client, name, weights=weights)
            if result:
                # Apply split filter to each experiment
                if split_example_ids is not None and "per_example" in result:
                    result["per_example"] = {k: v for k, v in result["per_example"].items() if k in split_example_ids}
                    all_scores = [v["score"] for v in result["per_example"].values()]
                    result["combined_score"] = sum(all_scores) / len(all_scores) if all_scores else 0.0
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
