#!/usr/bin/env python3
"""Run LangSmith evaluation for a candidate in a worktree.

Wraps client.evaluate() — runs the user's agent against the dataset
with configured evaluators, from within a specific directory (worktree).

Usage:
    python3 run_eval.py \
        --config .evolver.json \
        --worktree-path /tmp/worktree-abc \
        --experiment-prefix v001a \
        [--timeout 120]

Requires: pip install langsmith openevals
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile


def ensure_langsmith_api_key():
    """Load LANGSMITH_API_KEY from credentials file if not in env."""
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


def make_target(entry_point, cwd):
    """Create a target function that runs the agent from a specific directory."""
    def target(inputs):
        input_json = json.dumps(inputs)
        input_path = tempfile.mktemp(suffix=".json")
        output_path = input_path + ".out"

        with open(input_path, "w") as f:
            f.write(input_json)

        try:
            cmd = entry_point
            if "{input}" in cmd:
                cmd = cmd.replace("{input}", input_path)
            elif "{input_json}" in cmd:
                cmd = cmd.replace("{input_json}", input_json)
            else:
                cmd = f"{cmd} --input {input_path} --output {output_path}"

            env = os.environ.copy()
            # Ensure traces go to the evolver project
            env["LANGSMITH_TRACING"] = "true"

            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=int(os.environ.get("EVAL_TASK_TIMEOUT", "120")),
                cwd=cwd, env=env,
            )

            # Read output file if it exists
            if os.path.exists(output_path):
                with open(output_path) as f:
                    try:
                        return json.load(f)
                    except json.JSONDecodeError:
                        pass

            # Fallback: parse stdout
            if result.stdout.strip():
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"output": result.stdout.strip()}

            # Accept segfault (139) if output was produced
            if result.returncode != 0:
                return {"output": "", "error": result.stderr.strip()[:500]}

            return {"output": ""}

        except subprocess.TimeoutExpired:
            return {"output": "", "error": f"TIMEOUT after {os.environ.get('EVAL_TASK_TIMEOUT', '120')}s"}
        except Exception as e:
            return {"output": "", "error": str(e)}
        finally:
            for p in [input_path, output_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    return target


def load_evaluators(evaluator_keys):
    """Load evaluators by key name."""
    from openevals.llm import create_llm_as_judge
    from openevals.prompts import CORRECTNESS_PROMPT, CONCISENESS_PROMPT

    evaluators = []
    for key in evaluator_keys:
        if key == "correctness":
            evaluators.append(create_llm_as_judge(
                prompt=CORRECTNESS_PROMPT,
                feedback_key="correctness",
                model="openai:gpt-4.1-mini",
            ))
        elif key == "conciseness":
            evaluators.append(create_llm_as_judge(
                prompt=CONCISENESS_PROMPT,
                feedback_key="conciseness",
                model="openai:gpt-4.1-mini",
            ))
        elif key == "latency":
            def latency_eval(inputs, outputs, **kwargs):
                return {"key": "has_output", "score": 1.0 if outputs else 0.0}
            evaluators.append(latency_eval)
        elif key == "token_efficiency":
            def token_eval(inputs, outputs, **kwargs):
                output_text = str(outputs.get("output", outputs.get("answer", "")))
                score = min(1.0, 2000 / max(len(output_text), 1))
                return {"key": "token_efficiency", "score": score}
            evaluators.append(token_eval)

    return evaluators


def main():
    parser = argparse.ArgumentParser(description="Run LangSmith evaluation for a candidate")
    parser.add_argument("--config", default=".evolver.json", help="Path to .evolver.json")
    parser.add_argument("--worktree-path", required=True, help="Path to the candidate's worktree")
    parser.add_argument("--experiment-prefix", required=True, help="Experiment name prefix (e.g. v001a)")
    parser.add_argument("--timeout", type=int, default=120, help="Per-task timeout in seconds")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    os.environ["EVAL_TASK_TIMEOUT"] = str(args.timeout)
    ensure_langsmith_api_key()

    from langsmith import Client
    client = Client()

    target = make_target(config["entry_point"], args.worktree_path)
    evaluators = load_evaluators(config["evaluators"])

    print(f"Running evaluation: {args.experiment_prefix}")
    print(f"  Dataset: {config['dataset']}")
    print(f"  Worktree: {args.worktree_path}")
    print(f"  Evaluators: {config['evaluators']}")

    try:
        results = client.evaluate(
            target,
            data=config["dataset"],
            evaluators=evaluators,
            experiment_prefix=args.experiment_prefix,
            max_concurrency=1,
        )

        experiment_name = results.experiment_name

        # Calculate mean score
        scores = []
        per_example = {}
        for result in results:
            example_scores = []
            if result.evaluation_results and result.evaluation_results.get("results"):
                for er in result.evaluation_results["results"]:
                    if er.get("score") is not None:
                        example_scores.append(er["score"])
                        scores.append(er["score"])

            example_id = str(result.example.id) if result.example else "unknown"
            per_example[example_id] = {
                "score": sum(example_scores) / len(example_scores) if example_scores else 0.0,
                "num_evaluators": len(example_scores),
            }

        mean_score = sum(scores) / len(scores) if scores else 0.0

        output = {
            "experiment": experiment_name,
            "prefix": args.experiment_prefix,
            "combined_score": mean_score,
            "num_examples": len(per_example),
            "num_scores": len(scores),
            "per_example": per_example,
        }

        print(json.dumps(output))
        print(f"\nEvaluation complete: {mean_score:.3f} ({len(per_example)} examples)")

    except Exception as e:
        print(f"Evaluation failed: {e}", file=sys.stderr)
        output = {
            "experiment": None,
            "prefix": args.experiment_prefix,
            "combined_score": 0.0,
            "error": str(e),
        }
        print(json.dumps(output))
        sys.exit(1)


if __name__ == "__main__":
    main()
