#!/usr/bin/env python3
"""Persistent candidate archive for cross-iteration proposer reasoning.

Saves candidate artifacts (diff, proposal.md, scores) to an evolution_archive/
directory alongside the config file after each iteration. Proposers can later
grep this archive for patterns, winning strategies, and failed approaches.

Stdlib-only. No external dependencies.

Usage:
    # Archive a candidate
    python3 archive.py --config .evolver.json --version v001 --experiment v001-abc \
        --worktree-path /tmp/wt --score 0.85 --approach "fixed parsing" \
        --lens "failure_cluster" --won

    # List all archived candidates
    python3 archive.py --config .evolver.json --list
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone


MAX_DIFF_BYTES = 50 * 1024  # 50KB cap for full diff


def load_json_safe(path):
    """Load JSON file, return None if missing or invalid."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def run_git(args, cwd):
    """Run a git command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def archive_candidate(
    config_path,
    version,
    experiment,
    worktree_path=None,
    score=0.0,
    approach="",
    lens="",
    won=False,
):
    """Archive a single candidate's artifacts after evaluation.

    Creates evolution_archive/{version}/ next to the config file with:
    - meta.json: version, experiment, score, approach, lens, won, timestamp
    - proposal.md: copied from worktree if present
    - diff_stat.txt: git diff HEAD~1 --stat from worktree
    - diff.patch: git diff HEAD~1 from worktree (capped at 50KB)
    - best_results.json: copied from config dir if present
    - trace_insights.json: copied from config dir if present
    """
    config_dir = os.path.dirname(os.path.abspath(config_path))
    archive_root = os.path.join(config_dir, "evolution_archive")
    candidate_dir = os.path.join(archive_root, version)
    os.makedirs(candidate_dir, exist_ok=True)

    # --- meta.json ---
    meta = {
        "version": version,
        "experiment": experiment,
        "score": score,
        "approach": approach,
        "lens": lens,
        "won": won,
        "archived_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(candidate_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    # --- worktree artifacts ---
    if worktree_path and os.path.isdir(worktree_path):
        # proposal.md
        proposal_src = os.path.join(worktree_path, "proposal.md")
        if os.path.exists(proposal_src):
            shutil.copy2(proposal_src, os.path.join(candidate_dir, "proposal.md"))

        # diff stat
        diff_stat = run_git(["diff", "HEAD~1", "--stat"], cwd=worktree_path)
        if diff_stat:
            with open(os.path.join(candidate_dir, "diff_stat.txt"), "w") as f:
                f.write(diff_stat)

        # full diff (capped)
        full_diff = run_git(["diff", "HEAD~1"], cwd=worktree_path)
        if full_diff:
            if len(full_diff.encode("utf-8", errors="replace")) > MAX_DIFF_BYTES:
                full_diff = full_diff[:MAX_DIFF_BYTES] + "\n... [truncated at 50KB]\n"
            with open(os.path.join(candidate_dir, "diff.patch"), "w") as f:
                f.write(full_diff)

    # --- config-dir artifacts ---
    for artifact in ("best_results.json", "trace_insights.json"):
        src = os.path.join(config_dir, artifact)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(candidate_dir, artifact))

    return candidate_dir


def list_archive(config_path):
    """Return list of all archived candidates' meta.json contents."""
    config_dir = os.path.dirname(os.path.abspath(config_path))
    archive_root = os.path.join(config_dir, "evolution_archive")

    if not os.path.isdir(archive_root):
        return []

    candidates = []
    for entry in sorted(os.listdir(archive_root)):
        meta_path = os.path.join(archive_root, entry, "meta.json")
        meta = load_json_safe(meta_path)
        if meta:
            candidates.append(meta)

    return candidates


def main():
    parser = argparse.ArgumentParser(
        description="Archive candidate artifacts for cross-iteration reasoning."
    )
    parser.add_argument(
        "--config", required=True, help="Path to .evolver.json"
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_mode",
        help="List all archived candidates"
    )
    parser.add_argument("--version", help="Candidate version label (e.g. v001a)")
    parser.add_argument("--experiment", help="LangSmith experiment name")
    parser.add_argument("--worktree-path", help="Path to candidate worktree")
    parser.add_argument("--score", type=float, default=0.0, help="Candidate score")
    parser.add_argument("--approach", default="", help="Brief description of approach")
    parser.add_argument("--lens", default="", help="Investigation lens used")
    parser.add_argument("--won", action="store_true", help="Whether this candidate won the iteration")

    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"Error: config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    if args.list_mode:
        candidates = list_archive(args.config)
        print(json.dumps(candidates, indent=2))
        return

    if not args.version or not args.experiment:
        parser.error("--version and --experiment are required when archiving")

    candidate_dir = archive_candidate(
        config_path=args.config,
        version=args.version,
        experiment=args.experiment,
        worktree_path=args.worktree_path,
        score=args.score,
        approach=args.approach,
        lens=args.lens,
        won=args.won,
    )
    print(f"Archived to {candidate_dir}")


if __name__ == "__main__":
    main()
