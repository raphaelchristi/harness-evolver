#!/usr/bin/env python3
"""Test Suite Growth for Harness Evolver.

Generates regression test tasks when previously-failing tasks are now passing.
Creates mechanical variations of fixed tasks to prevent future regressions.

Usage:
    python3 test_growth.py \
        --current-scores .harness-evolver/harnesses/v003/scores.json \
        --previous-scores .harness-evolver/harnesses/v002/scores.json \
        --tasks-dir .harness-evolver/eval/tasks/ \
        --output-dir .harness-evolver/eval/tasks/ \
        --max-total-tasks 60

Stdlib-only. No external dependencies.
"""

import argparse
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


def find_fixed_tasks(current_scores, previous_scores, fix_threshold_before=0.5, fix_threshold_after=0.8):
    """Find tasks that improved significantly: score < before_threshold → > after_threshold."""
    current_per_task = current_scores.get("per_task", {})
    previous_per_task = previous_scores.get("per_task", {})

    fixed = []
    for tid, curr_data in current_per_task.items():
        if not isinstance(curr_data, dict):
            continue
        curr_score = curr_data.get("score", 0)
        prev_data = previous_per_task.get(tid, {})
        prev_score = prev_data.get("score", 0) if isinstance(prev_data, dict) else 0

        if prev_score < fix_threshold_before and curr_score > fix_threshold_after:
            fixed.append({
                "task_id": tid,
                "previous_score": prev_score,
                "current_score": curr_score,
                "improvement": curr_score - prev_score,
            })

    # Sort by improvement (biggest fixes first)
    fixed.sort(key=lambda x: -x["improvement"])
    return fixed


def count_existing_tasks(directory):
    """Count existing task JSON files in directory."""
    if not os.path.isdir(directory):
        return 0
    return sum(1 for f in os.listdir(directory) if f.endswith(".json"))


def next_regression_id(output_dir):
    """Find the next available regression task ID."""
    existing = set()
    if os.path.isdir(output_dir):
        for fname in os.listdir(output_dir):
            m = re.match(r"regression_(\d+)\.json", fname)
            if m:
                existing.add(int(m.group(1)))
    n = 1
    while n in existing:
        n += 1
    return n


def generate_variations(original_input, task_id):
    """Generate 2-3 mechanical variations of an input string.

    Uses simple string transforms — no LLM needed:
    - Rephrase by reordering
    - Add qualifying clause
    - Simplify to minimal form
    """
    variations = []
    text = original_input.strip()

    # Variation 1: Add a qualifying clause
    qualifiers = [
        "Please be specific and detailed in your response.",
        "Consider edge cases in your answer.",
        "Provide a concise but thorough response.",
        "Think step by step before answering.",
    ]
    # Pick qualifier based on hash of task_id for determinism
    qi = hash(task_id) % len(qualifiers)
    v1 = f"{text}\n\n{qualifiers[qi]}"
    variations.append(("qualified", v1))

    # Variation 2: Reorder sentences if multiple exist
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) >= 2:
        # Swap first two sentences
        reordered = sentences[1:] + sentences[:1]
        v2 = " ".join(reordered)
        variations.append(("reordered", v2))
    else:
        # If single sentence, prepend "Given the context: "
        v2 = f"Given the following context, {text[0].lower()}{text[1:]}" if len(text) > 1 else text
        variations.append(("rephrased", v2))

    # Variation 3: Minimal version — strip to core question
    # Remove qualifiers, keep just the main ask
    minimal = text
    # Strip common padding phrases
    for prefix in ["Please ", "Can you ", "Could you ", "I would like you to ", "I need you to "]:
        if minimal.startswith(prefix):
            minimal = minimal[len(prefix):]
            minimal = minimal[0].upper() + minimal[1:] if minimal else minimal
            break
    if minimal != text:
        variations.append(("minimal", minimal))

    return variations


def main():
    parser = argparse.ArgumentParser(description="Generate regression test tasks from score improvements")
    parser.add_argument("--current-scores", required=True, help="Path to current version's scores.json")
    parser.add_argument("--previous-scores", required=True, help="Path to previous version's scores.json")
    parser.add_argument("--tasks-dir", required=True, help="Path to eval/tasks/ (to read originals)")
    parser.add_argument("--output-dir", required=True, help="Directory to write regression tasks")
    parser.add_argument("--max-total-tasks", type=int, default=60, help="Cap total tasks in output-dir (default 60)")
    args = parser.parse_args()

    current = load_json(args.current_scores)
    previous = load_json(args.previous_scores)

    if not current or not previous:
        print("Missing scores files — skipping test growth")
        return

    # Find tasks that were fixed
    fixed = find_fixed_tasks(current, previous)
    if not fixed:
        print("No tasks improved significantly — no regression tasks needed")
        return

    # Check capacity
    existing_count = count_existing_tasks(args.output_dir)
    available_slots = args.max_total_tasks - existing_count
    if available_slots <= 0:
        print(f"Task suite already at capacity ({existing_count}/{args.max_total_tasks}) — skipping growth")
        return

    os.makedirs(args.output_dir, exist_ok=True)
    regression_id = next_regression_id(args.output_dir)
    tasks_added = 0
    fixed_ids = []

    for fix_info in fixed:
        if tasks_added >= available_slots:
            break

        tid = fix_info["task_id"]
        # Load original task
        task_path = os.path.join(args.tasks_dir, f"{tid}.json")
        original = load_json(task_path)
        if not original:
            continue

        original_input = original.get("input", "")
        if not original_input:
            continue

        original_meta = original.get("metadata", {})
        variations = generate_variations(original_input, tid)

        for var_type, var_input in variations:
            if tasks_added >= available_slots:
                break

            reg_id = f"regression_{regression_id:03d}"
            task = {
                "id": reg_id,
                "input": var_input,
                "metadata": {
                    "difficulty": original_meta.get("difficulty", "medium"),
                    "category": original_meta.get("category", "unknown"),
                    "type": "regression",
                    "source": "regression",
                    "regression_for": tid,
                    "variation": var_type,
                    "previous_score": fix_info["previous_score"],
                    "fixed_at_score": fix_info["current_score"],
                },
            }

            # Include expected if original had it
            if "expected" in original:
                task["expected"] = original["expected"]

            out_path = os.path.join(args.output_dir, f"{reg_id}.json")
            with open(out_path, "w") as f:
                json.dump(task, f, indent=2)

            tasks_added += 1
            regression_id += 1

        fixed_ids.append(tid)

    # Output summary
    summary = {
        "tasks_added": tasks_added,
        "fixed_tasks": fixed_ids,
        "total_tasks_now": existing_count + tasks_added,
        "max_total_tasks": args.max_total_tasks,
    }
    print(json.dumps(summary))
    print(f"Added {tasks_added} regression tasks to lock in improvements on: {', '.join(fixed_ids)}")


if __name__ == "__main__":
    main()
