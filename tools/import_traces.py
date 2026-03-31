#!/usr/bin/env python3
"""Import LangSmith Traces as Eval Tasks for Harness Evolver.

Transforms LangSmith trace JSON (from langsmith-cli) into task JSON files
for the evaluation set. Prioritizes traces with negative feedback.

Usage:
    python3 import_traces.py \
        --traces-json /tmp/langsmith_traces.json \
        --output-dir .harness-evolver/eval/tasks/ \
        --prefix imported \
        [--max-tasks 30]

Stdlib-only. No external dependencies.
"""

import argparse
import hashlib
import json
import os
import re
import sys


def load_json(path):
    """Load JSON file, return None if missing or invalid."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def extract_input_from_trace(run):
    """Extract the user input from a LangSmith run's inputs field.

    Handles multiple LangChain serialization formats:
    - Direct {"input": "..."} field
    - {"messages": [[HumanMessage, ...]]} format
    - {"question": "..."} or {"query": "..."} fields
    """
    inputs = run.get("inputs", {})
    if not inputs:
        return None

    if isinstance(inputs, str):
        return inputs

    # Direct input field
    for key in ("input", "question", "query", "prompt", "text", "user_input"):
        if key in inputs and isinstance(inputs[key], str):
            return inputs[key]

    # LangChain messages format
    messages = inputs.get("messages") or inputs.get("input")
    if isinstance(messages, list):
        # Might be [[msg1, msg2]] (batched) or [msg1, msg2]
        if messages and isinstance(messages[0], list):
            messages = messages[0]
        for msg in messages:
            if isinstance(msg, dict):
                # {"type": "human", "content": "..."}
                if msg.get("type") in ("human", "HumanMessage") or msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content:
                        return content
                    if isinstance(content, list):
                        # Multi-modal: [{"type": "text", "text": "..."}]
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                return part.get("text", "")
            elif isinstance(msg, str) and msg:
                return msg

    # Fallback: stringify the whole inputs
    flat = json.dumps(inputs)
    if len(flat) > 20:  # Only if there's meaningful content
        return flat[:2000]

    return None


def extract_feedback(run):
    """Extract user feedback from a LangSmith run."""
    feedback = run.get("feedback_stats") or run.get("feedback") or {}
    if not feedback:
        return None

    # feedback_stats format: {"thumbs_up": N, "thumbs_down": N}
    if isinstance(feedback, dict):
        up = feedback.get("thumbs_up", 0) or feedback.get("positive", 0)
        down = feedback.get("thumbs_down", 0) or feedback.get("negative", 0)
        if down > 0:
            return "negative"
        if up > 0:
            return "positive"
    return None


def infer_difficulty(text):
    """Infer difficulty from input characteristics."""
    if not text:
        return "medium"
    length = len(text)
    # Count question marks, clauses, etc.
    questions = text.count("?")
    sentences = len(re.split(r"[.!?]+", text))

    if length < 50 and questions <= 1:
        return "easy"
    if length > 500 or questions > 2 or sentences > 5:
        return "hard"
    return "medium"


def short_id(run_id):
    """Create a short deterministic ID from a full run ID."""
    return hashlib.md5(str(run_id).encode()).hexdigest()[:8]


def main():
    parser = argparse.ArgumentParser(description="Import LangSmith traces as eval tasks")
    parser.add_argument("--traces-json", required=True, help="Path to langsmith-cli JSON output")
    parser.add_argument("--output-dir", required=True, help="Directory to write task JSON files")
    parser.add_argument("--prefix", default="imported", help="Prefix for task IDs (default: imported)")
    parser.add_argument("--max-tasks", type=int, default=30, help="Max tasks to import (default: 30)")
    parser.add_argument("--prioritize-negative", action="store_true", default=True,
                        help="Import negative-feedback traces first (default: true)")
    args = parser.parse_args()

    traces = load_json(args.traces_json)
    if not traces:
        print("No traces found or invalid JSON — nothing to import")
        return

    if isinstance(traces, dict):
        # Might be wrapped in {"runs": [...]}
        traces = traces.get("runs", traces.get("data", [traces]))

    if not isinstance(traces, list):
        print("Unexpected traces format — expected a JSON array")
        return

    # Sort: negative feedback first, then errors, then the rest
    if args.prioritize_negative:
        def priority(run):
            fb = extract_feedback(run)
            has_error = bool(run.get("error"))
            if fb == "negative":
                return 0
            if has_error:
                return 1
            return 2
        traces.sort(key=priority)

    os.makedirs(args.output_dir, exist_ok=True)

    # Check for existing imported tasks to avoid duplicates
    existing_run_ids = set()
    for fname in os.listdir(args.output_dir):
        if fname.endswith(".json"):
            task = load_json(os.path.join(args.output_dir, fname))
            if task and task.get("metadata", {}).get("langsmith_run_id"):
                existing_run_ids.add(task["metadata"]["langsmith_run_id"])

    imported = 0
    skipped_no_input = 0
    skipped_duplicate = 0
    negative_count = 0

    for run in traces:
        if imported >= args.max_tasks:
            break

        run_id = str(run.get("id", ""))
        if run_id in existing_run_ids:
            skipped_duplicate += 1
            continue

        user_input = extract_input_from_trace(run)
        if not user_input or len(user_input.strip()) < 5:
            skipped_no_input += 1
            continue

        feedback = extract_feedback(run)
        has_error = bool(run.get("error"))
        task_id = f"{args.prefix}_{short_id(run_id)}"

        task = {
            "id": task_id,
            "input": user_input.strip(),
            "metadata": {
                "difficulty": infer_difficulty(user_input),
                "category": run.get("name", "unknown"),
                "type": "production",
                "source": "imported",
                "langsmith_run_id": run_id,
                "had_error": has_error,
                "user_feedback": feedback,
            },
        }

        out_path = os.path.join(args.output_dir, f"{task_id}.json")
        with open(out_path, "w") as f:
            json.dump(task, f, indent=2)

        imported += 1
        if feedback == "negative":
            negative_count += 1

    summary = {
        "imported": imported,
        "negative_feedback": negative_count,
        "skipped_no_input": skipped_no_input,
        "skipped_duplicate": skipped_duplicate,
        "total_traces": len(traces),
    }
    print(json.dumps(summary))
    print(f"Imported {imported} production traces as tasks ({negative_count} with negative feedback)")
    if skipped_duplicate:
        print(f"  Skipped {skipped_duplicate} already-imported traces")
    if skipped_no_input:
        print(f"  Skipped {skipped_no_input} traces with no extractable input")


if __name__ == "__main__":
    main()
