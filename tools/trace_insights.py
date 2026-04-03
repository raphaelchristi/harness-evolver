#!/usr/bin/env python3
"""Trace Insights Generator for Harness Evolver.

Analyzes LangSmith traces + per-task scores to produce structured insights.
Clusters errors, analyzes token usage, cross-references with scores,
and generates data-driven hypotheses.

Usage (v3 — SDK mode):
    python3 trace_insights.py \
        --from-experiment "v003-2026-04-01" \
        --output trace_insights.json

Usage (legacy — file mode):
    python3 trace_insights.py \
        --langsmith-runs langsmith_runs.json \
        --scores scores.json \
        --tasks-dir tasks/ \
        --output trace_insights.json

Requires: pip install langsmith (for SDK mode)
"""

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone


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


def load_json(path):
    """Load JSON file, return None if missing or invalid."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def cluster_errors(runs):
    """Group runs by error pattern (first 80 chars of error message)."""
    clusters = {}
    for run in runs:
        error = run.get("error")
        if not error:
            continue
        # Normalize: take first 80 chars, strip whitespace
        pattern = error.strip()[:80]
        clusters.setdefault(pattern, []).append(run)
    return [
        {"pattern": pattern, "count": len(runs_list), "run_names": [r.get("name", "?") for r in runs_list[:5]]}
        for pattern, runs_list in sorted(clusters.items(), key=lambda x: -len(x[1]))
    ]


def analyze_tokens(runs):
    """Bucket runs by token usage: low (<500), medium (500-2000), high (>2000)."""
    buckets = {"low": [], "medium": [], "high": []}
    for run in runs:
        tokens = run.get("tokens") or run.get("total_tokens") or 0
        if tokens < 500:
            buckets["low"].append(run)
        elif tokens < 2000:
            buckets["medium"].append(run)
        else:
            buckets["high"].append(run)
    return {
        name: {"count": len(items), "avg_tokens": sum((r.get("tokens") or r.get("total_tokens") or 0) for r in items) / max(len(items), 1)}
        for name, items in buckets.items()
    }


def analyze_responses(runs):
    """Bucket runs by response length: empty, short (<100), normal (100-1000), long (>1000)."""
    buckets = {"empty": [], "short": [], "normal": [], "long": []}
    for run in runs:
        resp = run.get("llm_response") or run.get("output") or ""
        length = len(resp)
        if length == 0:
            buckets["empty"].append(run)
        elif length < 100:
            buckets["short"].append(run)
        elif length < 1000:
            buckets["normal"].append(run)
        else:
            buckets["long"].append(run)
    return {
        name: {"count": len(items)}
        for name, items in buckets.items()
        if items
    }


def cross_reference_scores(runs, scores_data, tasks_dir):
    """Cross-reference trace patterns with per-task scores."""
    per_task = scores_data.get("per_task", {}) if scores_data else {}
    if not per_task:
        return {}

    # Load task metadata for category mapping
    task_meta = {}
    if tasks_dir and os.path.isdir(tasks_dir):
        for fname in os.listdir(tasks_dir):
            if fname.endswith(".json"):
                path = os.path.join(tasks_dir, fname)
                try:
                    with open(path) as f:
                        t = json.load(f)
                    tid = t.get("id", fname.replace(".json", ""))
                    task_meta[tid] = t.get("metadata", {})
                except (json.JSONDecodeError, OSError):
                    pass

    # Score statistics
    scores = [v.get("score", 0) for v in per_task.values() if isinstance(v, dict)]
    if not scores:
        return {}

    failing = {tid: v for tid, v in per_task.items() if isinstance(v, dict) and v.get("score", 0) < 0.5}
    passing = {tid: v for tid, v in per_task.items() if isinstance(v, dict) and v.get("score", 0) >= 0.8}

    # Group failures by category
    failure_categories = {}
    for tid in failing:
        meta = task_meta.get(tid, {})
        cat = meta.get("category", meta.get("type", "unknown"))
        failure_categories.setdefault(cat, []).append(tid)

    return {
        "total_tasks": len(per_task),
        "avg_score": sum(scores) / len(scores),
        "failing_count": len(failing),
        "passing_count": len(passing),
        "failing_task_ids": list(failing.keys()),
        "failure_categories": {cat: tids for cat, tids in sorted(failure_categories.items(), key=lambda x: -len(x[1]))},
    }


def correlate_tokens_scores(runs, scores_data):
    """Check if token usage correlates with task scores."""
    per_task = scores_data.get("per_task", {}) if scores_data else {}
    if not per_task or not runs:
        return None

    # Simple correlation: avg score for high-token vs low-token runs
    token_scores = {"low": [], "medium": [], "high": []}
    for run in runs:
        tokens = run.get("tokens") or run.get("total_tokens") or 0
        # Try to match run to task by name
        name = run.get("name", "")
        for tid, tdata in per_task.items():
            if isinstance(tdata, dict) and tid in name:
                score = tdata.get("score", 0)
                if tokens < 500:
                    token_scores["low"].append(score)
                elif tokens < 2000:
                    token_scores["medium"].append(score)
                else:
                    token_scores["high"].append(score)
                break

    result = {}
    for bucket, scores in token_scores.items():
        if scores:
            result[bucket] = {"count": len(scores), "avg_score": sum(scores) / len(scores)}
    return result if result else None


def generate_hypotheses(error_clusters, token_analysis, response_analysis, score_cross_ref, token_score_corr):
    """Generate data-driven hypotheses about failure patterns."""
    hypotheses = []

    # Hypothesis: errors cause failures
    if error_clusters:
        total_errors = sum(c["count"] for c in error_clusters)
        top_error = error_clusters[0]
        hypotheses.append(
            f"{total_errors} runs had errors. Most common: \"{top_error['pattern']}\" ({top_error['count']} occurrences)"
        )

    # Hypothesis: empty responses
    if response_analysis and response_analysis.get("empty", {}).get("count", 0) > 0:
        n = response_analysis["empty"]["count"]
        hypotheses.append(
            f"{n} runs returned empty responses — possible API timeout, rate limiting, or invalid prompt"
        )

    # Hypothesis: high token usage correlates with low scores
    if token_score_corr:
        high = token_score_corr.get("high", {})
        low = token_score_corr.get("low", {})
        if high.get("avg_score", 1) < low.get("avg_score", 0) - 0.15:
            hypotheses.append(
                f"High-token runs avg score {high['avg_score']:.2f} vs low-token {low['avg_score']:.2f} — model may be verbose but inaccurate"
            )

    # Hypothesis: specific category failures
    if score_cross_ref and score_cross_ref.get("failure_categories"):
        cats = score_cross_ref["failure_categories"]
        top_cat = next(iter(cats))
        count = len(cats[top_cat])
        hypotheses.append(
            f"Category \"{top_cat}\" has {count} failing tasks — may need targeted prompt or tool improvement"
        )

    # Hypothesis: many failing
    if score_cross_ref:
        fail_count = score_cross_ref.get("failing_count", 0)
        total = score_cross_ref.get("total_tasks", 1)
        if fail_count > total * 0.5:
            hypotheses.append(
                f"{fail_count}/{total} tasks failing (>{50}%) — fundamental approach issue, not edge cases"
            )

    return hypotheses


def identify_top_issues(error_clusters, response_analysis, score_cross_ref):
    """Identify the most impactful issues sorted by severity."""
    issues = []

    # Empty responses = high severity
    if response_analysis and response_analysis.get("empty", {}).get("count", 0) > 0:
        issues.append({
            "type": "empty_response",
            "severity": "high",
            "count": response_analysis["empty"]["count"],
            "description": "Runs returning empty responses",
        })

    # Errors = high severity
    if error_clusters:
        for cluster in error_clusters[:3]:
            issues.append({
                "type": "error",
                "severity": "high" if cluster["count"] > 2 else "medium",
                "count": cluster["count"],
                "pattern": cluster["pattern"],
                "description": f"Error: {cluster['pattern'][:60]}",
            })

    # Category-concentrated failures = medium severity
    if score_cross_ref and score_cross_ref.get("failure_categories"):
        for cat, tids in list(score_cross_ref["failure_categories"].items())[:3]:
            issues.append({
                "type": "category_failure",
                "severity": "medium" if len(tids) >= 3 else "low",
                "category": cat,
                "tasks": tids,
                "description": f"Category \"{cat}\" has {len(tids)} failing tasks",
            })

    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))
    return issues


def fetch_runs_from_langsmith(project_name, experiment_name=None, limit=50):
    """Fetch runs directly from LangSmith SDK (v3 mode)."""
    try:
        ensure_langsmith_api_key()
        from langsmith import Client
        client = Client()

        source = experiment_name or project_name
        raw_runs = list(client.list_runs(
            project_name=source,
            is_root=True,
            limit=limit,
        ))

        runs = []
        for run in raw_runs:
            entry = {
                "name": run.name or "unknown",
                "tokens": run.total_tokens or 0,
                "error": run.error[:200] if run.error else None,
                "llm_response": str(run.outputs)[:300] if run.outputs else "",
            }
            runs.append(entry)

        return runs
    except Exception as e:
        print(f"Failed to fetch from LangSmith: {e}", file=sys.stderr)
        return []


def fetch_scores_from_experiment(experiment_name):
    """Fetch per-example scores from a LangSmith experiment (v3 mode)."""
    try:
        from langsmith import Client
        client = Client()

        runs = list(client.list_runs(
            project_name=experiment_name,
            is_root=True,
            limit=100,
        ))

        all_run_ids = [run.id for run in runs]
        all_feedbacks = list(client.list_feedback(run_ids=all_run_ids))
        fb_map = {}
        for fb in all_feedbacks:
            fb_map.setdefault(str(fb.run_id), []).append(fb)

        per_task = {}
        for run in runs:
            example_id = str(run.reference_example_id or run.id)
            feedbacks = fb_map.get(str(run.id), [])
            scores = [fb.score for fb in feedbacks if fb.score is not None]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            per_task[example_id] = {"score": avg_score}

        all_scores = [v["score"] for v in per_task.values()]
        combined = sum(all_scores) / len(all_scores) if all_scores else 0.0

        return {"combined_score": combined, "per_task": per_task}
    except Exception as e:
        print(f"Failed to fetch experiment scores: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="Generate trace insights from LangSmith data + scores")
    parser.add_argument("--langsmith-runs", default=None, help="Path to langsmith_runs.json (v2 mode)")
    parser.add_argument("--langsmith-stats", help="Path to langsmith_stats.json (optional)")
    parser.add_argument("--scores", default=None, help="Path to scores.json (v2 mode)")
    parser.add_argument("--tasks-dir", default=None, help="Path to eval/tasks/ directory (v2 mode)")
    parser.add_argument("--from-project", default=None, help="LangSmith project name (v3 mode)")
    parser.add_argument("--from-experiment", default=None, help="LangSmith experiment name (v3 mode)")
    parser.add_argument("--output", required=True, help="Output path for trace_insights.json")
    args = parser.parse_args()

    # v3 mode: fetch directly from LangSmith
    if args.from_project or args.from_experiment:
        runs = fetch_runs_from_langsmith(args.from_project, args.from_experiment)
        scores_data = fetch_scores_from_experiment(args.from_experiment) if args.from_experiment else None
        stats = None
    else:
        # v2 mode: read from local files
        runs = load_json(args.langsmith_runs)
        stats = load_json(args.langsmith_stats)
        scores_data = load_json(args.scores)

    if not runs and not scores_data:
        # Nothing to analyze — write minimal insights
        insights = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": "No trace data or scores available for analysis",
            "error_clusters": [],
            "token_analysis": {},
            "response_analysis": {},
            "hypotheses": [],
            "top_issues": [],
        }
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(insights, f, indent=2)
        print("No data available — wrote empty insights")
        return

    runs = runs or []

    # Phase 1: Cluster traces
    error_clusters = cluster_errors(runs)
    token_analysis = analyze_tokens(runs)
    response_analysis = analyze_responses(runs)

    # Phase 2: Cross-reference with scores
    tasks_dir = getattr(args, "tasks_dir", None)
    score_cross_ref = cross_reference_scores(runs, scores_data, tasks_dir)
    token_score_corr = correlate_tokens_scores(runs, scores_data)

    # Phase 3: Generate hypotheses
    hypotheses = generate_hypotheses(error_clusters, token_analysis, response_analysis, score_cross_ref, token_score_corr)

    # Phase 4: Identify top issues
    top_issues = identify_top_issues(error_clusters, response_analysis, score_cross_ref)

    # Build summary line
    parts = []
    if error_clusters:
        parts.append(f"{len(error_clusters)} error pattern(s)")
    if score_cross_ref:
        parts.append(f"{score_cross_ref.get('failing_count', 0)}/{score_cross_ref.get('total_tasks', 0)} tasks failing")
        parts.append(f"avg score {score_cross_ref.get('avg_score', 0):.2f}")
    summary = "; ".join(parts) if parts else "Analysis complete, no major issues found"

    # Merge stats if available
    stats_summary = {}
    if stats:
        stats_summary = {
            "total_runs": stats.get("total_runs") or stats.get("run_count"),
            "error_rate": stats.get("error_rate"),
            "avg_latency_ms": stats.get("avg_latency_ms") or stats.get("latency_p50"),
            "p95_latency_ms": stats.get("latency_p95"),
            "avg_tokens": stats.get("avg_tokens") or stats.get("avg_total_tokens"),
        }
        # Remove None values
        stats_summary = {k: v for k, v in stats_summary.items() if v is not None}

    insights = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "langsmith_stats": stats_summary if stats_summary else None,
        "error_clusters": error_clusters,
        "token_analysis": token_analysis,
        "response_analysis": response_analysis,
        "score_cross_ref": score_cross_ref if score_cross_ref else None,
        "token_score_correlation": token_score_corr,
        "hypotheses": hypotheses,
        "top_issues": top_issues,
    }

    # Remove None values at top level
    insights = {k: v for k, v in insights.items() if v is not None}

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(insights, f, indent=2)

    print(f"Trace insights generated: {summary}")
    print(f"  {len(error_clusters)} error cluster(s), {len(hypotheses)} hypothesis(es), {len(top_issues)} issue(s)")


if __name__ == "__main__":
    main()
