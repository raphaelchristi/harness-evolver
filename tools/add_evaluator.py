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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import write_config_atomic


CODE_EVALUATOR_TEMPLATES = {
    "no_fabricated_references": {
        "description": "Check output doesn't contain fabricated citation patterns",
        "check": "not any(p in output for p in ['http://fake', 'doi.org/10.xxxx', 'ISBN 000'])",
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
    "no_empty_filler": {
        "description": "Check output isn't padded with filler phrases to appear longer",
        "check": "output.count('In conclusion') + output.count('As mentioned') + output.count('It is important to note') < 3",
    },
}


def add_evaluator(config_path, evaluator_name, eval_type, pattern=None):
    """Add evaluator to config using partial update to avoid race conditions.

    Re-reads the config immediately before writing to minimize the window
    where concurrent updates (e.g., main loop updating best_score) could
    be lost. Only modifies 'evaluators' and 'code_evaluators' fields.
    """
    # First read to check if evaluator already exists
    with open(config_path) as f:
        config = json.load(f)

    if evaluator_name in config.get("evaluators", []):
        print(f"Evaluator '{evaluator_name}' already exists", file=sys.stderr)
        return False

    # Prepare what we need to add
    new_code_eval = None
    if eval_type == "code" and pattern:
        new_code_eval = {"pattern": pattern, "type": "regex"}
    elif eval_type == "code" and evaluator_name in CODE_EVALUATOR_TEMPLATES:
        new_code_eval = CODE_EVALUATOR_TEMPLATES[evaluator_name]

    # Re-read config right before write to pick up concurrent changes
    with open(config_path) as f:
        config = json.load(f)

    evaluators = config.get("evaluators", [])
    if evaluator_name not in evaluators:
        evaluators.append(evaluator_name)
    config["evaluators"] = evaluators

    if new_code_eval:
        code_evals = config.get("code_evaluators", {})
        code_evals[evaluator_name] = new_code_eval
        config["code_evaluators"] = code_evals

    write_config_atomic(config_path, config)

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
        # Re-read right before write to avoid race conditions
        with open(args.config) as f:
            config = json.load(f)
        evaluators = config.get("evaluators", [])
        if args.evaluator in evaluators:
            evaluators.remove(args.evaluator)
            config["evaluators"] = evaluators
            code_evals = config.get("code_evaluators", {})
            code_evals.pop(args.evaluator, None)
            config["code_evaluators"] = code_evals
            write_config_atomic(args.config, config)
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
