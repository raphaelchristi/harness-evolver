#!/usr/bin/env python3
"""Cross-iteration memory consolidation for Harness Evolver.

Inspired by Claude Code's autoDream pattern. Analyzes evolution history
to identify recurring patterns, successful strategies, and wasted approaches.
Produces evolution_memory.md for proposer briefings.

Usage:
    python3 consolidate.py --config .evolver.json --output evolution_memory.md
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def orient(config):
    """Phase 1: Scan current state and history."""
    history = config.get("history", [])
    iterations = config.get("iterations", 0)
    best_score = config.get("best_score", 0)
    baseline_score = history[0]["score"] if history else 0

    return {
        "iterations": iterations,
        "best_score": best_score,
        "baseline_score": baseline_score,
        "improvement": best_score - baseline_score,
        "history": history,
    }


def gather(config, comparison_files):
    """Phase 2: Extract signals from trace insights and comparisons."""
    signals = {
        "winning_strategies": [],
        "losing_strategies": [],
        "recurring_failures": {},
        "score_deltas": [],
    }

    for comp_file in comparison_files:
        if not os.path.exists(comp_file):
            continue
        try:
            with open(comp_file) as f:
                data = json.load(f)
            comparison = data.get("comparison", data)

            winner = comparison.get("winner", {})
            if winner:
                signals["winning_strategies"].append({
                    "experiment": winner.get("experiment", ""),
                    "score": winner.get("score", 0),
                })

            for candidate in comparison.get("all_candidates", []):
                if candidate.get("experiment") != winner.get("experiment"):
                    signals["losing_strategies"].append({
                        "experiment": candidate.get("experiment", ""),
                        "score": candidate.get("score", 0),
                    })
        except (json.JSONDecodeError, OSError):
            continue

    # Compute score deltas from history
    history = config.get("history", [])
    for i in range(1, len(history)):
        signals["score_deltas"].append({
            "version": history[i]["version"],
            "delta": history[i]["score"] - history[i - 1]["score"],
            "score": history[i]["score"],
        })

    # Read trace insights for recurring patterns
    if os.path.exists("trace_insights.json"):
        try:
            with open("trace_insights.json") as f:
                insights = json.load(f)
            for issue in insights.get("top_issues", []):
                pattern = issue.get("pattern", issue.get("description", "unknown"))
                if pattern not in signals["recurring_failures"]:
                    signals["recurring_failures"][pattern] = 0
                signals["recurring_failures"][pattern] += 1
        except (json.JSONDecodeError, OSError):
            pass

    return signals


def consolidate(orientation, signals, existing_memory=None):
    """Phase 3: Merge signals into consolidated memory."""
    insights = []

    # Winning approach tracking (from comparison data)
    winning = signals.get("winning_strategies", [])
    if winning:
        win_count = len(winning)
        best_score = max(w.get("score", 0) for w in winning)
        insights.append({
            "type": "strategy_effectiveness",
            "insight": f"Best candidate score: {best_score:.3f} across {win_count} iterations",
            "recurrence": win_count,
            "data": {"win_count": win_count, "best_score": best_score},
        })

    # Recurring failures (only promote if seen 2+ times)
    recurring = {k: v for k, v in signals.get("recurring_failures", {}).items() if v >= 2}
    for pattern, count in sorted(recurring.items(), key=lambda x: -x[1]):
        insights.append({
            "type": "recurring_failure",
            "insight": f"Recurring failure ({count}x): {pattern}",
            "recurrence": count,
        })

    # Score trajectory
    deltas = signals.get("score_deltas", [])
    if deltas:
        positive = [d for d in deltas if d["delta"] > 0]
        negative = [d for d in deltas if d["delta"] < 0]
        stagnant = [d for d in deltas if abs(d["delta"]) < 0.01]
        insights.append({
            "type": "trajectory",
            "insight": f"Score trajectory: {len(positive)} improvements, {len(negative)} regressions, {len(stagnant)} stagnant",
            "recurrence": len(deltas),
        })

    # Merge with existing memory (update recurrence counts)
    if existing_memory:
        for existing in existing_memory.get("insights", []):
            found = False
            for new in insights:
                if new["type"] == existing["type"] and new["insight"] == existing["insight"]:
                    new["recurrence"] = max(new["recurrence"], existing.get("recurrence", 1)) + 1
                    found = True
                    break
            if not found and existing.get("recurrence", 1) >= 2:
                insights.append(existing)

    return insights


def prune(insights, max_insights=20):
    """Phase 4: Cap size, remove stale entries."""
    sorted_insights = sorted(insights, key=lambda x: -x.get("recurrence", 1))
    return sorted_insights[:max_insights]


def format_memory(orientation, insights):
    """Format consolidated memory as markdown."""
    lines = [
        "# Evolution Memory",
        "",
        f"*Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        f"*Iterations: {orientation['iterations']} | Best: {orientation['best_score']:.3f} | Baseline: {orientation['baseline_score']:.3f} | Improvement: +{orientation['improvement']:.3f}*",
        "",
        "## Key Insights (promoted after 2+ recurrences)",
        "",
    ]

    promoted = [i for i in insights if i.get("recurrence", 1) >= 2]
    other = [i for i in insights if i.get("recurrence", 1) < 2]

    if promoted:
        for insight in promoted:
            lines.append(f"- **[{insight['type']}]** {insight['insight']} (seen {insight['recurrence']}x)")
    else:
        lines.append("- No insights promoted yet (need 2+ recurrences)")

    if other:
        lines.append("")
        lines.append("## Observations (1 recurrence, pending promotion)")
        lines.append("")
        for insight in other:
            lines.append(f"- [{insight['type']}] {insight['insight']}")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Cross-iteration memory consolidation")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--output", default="evolution_memory.md", help="Output markdown path")
    parser.add_argument("--output-json", default="evolution_memory.json", help="Output JSON path")
    parser.add_argument("--comparison-files", nargs="*", default=[], help="Past comparison.json files")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    # Load existing memory if present
    existing = None
    if os.path.exists(args.output_json):
        try:
            with open(args.output_json) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Four-phase consolidation
    orientation = orient(config)
    signals = gather(config, args.comparison_files or ["comparison.json"])
    insights = consolidate(orientation, signals, existing)
    insights = prune(insights)

    # Write markdown
    memory_md = format_memory(orientation, insights)
    with open(args.output, "w") as f:
        f.write(memory_md)

    # Write JSON for programmatic access
    memory_json = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "orientation": orientation,
        "insights": insights,
    }
    with open(args.output_json, "w") as f:
        json.dump(memory_json, f, indent=2)

    print(memory_md)


if __name__ == "__main__":
    main()
