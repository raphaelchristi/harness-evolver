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


# Keywords that signal a failure is likely caused by missing capability
# rather than prompt/instruction wording. When these appear in failure
# clusters we emit a tool-gap lens so the proposer considers creating
# a new tool instead of rewriting prompts.
TOOL_GAP_SIGNALS = (
    "tool", "function", "api", "calculator", "search", "retriev",
    "fetch", "parser", "extract", "regex", "browser", "shell",
    "subprocess", "python_repl", "code_interpreter", "memory",
)


def _gap_analysis(config):
    """Classify evolution regime based on best_score vs target_score.

    Returns one of: "weak" (far from target), "mid", "ceiling" (near target),
    plus the numeric values for logging. Implements the empirical finding
    from Autogenesis Table 1 that weak models gain most from prompt/solution
    evolution while near-ceiling models only gain from tool evolution.
    """
    best = config.get("best_score")
    target = config.get("target_score")
    if best is None:
        return {"regime": "unknown", "best": None, "target": target, "gap": None}
    # Fallback target when not configured — assume 0.9 is "good enough"
    effective_target = target if target is not None else 0.9
    gap = max(0.0, effective_target - best)
    if gap >= 0.20:
        regime = "weak"
    elif gap <= 0.05:
        regime = "ceiling"
    else:
        regime = "mid"
    return {
        "regime": regime,
        "best": best,
        "target": target,
        "effective_target": effective_target,
        "gap": gap,
    }


def _cluster_text(cluster):
    parts = [str(cluster.get("description", "")), str(cluster.get("type", ""))]
    return " ".join(parts).lower()


def _tool_gap_signal(strategy):
    """True if any failure cluster or failing example points at missing capability."""
    for c in strategy.get("failure_clusters", []):
        text = _cluster_text(c)
        if any(s in text for s in TOOL_GAP_SIGNALS):
            return True
    for ex in strategy.get("failing_examples", []):
        err = (ex.get("error") or "").lower()
        if "no tool" in err or "has no attribute" in err or "tool not found" in err:
            return True
        if "ModuleNotFoundError" in (ex.get("error") or ""):
            return True
    return False


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
        "regime": _gap_analysis(config),
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

    # Regime-aware priority lens (weak-model vs near-ceiling)
    # This must come first so it survives the severity sort + truncation.
    gap = _gap_analysis(config)
    if gap["regime"] == "weak":
        lens_id += 1
        lenses.append({
            "id": lens_id,
            "question": (
                f"Baseline score {gap['best']:.3f} is far from target "
                f"{gap['effective_target']:.2f} (gap {gap['gap']:.2f}). "
                "Focus on prompt clarity and instruction quality — rewrite the "
                "system prompt and planner instructions to reduce ambiguity. "
                "Empirically, weak-baseline agents gain most from prompt edits."
            ),
            "source": "regime_weak",
            "severity": "high",
            "context": gap,
        })
    elif gap["regime"] == "ceiling" or _tool_gap_signal(strategy):
        reason = (
            f"Baseline score {gap['best']:.3f} is near target "
            f"{gap['effective_target']:.2f} — prompt edits have diminishing returns. "
            "Inspect failing examples for missing capabilities."
        ) if gap["regime"] == "ceiling" else (
            "Failing examples reference missing tools or capabilities."
        )
        lens_id += 1
        lenses.append({
            "id": lens_id,
            "question": (
                f"{reason} Consider CREATING A NEW TOOL or helper function that the "
                "agent can call. Identify one concrete capability the agent lacks, "
                "write the tool as a new Python function with a clear docstring, "
                "register it with the agent, and reference it from the system prompt. "
                "Do not just rewrite existing prompts."
            ),
            "source": "tool_gap",
            "severity": "critical" if gap["regime"] == "ceiling" else "high",
            "context": {"gap": gap, "has_tool_signal": _tool_gap_signal(strategy)},
        })

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

    # Uniform failure lens — when there are failing examples but no cluster lenses were generated
    # (e.g., all examples fail with same error like "python: not found")
    failing_examples = strategy.get("failing_examples", [])
    if failing_examples and not any(l["source"] == "failure_cluster" for l in lenses):
        # Check if all errors are the same
        errors = [ex.get("error", "") for ex in failing_examples if ex.get("error")]
        common_error = errors[0] if errors and len(set(errors)) == 1 else None
        if common_error:
            lens_id += 1
            lenses.append({
                "id": lens_id,
                "question": f"All {len(failing_examples)} examples fail with the same error: \"{common_error[:150]}\". Is this a code bug, configuration issue, or environment problem? What's the fix?",
                "source": "uniform_failure",
                "severity": "critical",
                "context": {"error": common_error[:300], "count": len(failing_examples)},
            })
        else:
            # Diverse errors but no clusters — create a general failure lens
            lens_id += 1
            lenses.append({
                "id": lens_id,
                "question": f"{len(failing_examples)} examples are failing with various errors. What are the root causes and what changes would fix the most failures?",
                "source": "failure_analysis",
                "severity": "high",
                "context": {"count": len(failing_examples)},
            })

    # Input diversity lens — when we have failing examples, suggest investigating by input type
    if failing_examples and len(failing_examples) >= 5 and len(lenses) < max_lenses - 1:
        previews = [ex.get("input_preview", "")[:50] for ex in failing_examples[:5]]
        lens_id += 1
        lenses.append({
            "id": lens_id,
            "question": f"The agent fails on diverse inputs like: {'; '.join(previews[:3])}. Are there different failure modes for different input types?",
            "source": "input_diversity",
            "severity": "medium",
            "context": {"sample_inputs": previews},
        })

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

    regime = strategy.get("regime") or {}
    if regime.get("regime") not in (None, "unknown"):
        best = regime.get("best")
        target = regime.get("effective_target")
        gap = regime.get("gap") or 0
        lines.append(f"## Regime: **{regime['regime']}**  (best {best:.3f} vs target {target:.2f}, gap {gap:.3f})")
        if regime["regime"] == "weak":
            lines.append("- High headroom → prioritize prompt/instruction rewrites.")
        elif regime["regime"] == "ceiling":
            lines.append("- Near target → prioritize creating new tools/capabilities. Prompt edits have diminishing returns.")
        else:
            lines.append("- Mid-range → balanced prompt edits + targeted fixes.")
        lines.append("")

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
