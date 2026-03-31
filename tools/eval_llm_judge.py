#!/usr/bin/env python3
"""LLM-as-judge evaluation script for Harness Evolver.

Scores harness outputs using an LLM judge across multiple quality dimensions:
accuracy, completeness, relevance, no_hallucination.

CLI interface matches existing evals: --results-dir, --tasks-dir, --scores.
Stdlib-only. No external dependencies.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_api import detect_provider, call_llm

DIMENSIONS = ["accuracy", "completeness", "relevance", "no_hallucination"]

WEIGHTS = {
    "accuracy": 0.4,
    "completeness": 0.2,
    "relevance": 0.2,
    "no_hallucination": 0.2,
}


def build_judge_prompt(task, result):
    """Build the evaluation prompt for the LLM judge."""
    prompt_parts = [
        "You are an expert evaluator. Assess the quality of the following output.",
        "",
        "QUESTION/INPUT:",
        str(task.get("input", "")),
        "",
        "OUTPUT TO EVALUATE:",
        str(result.get("output", "")),
    ]

    if "expected" in task:
        prompt_parts.extend([
            "",
            "REFERENCE ANSWER:",
            str(task["expected"]),
        ])

    prompt_parts.extend([
        "",
        "Score each dimension from 1 (worst) to 5 (best):",
        "- accuracy: Is the output factually correct and properly addresses the input?",
        "- completeness: Does it cover all relevant aspects?",
        "- relevance: Is it focused and on-topic?",
        "- no_hallucination: Does it avoid fabricating information not supported by context?",
        "",
        "Think step by step, then respond with ONLY this JSON:",
        '{"reasoning": "your analysis", "accuracy": N, "completeness": N, "relevance": N, "no_hallucination": N}',
    ])

    return "\n".join(prompt_parts)


def extract_json_scores(response):
    """Extract scoring JSON from LLM response. Handles fenced and bare JSON."""
    # Try direct parse
    try:
        data = json.loads(response.strip())
        if "accuracy" in data:
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Try extracting from markdown fences
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
    if fence_match:
        try:
            data = json.loads(fence_match.group(1))
            if "accuracy" in data:
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    # Try regex extraction for JSON with accuracy key
    json_match = re.search(r'\{[^{}]*"accuracy"\s*:\s*\d[^{}]*\}', response)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            if "accuracy" in data:
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def normalize_score(raw_score):
    """Normalize a 1-5 score to 0.0-1.0 range."""
    clamped = max(1, min(5, int(raw_score)))
    return (clamped - 1) / 4.0


def compute_combined_score(scores_dict):
    """Compute weighted combined score from normalized dimension scores."""
    total = 0.0
    for dim in DIMENSIONS:
        total += scores_dict.get(dim, 0.0) * WEIGHTS[dim]
    return total


def evaluate_task(provider, api_key, model, task, result):
    """Evaluate a single task with the LLM judge. Returns per-task score dict."""
    prompt = build_judge_prompt(task, result)

    try:
        response = call_llm(provider, api_key, model, prompt, max_tokens=2048)
    except Exception as e:
        return {
            "score": 0.0,
            "accuracy": 1, "completeness": 1, "relevance": 1, "no_hallucination": 1,
            "reasoning": f"LLM call failed: {e}",
            "error": str(e),
        }

    parsed = extract_json_scores(response)
    if parsed is None:
        return {
            "score": 0.0,
            "accuracy": 1, "completeness": 1, "relevance": 1, "no_hallucination": 1,
            "reasoning": f"Failed to parse judge response: {response[:200]}",
            "error": "parse_failed",
        }

    # Extract raw scores
    raw = {}
    normalized = {}
    for dim in DIMENSIONS:
        raw[dim] = parsed.get(dim, 1)
        normalized[dim] = normalize_score(raw[dim])

    combined = compute_combined_score(normalized)

    return {
        "score": round(combined, 4),
        "accuracy": raw["accuracy"],
        "completeness": raw["completeness"],
        "relevance": raw["relevance"],
        "no_hallucination": raw["no_hallucination"],
        "reasoning": parsed.get("reasoning", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="LLM-as-judge evaluation")
    parser.add_argument("--results-dir", required=True,
                        help="Directory with harness output JSON files")
    parser.add_argument("--tasks-dir", required=True,
                        help="Directory with task JSON files")
    parser.add_argument("--scores", required=True,
                        help="Output path for scores JSON")
    args = parser.parse_args()

    # Detect LLM provider
    provider, api_key, model = detect_provider()

    # Collect tasks
    task_files = sorted(f for f in os.listdir(args.tasks_dir) if f.endswith(".json"))
    if not task_files:
        print(f"FAIL: no .json task files in {args.tasks_dir}", file=sys.stderr)
        sys.exit(1)

    per_task = {}
    dimension_totals = {dim: 0.0 for dim in DIMENSIONS}
    total_combined = 0.0
    total_tasks = 0

    for task_file in task_files:
        # Load task
        task_path = os.path.join(args.tasks_dir, task_file)
        with open(task_path) as f:
            task = json.load(f)
        task_id = task["id"]

        # Load result
        result_path = os.path.join(args.results_dir, task_file)
        if os.path.exists(result_path):
            with open(result_path) as f:
                result = json.load(f)
        else:
            result = {"id": task_id, "output": "", "error": "no output file"}

        # Evaluate
        task_scores = evaluate_task(provider, api_key, model, task, result)
        per_task[task_id] = task_scores

        # Accumulate
        total_combined += task_scores["score"]
        for dim in DIMENSIONS:
            dimension_totals[dim] += normalize_score(task_scores[dim])
        total_tasks += 1

    # Compute averages
    if total_tasks > 0:
        combined_score = round(total_combined / total_tasks, 4)
        avg_dimensions = {
            dim: round(dimension_totals[dim] / total_tasks, 4) for dim in DIMENSIONS
        }
    else:
        combined_score = 0.0
        avg_dimensions = {dim: 0.0 for dim in DIMENSIONS}

    scores = {
        "combined_score": combined_score,
        "eval_type": "llm-judge",
        "judge_provider": provider,
        "judge_model": model,
        "dimensions": avg_dimensions,
        "weights": WEIGHTS,
        "total_tasks": total_tasks,
        "per_task": per_task,
    }

    # Write scores
    os.makedirs(os.path.dirname(os.path.abspath(args.scores)), exist_ok=True)
    with open(args.scores, "w") as f:
        json.dump(scores, f, indent=2)

    print(f"LLM judge evaluation complete. combined_score: {combined_score} "
          f"({total_tasks} tasks, provider: {provider}/{model})")


if __name__ == "__main__":
    main()
