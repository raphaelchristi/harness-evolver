#!/usr/bin/env python3
"""State manager for Harness Evolver.

Commands:
    init   --base-dir DIR --baseline-score FLOAT
    update --base-dir DIR --version VER --scores PATH --proposal PATH
    show   --base-dir DIR

Manages: summary.json (source of truth), STATE.md (human view), PROPOSER_HISTORY.md (log).
Stdlib-only. No external dependencies.
"""

import argparse
import json
import os
import re
import sys


def _read_json(path):
    with open(path) as f:
        return json.load(f)


def _write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _read_text(path):
    with open(path) as f:
        return f.read()


def _write_text(path, text):
    with open(path, "w") as f:
        f.write(text)


def _summary_path(base_dir):
    return os.path.join(base_dir, "summary.json")


def _state_md_path(base_dir):
    return os.path.join(base_dir, "STATE.md")


def _history_path(base_dir):
    return os.path.join(base_dir, "PROPOSER_HISTORY.md")


def _detect_parent(proposal_text, current_best):
    """Parse 'Based on vXXX' or 'Based on baseline' from proposal text."""
    match = re.search(r"[Bb]ased on (v\d+|baseline)", proposal_text)
    if match:
        return match.group(1)
    return current_best


def _render_state_md(summary):
    """Generate STATE.md from summary.json data."""
    lines = ["# Harness Evolver Status", ""]
    best = summary["best"]
    worst = summary["worst"]
    lines.append(f"**Iterations:** {summary['iterations']}")
    lines.append(f"**Best:** {best['version']} ({best['combined_score']:.2f})")
    lines.append(f"**Worst:** {worst['version']} ({worst['combined_score']:.2f})")
    if summary["history"]:
        last = summary["history"][-1]
        lines.append(f"**Latest:** {last['version']} ({last['combined_score']:.2f})")
    lines.append("")
    lines.append("## History")
    lines.append("")
    lines.append("| Version | Score | Parent | Delta |")
    lines.append("|---------|-------|--------|-------|")
    prev_score = None
    for entry in summary["history"]:
        v = entry["version"]
        s = entry["combined_score"]
        p = entry["parent"] or "-"
        if prev_score is not None and v != "baseline":
            delta = s - prev_score
            if delta < -0.01:
                delta_str = f"{delta:+.2f} REGRESSION"
            elif delta > 0.01:
                delta_str = f"{delta:+.2f}"
            else:
                delta_str = f"{delta:+.2f} (stagnant)"
        else:
            delta_str = "-"
        lines.append(f"| {v} | {s:.2f} | {p} | {delta_str} |")
        prev_score = s
    return "\n".join(lines) + "\n"


def cmd_init(args):
    base_dir = args.base_dir
    score = args.baseline_score
    os.makedirs(base_dir, exist_ok=True)

    summary = {
        "iterations": 0,
        "best": {"version": "baseline", "combined_score": score},
        "worst": {"version": "baseline", "combined_score": score},
        "history": [
            {"version": "baseline", "combined_score": score, "parent": None}
        ],
    }
    _write_json(_summary_path(base_dir), summary)
    _write_text(_state_md_path(base_dir), _render_state_md(summary))
    _write_text(_history_path(base_dir), "# Proposer History\n")


def cmd_update(args):
    base_dir = args.base_dir
    version = args.version
    scores = _read_json(args.scores)
    proposal_text = _read_text(args.proposal) if args.proposal else ""

    summary = _read_json(_summary_path(base_dir))
    combined = scores.get("combined_score", 0.0)
    parent = _detect_parent(proposal_text, summary["best"]["version"])

    entry = {
        "version": version,
        "combined_score": combined,
        "parent": parent,
    }
    summary["history"].append(entry)
    summary["iterations"] = len(summary["history"]) - 1

    non_baseline = [h for h in summary["history"] if h["version"] != "baseline"]
    if non_baseline:
        best_entry = max(non_baseline, key=lambda h: h["combined_score"])
        worst_entry = min(non_baseline, key=lambda h: h["combined_score"])
        summary["best"] = {
            "version": best_entry["version"],
            "combined_score": best_entry["combined_score"],
        }
        summary["worst"] = {
            "version": worst_entry["version"],
            "combined_score": worst_entry["combined_score"],
        }

    _write_json(_summary_path(base_dir), summary)
    _write_text(_state_md_path(base_dir), _render_state_md(summary))

    parent_score = None
    for h in summary["history"]:
        if h["version"] == parent:
            parent_score = h["combined_score"]
            break

    is_regression = parent_score is not None and combined < parent_score - 0.01
    regression_tag = " <- REGRESSION" if is_regression else ""

    proposal_lines = proposal_text.strip().split("\n")
    summary_line = ""
    for line in proposal_lines:
        stripped = line.strip()
        if stripped and not re.match(r"^[Bb]ased on", stripped):
            summary_line = stripped
            break

    history_entry = f"\n## {version} (score: {combined:.2f}){regression_tag}\n{summary_line}\n"
    history_path = _history_path(base_dir)
    with open(history_path, "a") as f:
        f.write(history_entry)


def cmd_show(args):
    base_dir = args.base_dir
    summary = _read_json(_summary_path(base_dir))
    best = summary["best"]
    worst = summary["worst"]

    print(f"Harness Evolver — Iteration {summary['iterations']}")
    print(f"Best:  {best['version']}  score: {best['combined_score']:.2f}")
    print(f"Worst: {worst['version']}  score: {worst['combined_score']:.2f}")
    print()
    for entry in summary["history"]:
        v = entry["version"]
        s = entry["combined_score"]
        bar_len = int(s * 30)
        bar = "\u2588" * bar_len
        print(f"  {v:>10}: {s:.2f} {bar}")


def main():
    parser = argparse.ArgumentParser(description="Harness Evolver state manager")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init")
    p_init.add_argument("--base-dir", required=True)
    p_init.add_argument("--baseline-score", type=float, required=True)

    p_update = sub.add_parser("update")
    p_update.add_argument("--base-dir", required=True)
    p_update.add_argument("--version", required=True)
    p_update.add_argument("--scores", required=True)
    p_update.add_argument("--proposal", default=None)

    p_show = sub.add_parser("show")
    p_show.add_argument("--base-dir", required=True)

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "show":
        cmd_show(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
