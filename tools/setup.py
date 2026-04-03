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

Requires: pip install langsmith
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common
from _common import ensure_langsmith_api_key


def check_dependencies():
    """Verify langsmith is installed."""
    missing = []
    try:
        import langsmith  # noqa: F401
    except ImportError:
        missing.append("langsmith")
    return missing


def assign_splits(client, dataset_id, train_pct=70):
    """Assign train/held_out splits to all examples in a dataset."""
    import random
    examples = list(client.list_examples(dataset_id=dataset_id))
    random.shuffle(examples)
    split_point = int(len(examples) * train_pct / 100)
    for ex in examples[:split_point]:
        client.update_example(ex.id, split="train")
    for ex in examples[split_point:]:
        client.update_example(ex.id, split="held_out")
    return len(examples[:split_point]), len(examples[split_point:])


def resolve_dataset_name(client, base_name):
    """Find an available dataset name by auto-incrementing the version suffix.

    Tries base_name-eval-v1, v2, v3... until an unused name is found.
    Returns (resolved_name, version_number).
    """
    existing = set()
    try:
        for ds in client.list_datasets():
            existing.add(ds.name)
    except Exception:
        pass

    for v in range(1, 100):
        candidate = f"{base_name}-eval-v{v}"
        if candidate not in existing:
            return candidate, v

    # Fallback: timestamp-based
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{base_name}-eval-{ts}", 0


