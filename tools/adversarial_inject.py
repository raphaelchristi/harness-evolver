#!/usr/bin/env python3
"""Inject adversarial examples into LangSmith dataset.

Detects potential memorization by checking if agent outputs are suspiciously
similar to reference outputs, then generates adversarial variations to test
generalization.

Usage:
    python3 adversarial_inject.py \
        --config .evolver.json \
        --experiment v003a \
        --output adversarial_report.json
"""

import argparse
import json
import os
import platform
import sys
import random


def ensure_langsmith_api_key():
    """Load LANGSMITH_API_KEY from credentials file or .env if not in env."""
    if os.environ.get("LANGSMITH_API_KEY"):
        return True
    if platform.system() == "Darwin":
        creds_path = os.path.expanduser("~/Library/Application Support/langsmith-cli/credentials")
    else:
        creds_path = os.path.expanduser("~/.config/langsmith-cli/credentials")
    if os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    if os.path.exists(".env"):
        try:
            with open(".env") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY=") and not line.startswith("#"):
                        key = line.split("=", 1)[1].strip().strip("'\"")
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    return False


def detect_memorization(client, experiment_name, dataset_name):
    """Check if agent outputs are suspiciously similar to reference outputs."""
    suspicious = []
    try:
        runs = list(client.list_runs(project_name=experiment_name, is_root=True, limit=100))
        examples = {str(e.id): e for e in client.list_examples(dataset_name=dataset_name, limit=500)}

        for run in runs:
            if not run.reference_example_id:
                continue
            example = examples.get(str(run.reference_example_id))
            if not example or not example.outputs:
                continue

            run_output = str(run.outputs or "").lower().strip()
            ref_output = str(example.outputs).lower().strip()

            if not run_output or not ref_output:
                continue

            if run_output == ref_output:
                suspicious.append({
                    "example_id": str(run.reference_example_id),
                    "match_type": "exact",
                    "input": str(run.inputs)[:200],
                })
            elif len(run_output) > 50 and ref_output in run_output:
                suspicious.append({
                    "example_id": str(run.reference_example_id),
                    "match_type": "contains_reference",
                    "input": str(run.inputs)[:200],
                })

    except Exception as e:
        print(f"Error checking memorization: {e}", file=sys.stderr)

    return suspicious


def generate_adversarial_inputs(client, dataset_name, num_inputs=5):
    """Generate adversarial variations of existing examples.

    Creates multiple variation types to test generalization:
    - negation: inverts the question to test if the agent distinguishes
    - constraint: adds a constraint that changes the expected answer
    - ambiguous: makes the input ambiguous to test robustness
    - partial: provides incomplete input to test graceful handling
    """
    examples = list(client.list_examples(dataset_name=dataset_name, limit=100))
    if not examples:
        return []

    adversarial = []
    sampled = random.sample(examples, min(num_inputs, len(examples)))

    variation_types = [
        ("negation", "What is NOT the case: {input}"),
        ("constraint", "{input} Answer in exactly one sentence."),
        ("ambiguous", "Someone asked something like: {input}"),
        ("partial", "{partial_input}"),
    ]

    for example in sampled:
        input_data = example.inputs or {}
        input_text = str(input_data.get("input", input_data))

        # Pick a variation type (rotate through them)
        idx = sampled.index(example) % len(variation_types)
        vtype, template = variation_types[idx]

        if vtype == "partial":
            # Use first half of the input
            words = input_text.split()
            partial = " ".join(words[:max(len(words) // 2, 3)])
            varied_input = template.format(partial_input=partial)
        else:
            varied_input = template.format(input=input_text)

        adversarial.append({
            "inputs": {"input": varied_input},
            "metadata": {
                "source": "adversarial",
                "original_example_id": str(example.id),
                "variation_type": vtype,
            },
        })

    return adversarial


def inject_adversarial(client, dataset_id, adversarial_inputs, config=None):
    """Add adversarial examples to dataset."""
    config = config or {}
    added = 0
    for adv in adversarial_inputs:
        try:
            split = "train" if random.random() < 0.7 else "held_out"
            metadata = dict(adv["metadata"])
            metadata["added_at_iteration"] = config.get("iterations", 0)
            client.create_example(
                inputs=adv["inputs"],
                dataset_id=dataset_id,
                metadata=metadata,
                split=split,
            )
            added += 1
        except Exception as e:
            print(f"Failed to inject: {e}", file=sys.stderr)
    return added


def main():
    parser = argparse.ArgumentParser(description="Adversarial injection for evaluators")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--experiment", required=True, help="Experiment to check for memorization")
    parser.add_argument("--output", default=None, help="Output report path")
    parser.add_argument("--inject", action="store_true", help="Actually inject adversarial examples")
    parser.add_argument("--num-adversarial", type=int, default=5, help="Number of adversarial examples")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    ensure_langsmith_api_key()
    from langsmith import Client
    client = Client()

    suspicious = detect_memorization(client, args.experiment, config["dataset"])
    adversarial = generate_adversarial_inputs(client, config["dataset"], args.num_adversarial)

    injected = 0
    if args.inject and adversarial:
        injected = inject_adversarial(client, config["dataset_id"], adversarial, config=config)

    result = {
        "memorization_suspects": len(suspicious),
        "suspicious_examples": suspicious,
        "adversarial_generated": len(adversarial),
        "adversarial_injected": injected,
    }

    output = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    print(output)

    if suspicious:
        print(f"\nWARNING: {len(suspicious)} examples show potential memorization!", file=sys.stderr)


if __name__ == "__main__":
    main()
