#!/usr/bin/env python3
"""LangSmith Setup for Harness Evolver v3.

Configures the LangSmith environment for evolution:
  - Creates/connects to a LangSmith project
  - Creates a dataset from test inputs, production traces, or generated data
  - Configures evaluators based on optimization goals
  - Runs baseline evaluation
  - Writes .evolver.json config

Usage:
    python3 setup.py \
        --project-name my-agent \
        --entry-point "python main.py" \
        --framework langgraph \
        --goals accuracy,latency \
        [--dataset-from-file inputs.json] \
        [--dataset-from-langsmith production-project] \
        [--production-project my-prod-project] \
        [--evaluators correctness,conciseness]

Requires: pip install langsmith openevals
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


def check_dependencies():
    """Verify langsmith and openevals are installed."""
    missing = []
    try:
        import langsmith  # noqa: F401
    except ImportError:
        missing.append("langsmith")
    try:
        import openevals  # noqa: F401
    except ImportError:
        missing.append("openevals")
    return missing


def create_dataset_from_file(client, dataset_name, file_path):
    """Create a LangSmith dataset from a JSON file of inputs."""
    with open(file_path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = data.get("examples", data.get("tasks", [data]))

    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description=f"Evaluation dataset created from {os.path.basename(file_path)}",
    )

    examples = []
    for item in data:
        if isinstance(item, str):
            examples.append({"inputs": {"input": item}})
        elif isinstance(item, dict):
            # Support both {"input": "..."} and {"inputs": {"question": "..."}} formats
            if "inputs" in item:
                ex = {"inputs": item["inputs"]}
            elif "input" in item:
                ex = {"inputs": {"input": item["input"]}}
            elif "question" in item:
                ex = {"inputs": {"question": item["question"]}}
            else:
                ex = {"inputs": item}

            # Include expected outputs if present
            if "outputs" in item:
                ex["outputs"] = item["outputs"]
            elif "expected" in item:
                ex["outputs"] = {"expected": item["expected"]}

            # Include metadata
            if "metadata" in item:
                ex["metadata"] = item["metadata"]

            examples.append(ex)

    if examples:
        client.create_examples(dataset_id=dataset.id, examples=examples)

    return dataset, len(examples)


def create_dataset_from_langsmith(client, dataset_name, source_project, limit=100):
    """Create a dataset from existing LangSmith production traces."""
    runs = list(client.list_runs(
        project_name=source_project,
        is_root=True,
        limit=limit,
    ))

    if not runs:
        return None, 0

    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description=f"Evaluation dataset from production traces ({source_project})",
    )

    examples = []
    for run in runs:
        if run.inputs:
            ex = {"inputs": run.inputs}
            if run.outputs:
                ex["outputs"] = run.outputs
            examples.append(ex)

    if examples:
        client.create_examples(dataset_id=dataset.id, examples=examples)

    return dataset, len(examples)


def create_empty_dataset(client, dataset_name):
    """Create an empty dataset (to be populated by testgen agent)."""
    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description="Evaluation dataset (pending test generation)",
    )
    return dataset


def get_evaluators(goals, evaluator_names=None):
    """Build evaluator list based on optimization goals."""
    from openevals.llm import create_llm_as_judge
    from openevals.prompts import CORRECTNESS_PROMPT, CONCISENESS_PROMPT

    evaluators = []
    evaluator_keys = []

    # Map goals to evaluators
    goal_map = {
        "accuracy": ("correctness", CORRECTNESS_PROMPT),
        "conciseness": ("conciseness", CONCISENESS_PROMPT),
    }

    if evaluator_names:
        names = [n.strip() for n in evaluator_names.split(",")]
    else:
        names = []
        for goal in goals:
            if goal in goal_map:
                names.append(goal_map[goal][0])
        if not names:
            names = ["correctness"]  # default

    for name in names:
        if name in ("correctness", "accuracy"):
            evaluators.append(create_llm_as_judge(
                prompt=CORRECTNESS_PROMPT,
                feedback_key="correctness",
                model="openai:gpt-4.1-mini",
            ))
            evaluator_keys.append("correctness")
        elif name in ("conciseness", "brevity"):
            evaluators.append(create_llm_as_judge(
                prompt=CONCISENESS_PROMPT,
                feedback_key="conciseness",
                model="openai:gpt-4.1-mini",
            ))
            evaluator_keys.append("conciseness")

    # Code-based evaluators for latency/tokens
    if "latency" in goals:
        def latency_eval(inputs, outputs, **kwargs):
            # Latency is captured in traces, not scored here
            return {"key": "has_output", "score": 1.0 if outputs else 0.0}
        evaluators.append(latency_eval)
        evaluator_keys.append("latency")

    if "token_efficiency" in goals:
        def token_eval(inputs, outputs, **kwargs):
            output_text = str(outputs.get("output", outputs.get("answer", "")))
            # Penalize very long outputs (>2000 chars)
            score = min(1.0, 2000 / max(len(output_text), 1))
            return {"key": "token_efficiency", "score": score}
        evaluators.append(token_eval)
        evaluator_keys.append("token_efficiency")

    return evaluators, evaluator_keys


def make_target(entry_point, cwd=None):
    """Create a target function that runs the user's agent."""
    def target(inputs):
        input_json = json.dumps(inputs)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(input_json)
            input_path = f.name

        output_path = input_path + ".out"
        try:
            # Build command — supports {input} placeholder
            cmd = entry_point
            if "{input}" in cmd:
                cmd = cmd.replace("{input}", input_path)
            elif "{input_json}" in cmd:
                cmd = cmd.replace("{input_json}", input_json)
            else:
                cmd = f"{cmd} --input {input_path} --output {output_path}"

            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=120, cwd=cwd,
            )

            # Try to read output file
            if os.path.exists(output_path):
                with open(output_path) as f:
                    return json.load(f)

            # Fallback: parse stdout as JSON
            if result.stdout.strip():
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"output": result.stdout.strip()}

            return {"output": "", "error": result.stderr.strip() if result.returncode != 0 else None}

        except subprocess.TimeoutExpired:
            return {"output": "", "error": "TIMEOUT after 120s"}
        except Exception as e:
            return {"output": "", "error": str(e)}
        finally:
            for p in [input_path, output_path]:
                if os.path.exists(p):
                    os.remove(p)

    return target


