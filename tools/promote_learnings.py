#!/usr/bin/env python3
"""Promote proven evolution learnings to CLAUDE.md.

Reads evolution_memory.md, extracts insights with recurrence >= threshold,
and appends them to the project's CLAUDE.md as permanent rules.

This implements "compound learning" — each evolution session permanently
improves the project, not just the code.

Usage:
    python3 promote_learnings.py --memory evolution_memory.md --target CLAUDE.md --threshold 5
    python3 promote_learnings.py --memory evolution_memory.md --dry-run

Stdlib-only — no langsmith dependency.

References:
    - Compound Engineering (EveryInc): explicit codification of learnings
    - Self-Improving Agent (pskoett): 3-tier promotion with quantitative thresholds
"""

import argparse
import json
import os
import re
import sys


def parse_evolution_memory(memory_path):
    """Parse evolution_memory.md and extract insights with recurrence counts."""
    if not os.path.exists(memory_path):
        return []

    insights = []
    with open(memory_path) as f:
        content = f.read()

    # Parse "Key Insights" section — format: "N. **text** [rec:N]"
    # Also handles: "N. text [rec:N]" and "- text [rec:N]"
    pattern = r'(?:^[\d]+\.\s+|\-\s+)\*{0,2}(.+?)\*{0,2}\s+\[rec:(\d+)\]'
    for match in re.finditer(pattern, content, re.MULTILINE):
        text = match.group(1).strip()
        rec = int(match.group(2))
        insights.append({"text": text, "recurrence": rec})

    return insights


def format_as_claude_rules(insights, project_name=""):
    """Format insights as CLAUDE.md rules."""
    if not insights:
        return ""

    lines = [
        "",
        f"## Evolution Learnings{' — ' + project_name if project_name else ''}",
        "",
        "Rules learned from automated evolution (promoted from evolution_memory.md):",
        "",
    ]
    for i, insight in enumerate(insights, 1):
        lines.append(f"- {insight['text']}")

    lines.append("")
    return "\n".join(lines)


def append_to_claude_md(target_path, rules_text, dry_run=False):
    """Append rules to CLAUDE.md. Creates file if it doesn't exist."""
    if dry_run:
        print("DRY RUN — would append to", target_path)
        print(rules_text)
        return True

    # Check if rules already exist (prevent duplicates)
    if os.path.exists(target_path):
        with open(target_path) as f:
            existing = f.read()
        if "## Evolution Learnings" in existing:
            print("Evolution Learnings section already exists in CLAUDE.md. Skipping to prevent duplicates.", file=sys.stderr)
            return False

    with open(target_path, "a") as f:
        f.write(rules_text)

    return True


def main():
    parser = argparse.ArgumentParser(description="Promote evolution learnings to CLAUDE.md")
    parser.add_argument("--memory", default="evolution_memory.md", help="Path to evolution_memory.md")
    parser.add_argument("--target", default="CLAUDE.md", help="Path to CLAUDE.md to append to")
    parser.add_argument("--threshold", type=int, default=5, help="Minimum recurrence to promote (default 5)")
    parser.add_argument("--project", default="", help="Project name for section header")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be promoted without writing")
    parser.add_argument("--output", default=None, help="Write promoted insights to JSON file")
    args = parser.parse_args()

    insights = parse_evolution_memory(args.memory)
    if not insights:
        print(json.dumps({"promoted": 0, "total_insights": 0}))
        return

    promotable = [i for i in insights if i["recurrence"] >= args.threshold]

    if not promotable:
        print(json.dumps({
            "promoted": 0,
            "total_insights": len(insights),
            "max_recurrence": max(i["recurrence"] for i in insights),
            "threshold": args.threshold,
        }))
        return

    rules_text = format_as_claude_rules(promotable, args.project)
    success = append_to_claude_md(args.target, rules_text, args.dry_run)

    result = {
        "promoted": len(promotable) if success else 0,
        "total_insights": len(insights),
        "threshold": args.threshold,
        "insights": [i["text"] for i in promotable],
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
