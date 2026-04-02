#!/usr/bin/env python3
"""Mine Claude Code session history for eval dataset examples.

Reads ~/.claude/ session files to extract real user interactions
that can be used as evaluation data. Filters for relevance to the
agent being optimized, detects and skips secrets.

Usage:
    python3 mine_sessions.py \
        --agent-description "A ReAct agent that answers questions using tools" \
        --output session_examples.json \
        [--max-examples 50]

Stdlib-only except for secret_filter (local import).
"""

import argparse
import glob
import json
import os
import sys


def find_session_files():
    """Find Claude Code session history files."""
    candidates = [
        os.path.expanduser("~/.claude/history.jsonl"),
        os.path.expanduser("~/.claude/sessions/*/messages.jsonl"),
    ]
    found = []
    for pattern in candidates:
        found.extend(glob.glob(pattern))
    return found


def extract_messages(file_path):
    """Extract user->assistant message pairs from a session file."""
    pairs = []
    try:
        with open(file_path) as f:
            messages = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    messages.append(msg)
                except json.JSONDecodeError:
                    continue

            for i in range(len(messages) - 1):
                if (messages[i].get("role") == "user" and
                    messages[i + 1].get("role") == "assistant"):
                    user_text = messages[i].get("content", "")
                    if isinstance(user_text, list):
                        user_text = " ".join(
                            p.get("text", "") for p in user_text
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    asst_text = messages[i + 1].get("content", "")
                    if isinstance(asst_text, list):
                        asst_text = " ".join(
                            p.get("text", "") for p in asst_text
                            if isinstance(p, dict) and p.get("type") == "text"
                        )

                    if user_text and len(user_text) > 10:
                        pairs.append({
                            "input": user_text[:500],
                            "output_preview": asst_text[:200] if asst_text else "",
                            "source_file": os.path.basename(file_path),
                        })
    except (OSError, UnicodeDecodeError):
        pass
    return pairs


def filter_relevant(pairs, agent_description, max_examples=50):
    """Simple keyword-based relevance filter."""
    stop_words = {"a", "an", "the", "is", "are", "was", "were", "that", "this",
                  "and", "or", "for", "to", "in", "on", "with", "using"}
    keywords = set(
        w.lower() for w in agent_description.split()
        if len(w) > 3 and w.lower() not in stop_words
    )

    scored = []
    for pair in pairs:
        input_words = set(pair["input"].lower().split())
        overlap = len(keywords & input_words)
        if overlap >= 1:
            scored.append((overlap, pair))

    scored.sort(key=lambda x: -x[0])
    return [pair for _, pair in scored[:max_examples]]


def main():
    parser = argparse.ArgumentParser(description="Mine Claude Code sessions for eval data")
    parser.add_argument("--agent-description", required=True, help="Description of the agent being optimized")
    parser.add_argument("--output", default="session_examples.json")
    parser.add_argument("--max-examples", type=int, default=50)
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(__file__))
    try:
        from secret_filter import has_secrets
    except ImportError:
        has_secrets = lambda text: False  # noqa: E731

    session_files = find_session_files()
    if not session_files:
        print("No Claude Code session files found.", file=sys.stderr)
        print(json.dumps({"mined": 0, "output": args.output}))
        sys.exit(0)

    print(f"Found {len(session_files)} session file(s)", file=sys.stderr)

    all_pairs = []
    secrets_skipped = 0
    for sf in session_files:
        pairs = extract_messages(sf)
        for p in pairs:
            if has_secrets(p["input"]) or has_secrets(p.get("output_preview", "")):
                secrets_skipped += 1
                continue
            all_pairs.append(p)

    print(f"Extracted {len(all_pairs)} message pairs ({secrets_skipped} skipped for secrets)", file=sys.stderr)

    relevant = filter_relevant(all_pairs, args.agent_description, args.max_examples)
    print(f"Filtered to {len(relevant)} relevant examples", file=sys.stderr)

    examples = []
    for p in relevant:
        examples.append({
            "input": p["input"],
            "metadata": {"source": "session_mining", "source_file": p["source_file"]},
        })

    output = {"examples": examples, "count": len(examples), "source": "claude_code_sessions"}
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(json.dumps({"mined": len(examples), "output": args.output}))


if __name__ == "__main__":
    main()
