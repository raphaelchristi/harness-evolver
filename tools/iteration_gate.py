#!/usr/bin/env python3
"""Three-gate iteration trigger for Harness Evolver.

Evaluates whether the next evolution iteration should proceed based on:
1. Score gate: skip if no meaningful delta or no clustered failures
2. Cost gate: estimate token cost, stop if budget exceeded
3. Convergence gate: detect statistical plateau

Usage:
    python3 iteration_gate.py --config .evolver.json --output gate_result.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def score_gate(config, threshold=0.02):
    """Check if there's meaningful room for improvement."""
    history = config.get("history", [])
    if len(history) < 2:
        return {"pass": True, "reason": "Not enough history to evaluate"}

    recent = [h["score"] for h in history[-3:]]
    best = config.get("best_score", 0)
    target = config.get("target_score")

    if target and best >= target:
        return {"pass": False, "reason": f"Target reached: {best:.3f} >= {target}"}

    if len(recent) >= 3:
        score_range = max(recent) - min(recent)
        if score_range < threshold:
            return {
                "pass": False,
                "reason": f"Plateau detected: last 3 scores within {score_range:.4f} (threshold: {threshold})",
                "suggest": "architect",
            }

    return {"pass": True, "reason": f"Score delta exists: range={max(recent)-min(recent):.4f}"}


def cost_gate(config, budget_tokens=None):
    """Estimate cost of next iteration and check against budget."""
    history = config.get("history", [])
    iterations = config.get("iterations", 0)
    estimated_cost = config.get("iteration_costs", {})

    if not estimated_cost and iterations == 0:
        return {"pass": True, "reason": "First iteration, no cost data yet"}

    total_spent = sum(estimated_cost.get("per_iteration", [0]))
    budget = budget_tokens or estimated_cost.get("budget_tokens")

    if not budget:
        return {"pass": True, "reason": "No budget configured"}

    avg_cost = total_spent / max(iterations, 1)
    remaining = budget - total_spent

    if remaining < avg_cost * 0.5:
        return {
            "pass": False,
            "reason": f"Budget nearly exhausted: {remaining:,} tokens remaining, avg iteration costs {avg_cost:,.0f}",
        }

    return {"pass": True, "reason": f"Budget OK: {remaining:,} tokens remaining"}


def convergence_gate(config, min_improvement=0.005, lookback=5):
    """Detect statistical convergence using diminishing returns."""
    history = config.get("history", [])
    if len(history) < 3:
        return {"pass": True, "reason": "Not enough iterations for convergence analysis"}

    recent = history[-lookback:] if len(history) >= lookback else history
    deltas = []
    for i in range(1, len(recent)):
        deltas.append(recent[i]["score"] - recent[i - 1]["score"])

    if not deltas:
        return {"pass": True, "reason": "No deltas to analyze"}

    avg_delta = sum(deltas) / len(deltas)
    positive_deltas = [d for d in deltas if d > 0]
    improvement_rate = len(positive_deltas) / len(deltas)

    if avg_delta < min_improvement and improvement_rate < 0.4:
        return {
            "pass": False,
            "reason": f"Converged: avg delta={avg_delta:.4f}, improvement rate={improvement_rate:.0%}",
            "suggest": "architect" if improvement_rate < 0.2 else "continue_cautious",
        }

    return {
        "pass": True,
        "reason": f"Still improving: avg delta={avg_delta:.4f}, improvement rate={improvement_rate:.0%}",
    }


def main():
    parser = argparse.ArgumentParser(description="Three-gate iteration trigger")
    parser.add_argument("--config", default=".evolver.json", help="Config path")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--score-threshold", type=float, default=0.02, help="Score plateau threshold")
    parser.add_argument("--budget-tokens", type=int, default=None, help="Token budget override")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    gates = {
        "score": score_gate(config, args.score_threshold),
        "cost": cost_gate(config, args.budget_tokens),
        "convergence": convergence_gate(config),
    }

    all_pass = all(g["pass"] for g in gates.values())
    suggestions = [g.get("suggest") for g in gates.values() if g.get("suggest")]

    result = {
        "proceed": all_pass,
        "gates": gates,
        "suggestions": suggestions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    output = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    print(output)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
