#!/usr/bin/env python3
"""Passthrough eval — collects outputs for judge subagent scoring.

When no custom eval.py exists, this is used as the default. It does NOT score
outputs — it collects them and marks them for the judge subagent to evaluate.
The evolve skill detects eval_type=pending-judge and spawns the judge agent.
"""

import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--tasks-dir", required=True)
    parser.add_argument("--scores", required=True)
    args = parser.parse_args()

    per_task = {}
    for fname in sorted(os.listdir(args.tasks_dir)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(args.tasks_dir, fname)) as f:
            task = json.load(f)
        task_id = task["id"]

        result_path = os.path.join(args.results_dir, fname)
        output = ""
        if os.path.exists(result_path):
            with open(result_path) as f:
                result = json.load(f)
            output = str(result.get("output", ""))

        per_task[task_id] = {
            "score": -1,
            "input": str(task.get("input", ""))[:500],
            "output": output[:500],
        }

    scores = {
        "combined_score": -1,
        "eval_type": "pending-judge",
        "total_tasks": len(per_task),
        "per_task": per_task,
    }
    with open(args.scores, "w") as f:
        json.dump(scores, f, indent=2)

    print(f"Collected {len(per_task)} task outputs for judge scoring.")


if __name__ == "__main__":
    main()
