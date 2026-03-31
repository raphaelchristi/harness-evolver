#!/usr/bin/env python3
"""Evaluation orchestrator for Harness Evolver.

Commands:
    validate --harness PATH [--config PATH] [--timeout SECONDS]
    run      --harness PATH --tasks-dir PATH --eval PATH --traces-dir PATH --scores PATH
             [--config PATH] [--timeout SECONDS]

Runs harness per task, captures traces (stdout/stderr/timing), then calls user's eval script.
Stdlib-only. No external dependencies.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time


def _resolve_python():
    """Resolve the Python interpreter to use for subprocesses.

    Prefers the current interpreter (sys.executable) over a hardcoded 'python3'.
    This is critical in monorepo setups where the harness may need a specific
    venv Python (e.g. Python 3.12) while the system 'python3' is a different
    version (e.g. 3.14) with incompatible site-packages.
    """
    exe = sys.executable
    if exe and os.path.isfile(exe):
        return exe
    return "python3"


def _run_harness_on_task(harness, config, task_input_path, output_path, task_traces_dir, timeout, env=None):
    """Run the harness on a single task. Returns (success, elapsed_ms, stdout, stderr)."""
    cmd = [_resolve_python(), harness, "--input", task_input_path, "--output", output_path]
    if task_traces_dir:
        extra_dir = os.path.join(task_traces_dir, "extra")
        os.makedirs(extra_dir, exist_ok=True)
        cmd.extend(["--traces-dir", extra_dir])
    if config and os.path.exists(config):
        cmd.extend(["--config", config])

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
        )
        elapsed_ms = (time.time() - start) * 1000
        # Accept exit code 0 (success) or check if output file exists for non-zero exits.
        # LLM agents with C extensions (numpy, httpx) often segfault (exit 139) during
        # Python shutdown AFTER writing correct output.
        success = result.returncode == 0
        if not success and os.path.exists(output_path):
            try:
                with open(output_path) as f:
                    json.load(f)
                # Valid JSON output exists despite non-zero exit — treat as success
                success = True
            except (json.JSONDecodeError, OSError):
                pass
        return success, elapsed_ms, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.time() - start) * 1000
        return False, elapsed_ms, "", f"TIMEOUT after {timeout}s"
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        return False, elapsed_ms, "", str(e)


def cmd_validate(args):
    harness = args.harness
    config = getattr(args, "config", None)
    timeout = getattr(args, "timeout", 30) or 30

    if not os.path.exists(harness):
        print(f"FAIL: harness not found: {harness}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        dummy_task = {"id": "validation", "input": "test input for validation", "metadata": {}}
        input_path = os.path.join(tmpdir, "input.json")
        output_path = os.path.join(tmpdir, "output.json")
        with open(input_path, "w") as f:
            json.dump(dummy_task, f)

        success, elapsed, stdout, stderr = _run_harness_on_task(
            harness, config, input_path, output_path, None, timeout=timeout,
        )

        if not success:
            hint = ""
            if "TIMEOUT" in stderr:
                hint = (f"\nHint: validation timed out after {timeout}s. "
                        "For LLM-powered agents that make real API calls, "
                        "use --timeout to increase the limit: "
                        f"evaluate.py validate --harness {harness} --timeout 120")
            print(f"FAIL: harness exited with error.\nstderr: {stderr}{hint}", file=sys.stderr)
            sys.exit(1)

        if not os.path.exists(output_path):
            print("FAIL: harness did not create output file.", file=sys.stderr)
            sys.exit(1)

        try:
            with open(output_path) as f:
                output = json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"FAIL: output is not valid JSON: {e}", file=sys.stderr)
            sys.exit(1)

        if "id" not in output or "output" not in output:
            print(f"FAIL: output missing 'id' or 'output' fields. Got: {output}", file=sys.stderr)
            sys.exit(1)

        print(f"OK: harness validated in {elapsed:.0f}ms. Output: {output}")


def cmd_run(args):
    harness = args.harness
    config = getattr(args, "config", None)
    tasks_dir = args.tasks_dir
    eval_script = getattr(args, "eval")
    traces_dir = args.traces_dir
    scores_path = args.scores
    timeout = args.timeout

    os.makedirs(traces_dir, exist_ok=True)

    task_files = sorted(f for f in os.listdir(tasks_dir) if f.endswith(".json"))
    if not task_files:
        print(f"FAIL: no .json task files in {tasks_dir}", file=sys.stderr)
        sys.exit(1)

    all_stdout = []
    all_stderr = []
    timing = {"per_task": {}}
    results_dir = tempfile.mkdtemp()

    # LangSmith: setup auto-tracing env vars if configured
    langsmith_env = None
    project_config_path = os.path.join(os.path.dirname(os.path.dirname(traces_dir)), "config.json")
    if os.path.exists(project_config_path):
        with open(project_config_path) as f:
            project_config = json.load(f)
        ls = project_config.get("eval", {}).get("langsmith", {})
        if ls.get("enabled"):
            api_key = os.environ.get(ls.get("api_key_env", "LANGSMITH_API_KEY"), "")
            if api_key:
                version = os.path.basename(os.path.dirname(traces_dir))
                ls_project = f"{ls.get('project_prefix', 'harness-evolver')}-{version}"
                langsmith_env = {
                    **os.environ,
                    "LANGCHAIN_TRACING_V2": "true",
                    "LANGCHAIN_API_KEY": api_key,
                    "LANGCHAIN_PROJECT": ls_project,
                }
                # Write the project name so the evolve skill knows where to find traces
                ls_project_file = os.path.join(os.path.dirname(os.path.dirname(traces_dir)), "langsmith_project.txt")
                with open(ls_project_file, "w") as f:
                    f.write(ls_project)

    for task_file in task_files:
        task_path = os.path.join(tasks_dir, task_file)
        with open(task_path) as f:
            task = json.load(f)
        task_id = task["id"]

        task_input = {k: v for k, v in task.items() if k != "expected"}

        task_traces_dir = os.path.join(traces_dir, task_id)
        os.makedirs(task_traces_dir, exist_ok=True)

        input_path = os.path.join(task_traces_dir, "input.json")
        with open(input_path, "w") as f:
            json.dump(task_input, f, indent=2)

        output_path = os.path.join(results_dir, task_file)

        success, elapsed_ms, stdout, stderr = _run_harness_on_task(
            harness, config, input_path, output_path, task_traces_dir, timeout,
            env=langsmith_env,
        )

        if os.path.exists(output_path):
            shutil.copy2(output_path, os.path.join(task_traces_dir, "output.json"))
        else:
            with open(os.path.join(task_traces_dir, "output.json"), "w") as f:
                json.dump({"id": task_id, "output": "", "error": "harness failed"}, f)

        timing["per_task"][task_id] = round(elapsed_ms, 1)
        all_stdout.append(f"--- {task_id} ---\n{stdout}")
        all_stderr.append(f"--- {task_id} ---\n{stderr}")

    timing["total_ms"] = round(sum(timing["per_task"].values()), 1)
    with open(os.path.join(traces_dir, "timing.json"), "w") as f:
        json.dump(timing, f, indent=2)
    with open(os.path.join(traces_dir, "stdout.log"), "w") as f:
        f.write("\n".join(all_stdout))
    with open(os.path.join(traces_dir, "stderr.log"), "w") as f:
        f.write("\n".join(all_stderr))

    eval_cmd = [
        _resolve_python(), eval_script,
        "--results-dir", results_dir,
        "--tasks-dir", tasks_dir,
        "--scores", scores_path,
    ]
    result = subprocess.run(eval_cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"FAIL: eval script failed.\nstderr: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(scores_path):
        scores = json.load(open(scores_path))
        print(f"Evaluation complete. combined_score: {scores.get('combined_score', 'N/A')}")
    else:
        print("WARNING: eval script did not produce scores file.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Harness Evolver evaluation orchestrator")
    sub = parser.add_subparsers(dest="command")

    p_val = sub.add_parser("validate")
    p_val.add_argument("--harness", required=True)
    p_val.add_argument("--config", default=None)
    p_val.add_argument("--timeout", type=int, default=30,
                       help="Validation timeout in seconds (default: 30). "
                            "Increase for LLM-powered agents that make real API calls.")

    p_run = sub.add_parser("run")
    p_run.add_argument("--harness", required=True)
    p_run.add_argument("--config", default=None)
    p_run.add_argument("--tasks-dir", required=True)
    p_run.add_argument("--eval", required=True)
    p_run.add_argument("--traces-dir", required=True)
    p_run.add_argument("--scores", required=True)
    p_run.add_argument("--timeout", type=int, default=60)

    args = parser.parse_args()
    if args.command == "validate":
        cmd_validate(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