def create_dataset_with_retry(client, dataset_name, description, max_retries=3):
    """Create dataset with retry for transient errors."""
    import time
    for attempt in range(max_retries):
        try:
            return client.create_dataset(dataset_name=dataset_name, description=description)
        except Exception as e:
            if attempt + 1 < max_retries and ("403" in str(e) or "500" in str(e)):
                wait = 2 ** attempt + 0.5
                print(f"  Transient error creating dataset (attempt {attempt + 1}/{max_retries}), retrying in {wait:.0f}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def create_dataset_from_file(client, dataset_name, file_path):
    """Create a LangSmith dataset from a JSON file of inputs."""
    with open(file_path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = data.get("examples", data.get("tasks", [data]))

    dataset = create_dataset_with_retry(
        client, dataset_name,
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

            # Include rubric/expected behavior in metadata
            if "expected_behavior" in item:
                if "metadata" not in ex:
                    ex["metadata"] = {}
                ex["metadata"]["expected_behavior"] = item["expected_behavior"]

            # Include difficulty and category in metadata
            for field in ("difficulty", "category"):
                if field in item:
                    if "metadata" not in ex:
                        ex["metadata"] = {}
                    ex["metadata"][field] = item[field]

            # Include metadata
            if "metadata" in item and "metadata" not in ex:
                ex["metadata"] = item["metadata"]
            elif "metadata" in item:
                ex["metadata"].update(item["metadata"])

            if "metadata" not in ex:
                ex["metadata"] = {}
            ex["metadata"].setdefault("source", "file")
            ex["metadata"].setdefault("added_at_iteration", 0)

            examples.append(ex)

    if examples:
        client.create_examples(dataset_id=dataset.id, examples=examples)
        train_n, held_n = assign_splits(client, dataset.id)
        print(f"Assigned splits: {train_n} train, {held_n} held_out", file=sys.stderr)

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

    dataset = create_dataset_with_retry(
        client, dataset_name,
        description=f"Evaluation dataset from production traces ({source_project})",
    )

    examples = []
    for run in runs:
        if run.inputs:
            ex = {"inputs": run.inputs}
            if run.outputs:
                ex["outputs"] = run.outputs
            ex["metadata"] = {"source": "production", "added_at_iteration": 0}
            examples.append(ex)

    if examples:
        client.create_examples(dataset_id=dataset.id, examples=examples)
        train_n, held_n = assign_splits(client, dataset.id)
        print(f"Assigned splits: {train_n} train, {held_n} held_out", file=sys.stderr)

    return dataset, len(examples)


def create_empty_dataset(client, dataset_name):
    """Create an empty dataset (to be populated by testgen agent)."""
    dataset = create_dataset_with_retry(
        client, dataset_name,
        description="Evaluation dataset (pending test generation)",
    )
    return dataset


def get_evaluators(goals, evaluator_names=None):
    """Build evaluator list based on optimization goals.

    Returns only code-based evaluators. LLM-as-judge evaluators
    (correctness, conciseness) are handled post-hoc by the
    harness-evaluator agent via langsmith-cli.
    """
    evaluators = []
    evaluator_keys = []

    # Map goals to evaluator keys (LLM-based are recorded but not instantiated)
    goal_to_key = {
        "accuracy": "correctness",
        "conciseness": "conciseness",
    }

    if evaluator_names:
        names = [n.strip() for n in evaluator_names.split(",")]
    else:
        names = []
        for goal in goals:
            if goal in goal_to_key:
                names.append(goal_to_key[goal])
        if not names:
            names = ["correctness"]  # default

    # Record all evaluator keys (for config) but only instantiate code-based ones
    for name in names:
        if name in ("correctness", "accuracy"):
            evaluator_keys.append("correctness")
            # LLM-as-judge — handled by evaluator agent, not here
        elif name in ("conciseness", "brevity"):
            evaluator_keys.append("conciseness")
            # LLM-as-judge — handled by evaluator agent, not here

    # Always include has_output
    def has_output_eval(inputs, outputs, **kwargs):
        has = bool(outputs and outputs.get("output", outputs.get("answer", "")))
        return {"key": "has_output", "score": 1.0 if has else 0.0}
    evaluators.append(has_output_eval)

    # Code-based evaluators for latency/tokens
    if "latency" in goals:
        evaluator_keys.append("latency")

    if "token_efficiency" in goals:
        def token_eval(inputs, outputs, **kwargs):
            output_text = str(outputs.get("output", outputs.get("answer", "")))
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
            elif "--input" in cmd or "-i " in cmd:
                cmd = f"{cmd} {input_path}"
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

    # Try to extract scores — this can fail with different SDK versions
    mean_score = 0.0
    try:
        scores = []
        for result in results:
            # Handle both object and dict result formats
            if hasattr(result, 'evaluation_results'):
                eval_results = result.evaluation_results
            elif isinstance(result, dict):
                eval_results = result.get("evaluation_results", {})
            else:
                continue

            results_list = eval_results.get("results", []) if isinstance(eval_results, dict) else []
            for er in results_list:
                score = er.get("score") if isinstance(er, dict) else getattr(er, "score", None)
                if score is not None:
                    scores.append(score)

        mean_score = sum(scores) / len(scores) if scores else 0.0
    except Exception as e:
        print(f"  Warning: Could not extract baseline scores: {e}", file=sys.stderr)
        print(f"  Baseline experiment '{experiment_name}' was created — scores will be computed during /evolve", file=sys.stderr)

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
    parser.add_argument("--dataset-name", default=None, help="Explicit dataset name (skip auto-versioning)")
    parser.add_argument("--evaluators", default=None, help="Comma-separated evaluator names")
    parser.add_argument("--skip-baseline", action="store_true", help="Skip baseline evaluation")
    parser.add_argument("--mode", choices=["light", "balanced", "heavy"], default="balanced", help="Evolution mode")
    parser.add_argument("--output", default=".evolver.json", help="Output config path")
    args = parser.parse_args()

    # Check dependencies
    missing = check_dependencies()
    if missing:
        print(f"Missing packages: {', '.join(missing)}", file=sys.stderr)
        print(f"Install with: pip install {' '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    # Load API key from credentials file if not in env
    if not ensure_langsmith_api_key():
        print("LANGSMITH_API_KEY not found in environment, credentials file, or .env", file=sys.stderr)
        print("Set it with: export LANGSMITH_API_KEY=lsv2_pt_...", file=sys.stderr)
        sys.exit(1)

    from langsmith import Client
    client = Client()

    # Verify connection
    try:
        client.list_datasets(limit=1)
        print(f"LangSmith connection verified (key from {_common.key_source}).")
    except Exception as e:
        if _common.key_source in ("credentials file", ".env file"):
            print(f"ERROR: API key loaded from {_common.key_source} is invalid or lacks permissions.", file=sys.stderr)
            print(f"The key was loaded from the {_common.key_source} but LangSmith rejected it.", file=sys.stderr)
            print(f"Fix: export LANGSMITH_API_KEY=lsv2_pt_... (with a valid key)", file=sys.stderr)
        else:
            print(f"Failed to connect to LangSmith: {e}", file=sys.stderr)
        sys.exit(1)

    # Verify write permissions
    try:
        test_ds = client.create_dataset(
            dataset_name="_evolver-permission-check",
            description="Temporary — verifying write permissions",
        )
        client.delete_dataset(dataset_id=test_ds.id)
        print("Write permissions verified.")
    except Exception as e:
        print(f"ERROR: API key can read but cannot write to LangSmith.", file=sys.stderr)
        print(f"The key needs 'Editor' role or higher to create datasets.", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)

    project_name = f"evolver-{args.project_name}"
    goals = [g.strip() for g in args.goals.split(",")]

    # Resolve dataset name (explicit or auto-versioned)
    if args.dataset_name:
        dataset_name = args.dataset_name
        print(f"Using explicit dataset name: '{dataset_name}'")
    else:
        dataset_name, version = resolve_dataset_name(client, args.project_name)
        if version > 1:
            print(f"Dataset name auto-versioned to '{dataset_name}' (v1-v{version-1} already exist)")
        else:
            print(f"Dataset: '{dataset_name}'")

    # Create dataset — wrapped in try/except to clean up orphaned datasets on failure
    dataset = None
    try:
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
        llm_evaluators = [k for k in evaluator_keys if k in ("correctness", "conciseness")]
        if llm_evaluators:
            print(f"  LLM evaluators (agent-based): {llm_evaluators}")

        # Run baseline (code-based evaluators only; LLM scoring done by evaluator agent)
        baseline_experiment = None
        baseline_score = 0.0
        if not args.skip_baseline and count > 0:
            print(f"Running baseline target ({count} examples)...")
            try:
                baseline_experiment, baseline_score = run_baseline(
                    client, dataset_name, args.entry_point, evaluators,
                )
                print(f"  Baseline has_output score: {baseline_score:.3f}")
                print(f"  Experiment: {baseline_experiment}")
                if llm_evaluators:
                    print(f"  Note: LLM scoring pending — evaluator agent will run during /harness:evolve")
            except Exception as e:
                print(f"  Baseline evaluation failed: {e}", file=sys.stderr)
                print("  Continuing with score 0.0")
        elif count == 0:
            print("Skipping baseline (no examples in dataset yet)")
        else:
            print("Skipping baseline (--skip-baseline)")

        # Warn if no project venv found and entry_point uses evolver venv
        entry_point = args.entry_point
        evolver_venv = os.path.expanduser("~/.evolver/venv")
        has_project_venv = any(os.path.isdir(os.path.join(".", d)) for d in [".venv", "venv"])
        if not has_project_venv:
            print("\n  WARNING: No Python venv found in project (.venv/ or venv/).", file=sys.stderr)
            print("  Create one first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt", file=sys.stderr)
        if evolver_venv in entry_point:
            print(f"\n  WARNING: Entry point uses evolver venv ({evolver_venv}).", file=sys.stderr)
            print("  The evolver venv is for tools only, not your agent.", file=sys.stderr)
            print("  Use your project's .venv/bin/python instead.", file=sys.stderr)

        # Resolve Python interpreter in entry_point to absolute path
        # This ensures the entry point works in worktrees where venvs don't exist
        parts = entry_point.split()
        if parts:
            python_path = parts[0]
            # Resolve relative Python paths (e.g., ../.venv/bin/python, .venv/bin/python)
            if "/" in python_path and not os.path.isabs(python_path):
                abs_python = os.path.abspath(python_path)
                if os.path.exists(abs_python):
                    parts[0] = abs_python
                    entry_point = " ".join(parts)
                    print(f"  Resolved Python path: {abs_python}")

        # Compute project_dir relative to git root (for worktree path resolution)
        project_dir = ""
        try:
            git_prefix = subprocess.run(
                ["git", "rev-parse", "--show-prefix"],
                capture_output=True, text=True, timeout=5,
            )
            if git_prefix.returncode == 0:
                project_dir = git_prefix.stdout.strip().rstrip("/")
        except Exception:
            pass

        # Write config
        config = {
            "version": "3.0.0",
            "project": project_name,
            "dataset": dataset_name,
            "dataset_id": str(dataset.id) if dataset else None,
            "project_dir": project_dir,
            "entry_point": entry_point,
            "evaluators": evaluator_keys,
            "evaluator_weights": {"has_output": 0},  # has_output tracked but excluded from combined (inflates scores)
            "mode": args.mode,
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

        # Atomic write to prevent corruption
        tmp = args.output + ".tmp"
        with open(tmp, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
        os.replace(tmp, args.output)

        print(f"\nSetup complete. Config saved to {args.output}")
        print(f"  Project: {project_name}")
        print(f"  Dataset: {dataset_name} ({count} examples)")
        print(f"  Evaluators: {evaluator_keys}")
        if baseline_experiment:
            print(f"  Baseline: {baseline_score:.3f}")
        print(f"\nNext: run /harness:evolve")

    except Exception as e:
        # Cleanup orphaned dataset if setup fails after dataset creation
        if dataset:
            print(f"Setup failed: {e}", file=sys.stderr)
            print(f"Cleaning up orphaned dataset '{dataset_name}'...", file=sys.stderr)
            try:
                client.delete_dataset(dataset_id=dataset.id)
                print("  Dataset deleted.", file=sys.stderr)
            except Exception:
                print(f"  WARNING: Could not delete dataset. Clean up manually in LangSmith.", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
