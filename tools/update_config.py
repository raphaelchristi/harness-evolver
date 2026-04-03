#!/usr/bin/env python3
"""Atomic .evolver.json updates after merge.

Replaces inline Python for config backup/restore/update during the evolve loop.
Three actions:
  backup  — save .evolver.json to .evolver.json.bak before merge
  restore — restore from .bak after merge overwrites config, delete .bak
  update  — update best_experiment, best_score, increment iterations,
             append enriched history entry

Stdlib-only. No external dependencies.

Usage:
    # Before merge — save config
    python3 update_config.py --config .evolver.json --action backup

    # After merge — restore config (merge brought worktree's stale copy)
    python3 update_config.py --config .evolver.json --action restore

    # Update config with winner data
    python3 update_config.py --config .evolver.json --action update \
        --winner-experiment v003-abc --winner-score 0.87 \
        --approach "fixed JSON parsing" --lens "failure_cluster" \
        --tokens 15000 --latency-ms 4500 --error-count 1 \
        --passing 18 --total 20 --per-evaluator '{"accuracy":0.9,"format":0.85}' \
        --code-loc 120
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import write_config_atomic, load_config


def action_backup(config_path):
    """Copy .evolver.json to .evolver.json.bak."""
    bak_path = config_path + ".bak"
    if not os.path.exists(config_path):
        print(f"Error: config not found: {config_path}", file=sys.stderr)
        return False
    shutil.copy2(config_path, bak_path)
    print(json.dumps({"action": "backup", "path": bak_path}))
    return True


def action_restore(config_path):
    """Restore .evolver.json from .bak, delete .bak."""
    bak_path = config_path + ".bak"
    if not os.path.exists(bak_path):
        print(f"Error: backup not found: {bak_path}", file=sys.stderr)
        return False
    shutil.copy2(bak_path, config_path)
    os.remove(bak_path)
    print(json.dumps({"action": "restore", "path": config_path}))
    return True


def action_update(config_path, args):
    """Update best_experiment, best_score, iterations, and append history."""
    config = load_config(config_path)

    # Update top-level fields
    config["best_experiment"] = args.winner_experiment
    config["best_score"] = args.winner_score
    config["iterations"] = config.get("iterations", 0) + 1

    # Build enriched history entry
    version = f"v{config['iterations']:03d}"
    entry = {
        "version": version,
        "experiment": args.winner_experiment,
        "score": args.winner_score,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Optional enrichment fields
    if args.approach:
        entry["approach"] = args.approach
    if args.lens:
        entry["lens"] = args.lens
    if args.tokens is not None:
        entry["tokens"] = args.tokens
    if args.latency_ms is not None:
        entry["latency_ms"] = args.latency_ms
    if args.error_count is not None:
        entry["error_count"] = args.error_count
    if args.passing is not None:
        entry["passing"] = args.passing
    if args.total is not None:
        entry["total"] = args.total
    if args.per_evaluator:
        try:
            entry["per_evaluator"] = json.loads(args.per_evaluator)
        except json.JSONDecodeError:
            print(f"Warning: --per-evaluator is not valid JSON, skipping", file=sys.stderr)
    if args.code_loc is not None:
        entry["code_loc"] = args.code_loc

    # Append to history
    if "history" not in config:
        config["history"] = []
    config["history"].append(entry)

    write_config_atomic(config_path, config)
    print(json.dumps({
        "action": "update",
        "version": version,
        "best_score": args.winner_score,
        "iterations": config["iterations"],
    }))
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Atomic .evolver.json updates after merge."
    )
    parser.add_argument(
        "--config", required=True, help="Path to .evolver.json"
    )
    parser.add_argument(
        "--action", required=True, choices=["backup", "restore", "update"],
        help="Action: backup, restore, or update"
    )

    # Update-specific flags
    parser.add_argument("--winner-experiment", help="Winning experiment name")
    parser.add_argument("--winner-score", type=float, help="Winning score")
    parser.add_argument("--approach", default="", help="Brief description of winning approach")
    parser.add_argument("--lens", default="", help="Investigation lens used")
    parser.add_argument("--tokens", type=int, default=None, help="Token usage")
    parser.add_argument("--latency-ms", type=int, default=None, help="Latency in milliseconds")
    parser.add_argument("--error-count", type=int, default=None, help="Number of errors")
    parser.add_argument("--passing", type=int, default=None, help="Number of passing examples")
    parser.add_argument("--total", type=int, default=None, help="Total number of examples")
    parser.add_argument("--per-evaluator", default=None, help="Per-evaluator scores as JSON string")
    parser.add_argument("--code-loc", type=int, default=None, help="Lines of code changed")

    args = parser.parse_args()

    if args.action == "update":
        if not args.winner_experiment or args.winner_score is None:
            parser.error("--winner-experiment and --winner-score are required for --action update")

    if args.action == "backup":
        ok = action_backup(args.config)
    elif args.action == "restore":
        ok = action_restore(args.config)
    elif args.action == "update":
        ok = action_update(args.config, args)
    else:
        parser.error(f"Unknown action: {args.action}")
        ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
