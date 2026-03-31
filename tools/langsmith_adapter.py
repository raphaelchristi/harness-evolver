#!/usr/bin/env python3
"""LangSmith adapter for Harness Evolver.

Bridges evaluate.py with LangSmith for:
1. Auto-tracing setup (env vars for LangChain)
2. Trace export to filesystem (for proposer)
3. LLM-as-Judge evaluators

Stdlib-only. Uses langsmith_api.py for REST calls.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import langsmith_api


def is_enabled(config):
    return config.get("eval", {}).get("langsmith", {}).get("enabled", False)


def setup_tracing(config, version):
    """Return env vars dict to set before running harness. Empty dict if unavailable."""
    ls = config["eval"]["langsmith"]
    api_key = os.environ.get(ls.get("api_key_env", "LANGSMITH_API_KEY"), "")
    if not api_key:
        return {}
    return {
        "LANGCHAIN_TRACING_V2": "true",
        "LANGCHAIN_API_KEY": api_key,
        "LANGCHAIN_PROJECT": f"{ls['project_prefix']}-{version}",
    }


def export_traces(config, version, traces_dir):
    """Export LangSmith runs to traces/langsmith/ for the proposer to read."""
    ls = config["eval"]["langsmith"]
    if not ls.get("export_traces", True):
        return

    api_key = os.environ.get(ls.get("api_key_env", "LANGSMITH_API_KEY"), "")
    if not api_key:
        return

    project_name = f"{ls['project_prefix']}-{version}"
    try:
        response = langsmith_api.get_runs(api_key, project_name)
    except Exception as e:
        print(f"WARNING: Failed to export LangSmith traces: {e}", file=sys.stderr)
        return

    runs = response.get("runs", [])
    ls_dir = os.path.join(traces_dir, "langsmith")
    os.makedirs(ls_dir, exist_ok=True)

    for run in runs:
        run_file = os.path.join(ls_dir, f"{run['id']}.json")
        with open(run_file, "w") as f:
            json.dump(
                {
                    "run_id": run["id"],
                    "run_type": run.get("run_type"),
                    "name": run.get("name"),
                    "inputs": run.get("inputs"),
                    "outputs": run.get("outputs"),
                    "error": run.get("error"),
                    "latency_ms": run.get("latency_ms"),
                    "tokens": {
                        "prompt": run.get("prompt_tokens", 0),
                        "completion": run.get("completion_tokens", 0),
                        "total": run.get("total_tokens", 0),
                    },
                    "child_runs": len(run.get("child_run_ids", [])),
                    "feedback": run.get("feedback_stats"),
                },
                f,
                indent=2,
            )

    summary = {
        "total_runs": len(runs),
        "run_types": {},
        "errors": [],
        "total_tokens": 0,
        "avg_latency_ms": 0,
    }
    for r in runs:
        rt = r.get("run_type", "unknown")
        summary["run_types"][rt] = summary["run_types"].get(rt, 0) + 1
        summary["total_tokens"] += r.get("total_tokens", 0)
        if r.get("error"):
            summary["errors"].append({"run_id": r["id"], "error": r["error"]})
    if runs:
        summary["avg_latency_ms"] = round(
            sum(r.get("latency_ms", 0) for r in runs) / len(runs), 1
        )
    with open(os.path.join(ls_dir, "_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)


def run_evaluators(config, version):
    """Run LangSmith built-in evaluators, return scores dict."""
    ls = config["eval"]["langsmith"]
    evaluators = ls.get("evaluators", {})
    builtin = evaluators.get("builtin", [])
    if not builtin:
        return {}

    api_key = os.environ.get(ls.get("api_key_env", "LANGSMITH_API_KEY"), "")
    if not api_key:
        return {}

    project_name = f"{ls['project_prefix']}-{version}"
    scores = {}
    for name in builtin:
        try:
            result = langsmith_api.run_evaluator(api_key, project_name, name)
            scores[name] = result.get("aggregate_score", 0.0)
        except Exception as e:
            print(f"WARNING: LangSmith evaluator '{name}' failed: {e}", file=sys.stderr)
    return scores
