#!/usr/bin/env python3
"""Run LangSmith evaluation for a candidate in a worktree.

Wraps client.evaluate() — runs the user's agent against the dataset
with code-based evaluators only (has_output, token_efficiency).
LLM-as-judge scoring (correctness, conciseness) is handled post-hoc
by the harness-evaluator agent via langsmith-cli.

Usage:
    python3 run_eval.py \
        --config .evolver.json \
        --worktree-path /tmp/worktree-abc \
        --experiment-prefix v001a \
        [--timeout 120]

Requires: pip install langsmith
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_langsmith_api_key

_RATE_LIMIT_RE = re.compile(
    r"\b429\b|rate[ _-]?limit|resource[_ ]exhausted|quota[_ ]?(exceeded|exhausted)",
    re.IGNORECASE,
)


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

            # {input_text}: extract plain text from inputs dict (for agents expecting --query "text")
            if "{input_text}" in cmd:
                import shlex
                text = ""
                for key in ("input", "question", "query", "prompt", "text", "user_input"):
                    if key in inputs and isinstance(inputs[key], str):
                        text = inputs[key]
                        break
                if not text and inputs:
                    first_val = next(iter(inputs.values()), "")
                    text = str(first_val) if not isinstance(first_val, str) else first_val
                cmd = cmd.replace("{input_text}", shlex.quote(text))
            elif "{input}" in cmd:
                # Placeholder: replace with path to JSON file
                cmd = cmd.replace("{input}", input_path)
            elif "{input_json}" in cmd:
                # Placeholder: replace with inline JSON string
                cmd = cmd.replace("{input_json}", input_json)
            elif "--input" in cmd or "-i " in cmd:
                # Entry point already has --input flag — pass the file path as next arg
                cmd = f"{cmd} {input_path}"
            else:
                # Default: append --input and --output flags
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
                stderr = result.stderr.strip()
                # Capture tail of stderr (traceback/error is at the end, not the beginning)
                error_msg = stderr[-500:] if len(stderr) > 500 else stderr
                return {"output": "", "error": error_msg}

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
    """Load code-based evaluators only.

    LLM-as-judge evaluators (correctness, conciseness) are handled
    post-hoc by the harness-evaluator agent via langsmith-cli.
    """
    evaluators = []

    # Always include has_output — verifies the agent produced something
    def has_output_eval(inputs, outputs, **kwargs):
        has = bool(outputs and outputs.get("output", outputs.get("answer", "")))
        return {"key": "has_output", "score": 1.0 if has else 0.0}
    evaluators.append(has_output_eval)

    for key in evaluator_keys:
        if key == "latency":
            # Latency is captured in traces, just check output exists
            pass  # has_output already covers this
        elif key == "token_efficiency":
            def token_eval(inputs, outputs, **kwargs):
                output_text = str(outputs.get("output", outputs.get("answer", "")))
                score = min(1.0, 2000 / max(len(output_text), 1))
                return {"key": "token_efficiency", "score": score}
            evaluators.append(token_eval)
        # correctness, conciseness — skipped, handled by evaluator agent

    return evaluators


def main():
    parser = argparse.ArgumentParser(description="Run LangSmith evaluation for a candidate")
    parser.add_argument("--config", default=".evolver.json", help="Path to .evolver.json")
    parser.add_argument("--worktree-path", required=True, help="Path to the candidate's worktree")
    parser.add_argument("--experiment-prefix", required=True, help="Experiment name prefix (e.g. v001a)")
    parser.add_argument("--timeout", type=int, default=120, help="Per-task timeout in seconds")
    parser.add_argument("--concurrency", type=int, default=None, help="Max concurrent evaluations (default: from config or 1)")
    parser.add_argument("--no-canary", action="store_true", help="Skip canary preflight check")
    parser.add_argument("--preflight-only", action="store_true", help="Run preflight checks only (API key, config, canary) then exit")
    parser.add_argument("--retry-on-rate-limit", action="store_true",
                        help="If rate-limited, wait 60s and suggest re-run")
    parser.add_argument("--sample", type=int, default=None, help="Evaluate a random sample of N examples instead of all")
    args = parser.parse_args()

    # Auto-copy config files to worktree if missing (untracked files aren't in worktrees)
    config_dir = os.path.dirname(os.path.abspath(args.config))
    worktree = args.worktree_path
    if config_dir != os.path.abspath(worktree):
        for fname in [".evolver.json", ".env"]:
            src = os.path.join(config_dir, fname)
            dst = os.path.join(worktree, fname)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                print(f"  Auto-copied {fname} to worktree", file=sys.stderr)

    with open(args.config) as f:
        config = json.load(f)

    concurrency = args.concurrency or config.get("eval_concurrency", 3)

    os.environ["EVAL_TASK_TIMEOUT"] = str(args.timeout)
    ensure_langsmith_api_key()

    from langsmith import Client
    client = Client()

    # Sample mode: evaluate subset of dataset (used by light mode)
    sampled_examples = None
    if args.sample:
        import random
        all_examples = list(client.list_examples(dataset_name=config["dataset"], limit=500))
        if args.sample < len(all_examples):
            sampled_examples = random.sample(all_examples, args.sample)
            print(f"  Sampling {args.sample}/{len(all_examples)} examples", file=sys.stderr)
        else:
            print(f"  Sample {args.sample} >= dataset size {len(all_examples)}, using all", file=sys.stderr)

    target = make_target(config["entry_point"], args.worktree_path)
    evaluators = load_evaluators(config["evaluators"])

    # Identify which evaluators need the agent (LLM-as-judge)
    llm_evaluators = [k for k in config["evaluators"] if k in ("correctness", "conciseness")]
    code_evaluators = [k for k in config["evaluators"] if k not in ("correctness", "conciseness")]

    # Canary run: verify agent works before burning through full dataset
    if not args.no_canary:
        print("  Canary: running 1 example preflight...", file=sys.stderr)
        try:
            canary_examples = list(client.list_examples(dataset_name=config["dataset"], limit=1))
            if canary_examples:
                canary_result = target(canary_examples[0].inputs)
                # Accept both "output" and "answer" keys (same contract as has_output evaluator)
                # Use `or` not default — handles empty string and None
                canary_output = canary_result.get("output") or canary_result.get("answer") or ""
                canary_error = canary_result.get("error", "")
                # Fail on empty output regardless of error — an agent that exits
                # cleanly with no output is still broken (Codex review finding)
                if not canary_output:
                    reason = canary_error or "agent produced no output (clean exit, no stdout)"
                    print(f"  CANARY FAILED: {reason}", file=sys.stderr)
                    print(f"  Fix the agent before running full evaluation.", file=sys.stderr)
                    output = {
                        "experiment": None,
                        "prefix": args.experiment_prefix,
                        "combined_score": 0.0,
                        "error": f"Canary failed: {canary_error[:200]}",
                    }
                    print(json.dumps(output))
                    sys.exit(2)
                else:
                    print(f"  Canary passed: got output ({len(str(canary_output))} chars)", file=sys.stderr)
        except Exception as e:
            print(f"  Canary check failed: {e} (proceeding anyway)", file=sys.stderr)

    # Preflight-only mode: check everything works, then exit
    if args.preflight_only:
        print(json.dumps({
            "preflight": "pass",
            "config": args.config,
            "dataset": config["dataset"],
            "entry_point": config["entry_point"],
            "evaluators": config["evaluators"],
            "worktree_files_copied": True,
            "api_key_loaded": bool(os.environ.get("LANGSMITH_API_KEY")),
        }, indent=2))
        sys.exit(0)

    print(f"Running evaluation: {args.experiment_prefix}")
    print(f"  Dataset: {config['dataset']}")
    print(f"  Worktree: {args.worktree_path}")
    print(f"  Code evaluators: {['has_output'] + code_evaluators}")
    if concurrency > 1:
        print(f"  Concurrency: {concurrency} parallel evaluations")
    if llm_evaluators:
        print(f"  Pending LLM evaluators (agent): {llm_evaluators}")

    try:
        eval_data = sampled_examples if sampled_examples else config["dataset"]
        results = client.evaluate(
            target,
            data=eval_data,
            evaluators=evaluators,
            experiment_prefix=args.experiment_prefix,
            max_concurrency=concurrency,
        )

        experiment_name = results.experiment_name

        # Calculate mean score + detect rate limits as we iterate
        scores = []
        per_example = {}
        rate_limit_count = 0
        total_processed = 0
        aborted_early = False

        for result in results:
            total_processed += 1
            example_scores = []

            # Handle both dict and object results (SDK version compat)
            if isinstance(result, dict):
                eval_results = result.get("evaluation_results", {})
                if isinstance(eval_results, dict):
                    eval_list = eval_results.get("results", [])
                else:
                    eval_list = getattr(eval_results, "results", []) or []
                example_obj = result.get("example")
                example_id = str(example_obj.get("id", "unknown") if isinstance(example_obj, dict) else getattr(example_obj, "id", "unknown"))
                # Check run outputs for rate-limit signals
                run_obj = result.get("run", {})
                outputs = run_obj.get("outputs", {}) if isinstance(run_obj, dict) else {}
            else:
                eval_results = getattr(result, "evaluation_results", None)
                if isinstance(eval_results, dict):
                    eval_list = eval_results.get("results", [])
                elif eval_results:
                    eval_list = getattr(eval_results, "results", []) or []
                else:
                    eval_list = []
                example_obj = getattr(result, "example", None)
                example_id = str(getattr(example_obj, "id", "unknown") if example_obj else "unknown")
                run_obj = getattr(result, "run", None)
                outputs = getattr(run_obj, "outputs", {}) if run_obj else {}

            # Detect rate-limit in this run's error (never check output — words like "curated" cause false positives)
            if outputs and isinstance(outputs, dict):
                error_text = str(outputs.get("error", ""))
                if _RATE_LIMIT_RE.search(error_text):
                    rate_limit_count += 1

            # Early abort: after 5+ runs, if >50% are rate-limited, stop burning quota
            if total_processed >= 5 and rate_limit_count / total_processed > 0.5:
                print(f"\n  ABORTING: {rate_limit_count}/{total_processed} runs hit rate limits ({rate_limit_count/total_processed:.0%}). Stopping early to save quota.", file=sys.stderr)
                aborted_early = True
                break

            for er in eval_list:
                score_val = er.get("score") if isinstance(er, dict) else getattr(er, "score", None)
                if score_val is not None:
                    example_scores.append(score_val)
                    scores.append(score_val)

            per_example[example_id] = {
                "score": sum(example_scores) / len(example_scores) if example_scores else 0.0,
                "num_evaluators": len(example_scores),
            }

        if aborted_early and args.retry_on_rate_limit:
            import time
            print(f"\n  Rate-limited. Waiting 60s before suggesting re-run...", file=sys.stderr)
            time.sleep(60)
            print(f"  Wait complete. Re-run this command to retry remaining examples.", file=sys.stderr)

        mean_score = sum(scores) / len(scores) if scores else 0.0
        num_examples = len(per_example)
        rate_limited = num_examples > 0 and (rate_limit_count / max(total_processed, 1)) > 0.3

        output = {
            "experiment": experiment_name,
            "prefix": args.experiment_prefix,
            "combined_score": mean_score,
            "num_examples": num_examples,
            "num_scores": len(scores),
            "per_example": per_example,
            "pending_llm_evaluators": llm_evaluators,
            "rate_limited": rate_limited,
            "rate_limit_count": rate_limit_count,
            "aborted_early": aborted_early,
            "total_processed": total_processed,
        }

        print(json.dumps(output))
        if rate_limited:
            print(f"\n  WARNING: {rate_limit_count}/{num_examples} runs hit rate limits ({rate_limit_count/num_examples:.0%}). Score may be unreliable.", file=sys.stderr)
        print(f"\nTarget runs complete: {num_examples} examples")
        if llm_evaluators:
            print(f"Awaiting evaluator agent for: {llm_evaluators}")

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
