#!/usr/bin/env python3
"""Add a new evaluator to .evolver.json configuration.

Used by the active critic to programmatically strengthen evaluation
when gaming is detected.

Usage:
    python3 add_evaluator.py --config .evolver.json --evaluator factual_accuracy --type llm
    python3 add_evaluator.py --config .evolver.json --evaluator regex_check --type code --pattern "\\d{4}"
"""

import argparse
import json
import sys


CODE_EVALUATOR_TEMPLATES = {
    "no_hallucination_markers": {
        "description": "Check output doesn't contain hallucination markers",
        "check": "not any(m in output for m in ['I think', 'probably', 'I believe', 'not sure'])",
    },
    "answer_not_question": {
        "description": "Check output doesn't just repeat the input question",
        "check": "output.strip().lower() != input_text.strip().lower()",
    },
    "min_length": {
        "description": "Check output meets minimum length",
        "check": "len(output.strip()) >= 20",
    },
    "no_repetition": {
        "description": "Check output doesn't have excessive repetition",
        "check": "len(set(output.split())) / max(len(output.split()), 1) > 0.3",
    },
}


def add_evaluator(config_path, evaluator_name, eval_type, pattern=None):
    """Add evaluator to config."""
    with open(config_path) as f:
        config = json.load(f)

    evaluators = config.get("evaluators", [])

    if evaluator_name in evaluators:
        print(f"Evaluator '{evaluator_name}' already exists", file=sys.stderr)
        return False

    evaluators.append(evaluator_name)
    config["evaluators"] = evaluators

    if eval_type == "code" and pattern:
        code_evals = config.get("code_evaluators", {})
        code_evals[evaluator_name] = {"pattern": pattern, "type": "regex"}
        config["code_evaluators"] = code_evals
    elif eval_type == "code" and evaluator_name in CODE_EVALUATOR_TEMPLATES:
        code_evals = config.get("code_evaluators", {})
        code_evals[evaluator_name] = CODE_EVALUATOR_TEMPLATES[evaluator_name]
        config["code_evaluators"] = code_evals

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return True


def main():
    parser = argparse.ArgumentParser(description="Add evaluator to .evolver.json")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--evaluator", required=True, help="Evaluator name")
    parser.add_argument("--type", choices=["llm", "code"], default="llm", help="Evaluator type")
    parser.add_argument("--pattern", default=None, help="Regex pattern for code evaluators")
    parser.add_argument("--remove", action="store_true", help="Remove evaluator instead of adding")
    args = parser.parse_args()

    if args.remove:
        with open(args.config) as f:
            config = json.load(f)
        evaluators = config.get("evaluators", [])
        if args.evaluator in evaluators:
            evaluators.remove(args.evaluator)
            config["evaluators"] = evaluators
            with open(args.config, "w") as f:
                json.dump(config, f, indent=2)
            print(f"Removed evaluator: {args.evaluator}")
        else:
            print(f"Evaluator '{args.evaluator}' not found", file=sys.stderr)
        return

    added = add_evaluator(args.config, args.evaluator, args.type, args.pattern)
    if added:
        print(json.dumps({
            "added": args.evaluator,
            "type": args.type,
            "evaluators": json.load(open(args.config))["evaluators"],
        }, indent=2))


if __name__ == "__main__":
    main()
