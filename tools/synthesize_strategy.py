#!/usr/bin/env python3
"""Synthesize evolution strategy document and investigation lenses.

Reads trace_insights.json, best_results.json, evolution_memory.json,
and production_seed.json to produce a targeted strategy document with
specific file paths and concrete change recommendations for proposers.

When --lenses is specified, also generates a lenses.json file containing
investigation questions derived from failure clusters, architecture issues,
production data, and evolution memory. Each lens becomes a focused brief
for one proposer agent.

Usage:
    python3 synthesize_strategy.py \
        --config .evolver.json \
        --trace-insights trace_insights.json \
        --best-results best_results.json \
        --evolution-memory evolution_memory.json \
        --production-seed production_seed.json \
        --output strategy.md \
        --lenses lenses.json
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


def synthesize(config, insights, results, memory, production=None):
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

    # Production trace data
    if production:
        prod_data = {}
        stats = production.get("stats", {})
        if stats:
            prod_data["total_traces"] = stats.get("total_traces", 0)
            prod_data["error_rate"] = stats.get("error_rate", 0)
        categories = production.get("categories", [])
        if categories:
            prod_data["traffic_distribution"] = categories[:10]
        neg = production.get("negative_feedback_inputs", [])
        if neg:
            prod_data["negative_feedback"] = neg[:5]
        errors = production.get("error_patterns", production.get("errors", []))
        if errors:
            prod_data["production_errors"] = errors[:5] if isinstance(errors, list) else []
        slow = production.get("slow_queries", [])
        if slow:
            prod_data["slow_queries"] = slow[:5]
        if prod_data:
            strategy["production"] = prod_data

    return strategy


def generate_lenses(strategy, config, insights, results, memory, production, max_lenses=5):
    """Generate investigation lenses from available data sources."""
    lenses = []
    lens_id = 0

    # Failure cluster lenses (one per distinct cluster, max 3)
    for cluster in strategy.get("failure_clusters", [])[:3]:
        lens_id += 1
        desc = cluster["description"]
        severity = cluster["severity"]
        examples = []
        for ex in strategy.get("failing_examples", []):
            if ex.get("error") and cluster.get("type", "") in str(ex.get("error", "")):
                examples.append(ex["example_id"])
        if not examples:
            examples = [ex["example_id"] for ex in strategy.get("failing_examples", [])[:3]]
        lenses.append({
            "id": lens_id,
            "question": f"{desc} — what code change would fix this?",
            "source": "failure_cluster",
            "severity": severity,
            "context": {"examples": examples[:5]},
        })

    # Architecture lens from trace insights
    if insights:
        for issue in insights.get("top_issues", []):
            if issue.get("severity") == "high" and issue.get("type") in (
                "architecture", "routing", "topology", "structure",
            ):
                lens_id += 1
                lenses.append({
                    "id": lens_id,
                    "question": f"Architectural issue: {issue['description']} — what structural change would help?",
                    "source": "architecture",
                    "severity": "high",
                    "context": {"issue_type": issue["type"]},
                })
                break  # at most 1 architecture lens

    # Production lens
    if production:
        prod_issues = []
        neg = production.get("negative_feedback_inputs", [])
        if neg:
            prod_issues.append(f"Users gave negative feedback on {len(neg)} queries")
        errors = production.get("error_patterns", production.get("errors", []))
        if errors and isinstance(errors, list) and len(errors) > 0:
            prod_issues.append(f"Production errors: {str(errors[0])[:100]}")
        slow = production.get("slow_queries", [])
        if slow:
            prod_issues.append(f"{len(slow)} slow queries detected")
        if prod_issues:
            lens_id += 1
            lenses.append({
                "id": lens_id,
                "question": f"Production data shows: {'; '.join(prod_issues)}. How should the agent handle these real-world patterns?",
                "source": "production",
                "severity": "high",
                "context": {},
            })

    # Evolution memory lens — winning patterns
    if memory:
        for insight in memory.get("insights", []):
            if insight.get("type") == "strategy_effectiveness" and insight.get("recurrence", 0) >= 2:
                lens_id += 1
                lenses.append({
                    "id": lens_id,
                    "question": f"{insight['insight']} — what further improvements in this direction are possible?",
                    "source": "evolution_memory",
                    "severity": "medium",
                    "context": {"recurrence": insight["recurrence"]},
                })
                break  # at most 1 memory lens

    # Evolution memory lens — persistent failures
    if memory:
        for insight in memory.get("insights", []):
            if insight.get("type") == "recurring_failure" and insight.get("recurrence", 0) >= 3:
                lens_id += 1
                lenses.append({
                    "id": lens_id,
                    "question": f"{insight['insight']} — this has persisted {insight['recurrence']} iterations. Why?",
                    "source": "persistent_failure",
                    "severity": "critical",
                    "context": {"recurrence": insight["recurrence"]},
                })
                break  # at most 1 persistent failure lens

    # Open lens (always included)
    lens_id += 1
    lenses.append({
        "id": lens_id,
        "question": "Open investigation — read all context and investigate what stands out most to you.",
        "source": "open",
        "severity": "medium",
        "context": {},
    })

    # Sort by severity, take top max_lenses
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    lenses.sort(key=lambda l: severity_order.get(l["severity"], 2))
    lenses = lenses[:max_lenses]

    # Reassign sequential IDs after sorting/truncating
    for i, lens in enumerate(lenses):
        lens["id"] = i + 1

    return lenses


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

    prod = strategy.get("production", {})
    if prod:
        lines.append("## Production Insights")
        if prod.get("total_traces"):
            lines.append(f"- **Traces**: {prod['total_traces']} total, {prod.get('error_rate', 0):.1%} error rate")
        if prod.get("traffic_distribution"):
            lines.append(f"- **Traffic**: {', '.join(str(c) for c in prod['traffic_distribution'][:5])}")
        if prod.get("negative_feedback"):
            lines.append("- **Negative feedback inputs**:")
            for nf in prod["negative_feedback"]:
                lines.append(f"  - {str(nf)[:120]}")
        if prod.get("production_errors"):
            lines.append("- **Production errors**:")
            for pe in prod["production_errors"]:
                lines.append(f"  - {str(pe)[:120]}")
        if prod.get("slow_queries"):
            lines.append("- **Slow queries**:")
            for sq in prod["slow_queries"]:
                lines.append(f"  - {str(sq)[:120]}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Synthesize evolution strategy")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--trace-insights", default="trace_insights.json")
    parser.add_argument("--best-results", default="best_results.json")
    parser.add_argument("--evolution-memory", default="evolution_memory.json")
    parser.add_argument("--production-seed", default="production_seed.json")
    parser.add_argument("--output", default="strategy.md")
    parser.add_argument("--lenses", default=None, help="Output path for lenses JSON")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    insights = load_json_safe(args.trace_insights)
    results = load_json_safe(args.best_results)
    memory = load_json_safe(args.evolution_memory)
    production = load_json_safe(args.production_seed)

    strategy = synthesize(config, insights, results, memory, production)

    md = format_strategy_md(strategy, config)
    with open(args.output, "w") as f:
        f.write(md)

    json_path = args.output.replace(".md", ".json")
    with open(json_path, "w") as f:
        json.dump(strategy, f, indent=2)

    # Generate lenses if requested
    if args.lenses:
        max_proposers = config.get("max_proposers", 5)
        lens_list = generate_lenses(
            strategy, config, insights, results, memory, production,
            max_lenses=max_proposers,
        )
        from datetime import datetime, timezone
        lenses_output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lens_count": len(lens_list),
            "lenses": lens_list,
        }
        with open(args.lenses, "w") as f:
            json.dump(lenses_output, f, indent=2)
        print(f"Generated {len(lens_list)} lenses → {args.lenses}", file=sys.stderr)

    print(md)


if __name__ == "__main__":
    main()
