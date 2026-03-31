#!/usr/bin/env python3
"""Evaluation orchestrator for Harness Evolver.

Commands:
    validate --harness PATH [--config PATH]
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


def _run_harness_on_task(harness, config, task_input_path, output_path, task_traces_dir, timeout):
    """Run the harness on a single task. Returns (success, elapsed_ms, stdout, stderr)."""
    cmd = ["python3", harness, "--input", task_input_path, "--output", output_path]
    if task_traces_dir:
        extra_dir = os.path.join(task_traces_dir, "extra")
        os.makedirs(extra_dir, exist_ok=True)
        cmd.extend(["--traces-dir", extra_dir])
    if config and os.path.exists(config):
        cmd.extend(["--config", config])

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        elapsed_ms = (time.time() - start) * 1000
        return result.returncode == 0, elapsed_ms, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.time() - start) * 1000
        return False, elapsed_ms, "", f"TIMEOUT after {timeout}s"
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        return False, elapsed_ms, "", str(e)


def cmd_validate(args):
    harness = args.harness
    config = getattr(args, "config", None)

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
            harness, config, input_path, output_path, None, timeout=30,
        )

        if not success:
            print(f"FAIL: harness exited with error.\nstderr: {stderr}", file=sys.stderr)
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
        "python3", eval_script,
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
