#!/usr/bin/env python3
"""Log an evolution iteration as a LangSmith run.

Creates a run in the evolution tracing project with iteration metadata.
Returns the run ID and dotted_order for nesting proposer traces as children.

Usage:
    python3 log_iteration.py --config .evolver.json --action start --version v001
    python3 log_iteration.py --config .evolver.json --action end --run-id <id> --score 0.85 --merged true

Requires: pip install langsmith
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_langsmith_api_key, load_config


def start_iteration(client, project_name, config, version):
    """Create a new LangSmith run for an iteration."""
    from langsmith import RunTree

    run = RunTree(
        name=f"iteration-{version}",
        run_type="chain",
        project_name=project_name,
        inputs={
            "version": version,
            "best_score": config.get("best_score", 0),
            "iterations": config.get("iterations", 0),
            "mode": config.get("mode", "balanced"),
            "evaluators": config.get("evaluators", []),
        },
        extra={
            "metadata": {
                "evolver_version": version,
                "agent_project": config.get("project", "unknown"),
                "mode": config.get("mode", "balanced"),
            }
        },
    )
    run.post()

    return {
        "run_id": str(run.id),
        "dotted_order": run.dotted_order,
        "trace_id": str(run.trace_id),
    }


def end_iteration(client, run_id, score, merged, approach, lens, candidates, duration):
    """Update an existing iteration run with results."""
    outputs = {
        "score": score,
        "merged": merged,
        "approach": approach,
        "lens": lens,
        "candidates_evaluated": candidates,
    }

    client.update_run(
        run_id=run_id,
        outputs=outputs,
        end_time=datetime.now(timezone.utc),
        extra={
            "metadata": {
                "score": score,
                "merged": merged,
                "approach": approach,
                "lens": lens,
                "duration_seconds": duration,
            }
        },
    )

    try:
        client.create_feedback(
            run_id=run_id,
            key="score",
            score=score,
            comment=f"{'Merged' if merged else 'Not merged'}: {approach}",
        )
    except Exception:
        pass

    return {"run_id": run_id, "score": score, "merged": merged}


def main():
    parser = argparse.ArgumentParser(description="Log evolution iteration to LangSmith")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--action", required=True, choices=["start", "end"])
    parser.add_argument("--version", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--score", type=float, default=0.0)
    parser.add_argument("--merged", type=lambda x: x.lower() == "true", default=False)
    parser.add_argument("--approach", default="")
    parser.add_argument("--lens", default="")
    parser.add_argument("--candidates", type=int, default=0)
    parser.add_argument("--duration", type=int, default=0)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    ensure_langsmith_api_key()

    config = load_config(args.config)
    if not config:
        print('{"error": "config not found"}')
        sys.exit(1)

    from langsmith import Client
    client = Client()

    project_name = args.project or f"harness-evolution-{config.get('project', 'unknown')}"

    if args.action == "start":
        version = args.version or f"v{config.get('iterations', 0) + 1:03d}"
        result = start_iteration(client, project_name, config, version)
        output = json.dumps(result, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        print(output)

    elif args.action == "end":
        if not args.run_id:
            print('{"error": "--run-id required for --action end"}', file=sys.stderr)
            sys.exit(1)
        result = end_iteration(
            client, args.run_id, args.score, args.merged,
            args.approach, args.lens, args.candidates, args.duration,
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