def run_baseline(client, dataset_name, entry_point, evaluators):
    """Run baseline evaluation and return experiment name + score."""
    target = make_target(entry_point)

    results = client.evaluate(
        target,
        data=dataset_name,
        evaluators=evaluators,
        experiment_prefix="baseline",
        max_concurrency=1,
    )

    experiment_name = results.experiment_name
    # Read aggregate metrics
    try:
        project = client.read_project(project_name=experiment_name, include_stats=True)
        stats = project.model_dump() if hasattr(project, "model_dump") else {}
    except Exception:
        stats = {}

    # Calculate mean score from results
    scores = []
    for result in results:
        if result.evaluation_results and result.evaluation_results.get("results"):
            for er in result.evaluation_results["results"]:
                if er.get("score") is not None:
                    scores.append(er["score"])

    mean_score = sum(scores) / len(scores) if scores else 0.0

    return experiment_name, mean_score


def main():
    parser = argparse.ArgumentParser(description="Setup LangSmith for Harness Evolver v3")
    parser.add_argument("--project-name", required=True, help="Name for the evolver project")
    parser.add_argument("--entry-point", required=True, help="Command to run the agent")
    parser.add_argument("--framework", default="unknown", help="Detected framework")
    parser.add_argument("--goals", default="accuracy", help="Comma-separated optimization goals")
    parser.add_argument("--dataset-from-file", default=None, help="Create dataset from JSON file")
    parser.add_argument("--dataset-from-langsmith", default=None, help="Create dataset from LangSmith project")
    parser.add_argument("--production-project", default=None, help="Production LangSmith project")
    parser.add_argument("--evaluators", default=None, help="Comma-separated evaluator names")
    parser.add_argument("--skip-baseline", action="store_true", help="Skip baseline evaluation")
    parser.add_argument("--output", default=".evolver.json", help="Output config path")
    args = parser.parse_args()

    # Check dependencies
    missing = check_dependencies()
    if missing:
        print(f"Missing packages: {', '.join(missing)}", file=sys.stderr)
        print(f"Install with: pip install {' '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    from langsmith import Client
    client = Client()

    # Verify connection
    try:
        client.list_datasets(limit=1)
        print("LangSmith connection verified.")
    except Exception as e:
        print(f"Failed to connect to LangSmith: {e}", file=sys.stderr)
        print("Check LANGSMITH_API_KEY is set correctly.", file=sys.stderr)
        sys.exit(1)

    project_name = f"evolver-{args.project_name}"
    dataset_name = f"{args.project_name}-eval-v1"
    goals = [g.strip() for g in args.goals.split(",")]

    # Create dataset
    print(f"Creating dataset '{dataset_name}'...")
    if args.dataset_from_file:
        dataset, count = create_dataset_from_file(client, dataset_name, args.dataset_from_file)
        print(f"  Created from file: {count} examples")
    elif args.dataset_from_langsmith:
        dataset, count = create_dataset_from_langsmith(
            client, dataset_name, args.dataset_from_langsmith,
        )
        if not dataset:
            print("  No traces found in source project. Creating empty dataset.")
            dataset = create_empty_dataset(client, dataset_name)
            count = 0
        else:
            print(f"  Created from LangSmith traces: {count} examples")
    else:
        dataset = create_empty_dataset(client, dataset_name)
        count = 0
        print("  Created empty dataset (testgen will populate)")

    # Configure evaluators
    print(f"Configuring evaluators for goals: {goals}")
    evaluators, evaluator_keys = get_evaluators(goals, args.evaluators)
    print(f"  Active evaluators: {evaluator_keys}")

    # Run baseline
    baseline_experiment = None
    baseline_score = 0.0
    if not args.skip_baseline and count > 0:
        print(f"Running baseline evaluation ({count} examples)...")
        try:
            baseline_experiment, baseline_score = run_baseline(
                client, dataset_name, args.entry_point, evaluators,
            )
            print(f"  Baseline score: {baseline_score:.3f}")
            print(f"  Experiment: {baseline_experiment}")
        except Exception as e:
            print(f"  Baseline evaluation failed: {e}", file=sys.stderr)
            print("  Continuing with score 0.0")
    elif count == 0:
        print("Skipping baseline (no examples in dataset yet)")
    else:
        print("Skipping baseline (--skip-baseline)")

    # Write config
    config = {
        "version": "3.0.0",
        "project": project_name,
        "dataset": dataset_name,
        "dataset_id": str(dataset.id) if dataset else None,
        "entry_point": args.entry_point,
        "evaluators": evaluator_keys,
        "optimization_goals": goals,
        "production_project": args.production_project,
        "baseline_experiment": baseline_experiment,
        "best_experiment": baseline_experiment,
        "best_score": baseline_score,
        "iterations": 0,
        "framework": args.framework,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "history": [{
            "version": "baseline",
            "experiment": baseline_experiment,
            "score": baseline_score,
        }] if baseline_experiment else [],
    }

    with open(args.output, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nSetup complete. Config saved to {args.output}")
    print(f"  Project: {project_name}")
    print(f"  Dataset: {dataset_name} ({count} examples)")
    print(f"  Evaluators: {evaluator_keys}")
    if baseline_experiment:
        print(f"  Baseline: {baseline_score:.3f}")
    print(f"\nNext: run /evolver:evolve")


if __name__ == "__main__":
    main()
