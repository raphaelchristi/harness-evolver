#!/usr/bin/env python3
"""Synthesize evolution strategy document from trace analysis.

Reads trace_insights.json, best_results.json, and evolution_memory.json
to produce a targeted strategy document with specific file paths,
line numbers, and concrete change recommendations for proposers.

Usage:
    python3 synthesize_strategy.py \
        --config .evolver.json \
        --trace-insights trace_insights.json \
        --best-results best_results.json \
        --evolution-memory evolution_memory.json \
        --output strategy.md
"""

import argparse
import json
import os
import sys


def load_json_safe(path):
    """Load JSON file, return None if missing or invalid."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def identify_target_files(config):
    """Identify which files proposers should focus on."""
    entry_point = config.get("entry_point", "")
    parts = entry_point.split()
    target_files = []
    for part in parts:
        if part.endswith(".py") and not part.startswith("-"):
            target_files.append(part)
    return target_files


def synthesize(config, insights, results, memory):
    """Produce strategy recommendations."""
    strategy = {
        "primary_targets": [],
        "failure_clusters": [],
        "recommended_approaches": [],
        "avoid": [],
    }

    strategy["primary_targets"] = identify_target_files(config)

    if insights:
        for issue in insights.get("top_issues", [])[:5]:
            strategy["failure_clusters"].append({
                "type": issue.get("type", "unknown"),
                "severity": issue.get("severity", "medium"),
                "description": issue.get("description", ""),
                "count": issue.get("count", 0),
            })

    if memory:
        for insight in memory.get("insights", []):
            if insight.get("recurrence", 0) >= 2:
                if insight["type"] == "strategy_effectiveness":
                    strategy["recommended_approaches"].append(insight["insight"])
                elif insight["type"] == "recurring_failure":
                    strategy["failure_clusters"].append({
                        "type": "recurring",
                        "severity": "high",
                        "description": insight["insight"],
                        "count": insight["recurrence"],
                    })

    if memory:
        for insight in memory.get("insights", []):
            if "losing" in insight.get("type", "") or "regression" in insight.get("type", ""):
                strategy["avoid"].append(insight["insight"])

    if results:
        per_example = results.get("per_example", {})
        failing = [(eid, data) for eid, data in per_example.items() if data.get("score", 0) < 0.5]
        failing.sort(key=lambda x: x[1].get("score", 0))
        strategy["failing_examples"] = [
            {
                "example_id": eid,
                "score": data["score"],
                "input_preview": data.get("input_preview", "")[:200],
                "error": data.get("error"),
            }
            for eid, data in failing[:10]
        ]

    return strategy


def format_strategy_md(strategy, config):
    """Format strategy as markdown document."""
    lines = [
        "# Evolution Strategy Document",
        "",
        f"*Framework: {config.get('framework', 'unknown')} | Entry point: {config.get('entry_point', 'N/A')}*",
        "",
    ]

    lines.append("## Target Files")
    for f in strategy.get("primary_targets", []):
        lines.append(f"- `{f}`")
    lines.append("")

    clusters = strategy.get("failure_clusters", [])
    if clusters:
        lines.append("## Failure Clusters (prioritized)")
        for i, c in enumerate(clusters, 1):
            lines.append(f"{i}. **[{c['severity']}]** {c['description']} (count: {c['count']})")
        lines.append("")

    approaches = strategy.get("recommended_approaches", [])
    if approaches:
        lines.append("## Recommended Approaches (from evolution memory)")
        for a in approaches:
            lines.append(f"- {a}")
        lines.append("")

    avoid = strategy.get("avoid", [])
    if avoid:
        lines.append("## Avoid (previously unsuccessful)")
        for a in avoid:
            lines.append(f"- {a}")
        lines.append("")

    failing = strategy.get("failing_examples", [])
    if failing:
        lines.append(f"## Top Failing Examples ({len(failing)})")
        for ex in failing:
            score = ex["score"]
            preview = ex["input_preview"][:100]
            error = f" — Error: {ex['error'][:80]}" if ex.get("error") else ""
            lines.append(f"- `{ex['example_id']}` (score: {score:.2f}): {preview}{error}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Synthesize evolution strategy")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--trace-insights", default="trace_insights.json")
    parser.add_argument("--best-results", default="best_results.json")
    parser.add_argument("--evolution-memory", default="evolution_memory.json")
    parser.add_argument("--output", default="strategy.md")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    insights = load_json_safe(args.trace_insights)
    results = load_json_safe(args.best_results)
    memory = load_json_safe(args.evolution_memory)

    strategy = synthesize(config, insights, results, memory)

    md = format_strategy_md(strategy, config)
    with open(args.output, "w") as f:
        f.write(md)

    json_path = args.output.replace(".md", ".json")
    with open(json_path, "w") as f:
        json.dump(strategy, f, indent=2)

    print(md)


if __name__ == "__main__":
    main()
