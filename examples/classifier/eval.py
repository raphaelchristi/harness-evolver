#!/usr/bin/env python3
"""Exact match accuracy scorer for the classifier example."""

import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--tasks-dir", required=True)
    parser.add_argument("--scores", required=True)
    args = parser.parse_args()

    correct = 0
    total = 0
    per_task = {}

    for fname in sorted(os.listdir(args.tasks_dir)):
        if not fname.endswith(".json"):
            continue
        task_path = os.path.join(args.tasks_dir, fname)
        task = json.load(open(task_path))
        task_id = task["id"]

        result_path = os.path.join(args.results_dir, fname)
        if not os.path.exists(result_path):
            per_task[task_id] = {"score": 0.0, "error": "no output file"}
            total += 1
            continue

        result = json.load(open(result_path))
        expected = task["expected"].lower().strip()
        actual = result.get("output", "").lower().strip()
        match = actual == expected

        per_task[task_id] = {
            "score": 1.0 if match else 0.0,
            "expected": expected,
            "actual": actual,
        }
        correct += int(match)
        total += 1

    accuracy = correct / total if total > 0 else 0.0
    scores = {
        "combined_score": accuracy,
        "accuracy": accuracy,
        "total_tasks": total,
        "correct": correct,
        "per_task": per_task,
    }
    json.dump(scores, open(args.scores, "w"), indent=2)


if __name__ == "__main__":
    main()
