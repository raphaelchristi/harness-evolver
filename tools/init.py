#!/usr/bin/env python3
"""Project initializer for Harness Evolver.

Usage:
    init.py --harness PATH --eval PATH --tasks PATH --base-dir PATH
            [--harness-config PATH] [--tools-dir PATH]

Creates the .harness-evolver/ directory structure, copies baseline files,
runs validation, evaluates the baseline, and initializes state.
Stdlib-only. No external dependencies.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile


def _detect_langsmith():
    """Auto-detect LangSmith API key and return config section."""
    if os.environ.get("LANGSMITH_API_KEY"):
        return {
            "enabled": True,
            "api_key_env": "LANGSMITH_API_KEY",
            "project_prefix": "harness-evolver",
        }
    return {"enabled": False}


def _check_langsmith_cli():
    """Check if langsmith-cli is installed."""
    try:
        r = subprocess.run(["langsmith-cli", "self", "detect"],
                          capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _detect_stack(harness_path):
    """Detect technology stack from harness imports."""
    detect_stack_py = os.path.join(os.path.dirname(__file__), "detect_stack.py")
    if not os.path.exists(detect_stack_py):
        return {}
    try:
        r = subprocess.run(
            ["python3", detect_stack_py, harness_path],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception:
        pass
    return {}


def _check_context7_available():
    """Check if Context7 MCP is configured in Claude Code."""
    settings_paths = [
        os.path.expanduser("~/.claude/settings.json"),
        os.path.expanduser("~/.claude.json"),
    ]
    for path in settings_paths:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    settings = json.load(f)
                mcp = settings.get("mcpServers", {})
                if "context7" in mcp or "Context7" in mcp:
                    return True
            except (json.JSONDecodeError, KeyError):
                pass
    return False


def main():
    parser = argparse.ArgumentParser(description="Initialize Harness Evolver project")
    parser.add_argument("--harness", required=True, help="Path to harness script")
    parser.add_argument("--eval", required=True, help="Path to eval script")
    parser.add_argument("--tasks", required=True, help="Path to tasks directory")
    parser.add_argument("--base-dir", required=True, help="Path for .harness-evolver/")
    parser.add_argument("--harness-config", default=None, help="Path to harness config.json")
    parser.add_argument("--tools-dir", default=None, help="Path to tools directory")
    args = parser.parse_args()

    base = args.base_dir
    tools = args.tools_dir or os.path.dirname(__file__)

    evaluate_py = os.path.join(tools, "evaluate.py")
    state_py = os.path.join(tools, "state.py")

    # 1. Create directory structure
    for d in ["baseline", "eval/tasks", "harnesses"]:
        os.makedirs(os.path.join(base, d), exist_ok=True)

    # 2. Copy baseline harness
    shutil.copy2(args.harness, os.path.join(base, "baseline", "harness.py"))
    if args.harness_config and os.path.exists(args.harness_config):
        shutil.copy2(args.harness_config, os.path.join(base, "baseline", "config.json"))

    # 3. Copy eval script and tasks
    shutil.copy2(args.eval, os.path.join(base, "eval", "eval.py"))
    for f in os.listdir(args.tasks):
        src = os.path.join(args.tasks, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(base, "eval", "tasks", f))

    # 4. Generate config.json
    harness_name = os.path.basename(args.harness)
    eval_name = os.path.basename(args.eval)
    config = {
        "version": "0.1.0",
        "harness": {
            "command": f"python3 {harness_name}",
            "args": ["--input", "{input}", "--output", "{output}",
                     "--traces-dir", "{traces_dir}", "--config", "{config}"],
            "timeout_per_task_sec": 60,
        },
        "eval": {
            "command": f"python3 {eval_name}",
            "args": ["--results-dir", "{results_dir}", "--tasks-dir", "{tasks_dir}",
                     "--scores", "{scores}"],
            "langsmith": _detect_langsmith(),
        },
        "evolution": {
            "max_iterations": 10,
            "candidates_per_iter": 1,
            "stagnation_limit": 3,
            "stagnation_threshold": 0.01,
            "target_score": None,
        },
        "paths": {
            "baseline": "baseline/",
            "eval_tasks": "eval/tasks/",
            "eval_script": "eval/eval.py",
            "harnesses": "harnesses/",
        },
    }
    with open(os.path.join(base, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    ls_config = config["eval"].get("langsmith", {})
    if ls_config.get("enabled"):
        print("  LangSmith tracing enabled (LANGSMITH_API_KEY detected)")
        if _check_langsmith_cli():
            print("  langsmith-cli detected — proposer will use it for trace analysis")
        else:
            print("  Recommendation: install langsmith-cli for rich trace analysis:")
            print("    uv tool install langsmith-cli && langsmith-cli auth login")

    # Detect stack
    stack = _detect_stack(args.harness)
    config["stack"] = {
        "detected": stack,
        "documentation_hint": "use context7",
        "auto_detected": True,
    }
    # Re-write config.json with stack section added
    with open(os.path.join(base, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    if stack:
        print("Stack detected:")
        for lib_info in stack.values():
            print(f"  {lib_info['display']}")
        if not _check_context7_available():
            print("\nRecommendation: install Context7 MCP for up-to-date documentation:")
            print("  claude mcp add context7 -- npx -y @upstash/context7-mcp@latest")

    # 5. Validate baseline harness
    print("Validating baseline harness...")
    val_args = ["python3", evaluate_py, "validate",
                "--harness", os.path.join(base, "baseline", "harness.py")]
    config_path = os.path.join(base, "baseline", "config.json")
    if os.path.exists(config_path):
        val_args.extend(["--config", config_path])
    r = subprocess.run(val_args, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL: baseline harness validation failed.\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    print(r.stdout.strip())

    # 6. Evaluate baseline
    print("Evaluating baseline harness...")
    baseline_traces = tempfile.mkdtemp()
    baseline_scores = os.path.join(base, "baseline_scores.json")
    eval_args = [
        "python3", evaluate_py, "run",
        "--harness", os.path.join(base, "baseline", "harness.py"),
        "--tasks-dir", os.path.join(base, "eval", "tasks"),
        "--eval", os.path.join(base, "eval", "eval.py"),
        "--traces-dir", baseline_traces,
        "--scores", baseline_scores,
        "--timeout", "60",
    ]
    if os.path.exists(config_path):
        eval_args.extend(["--config", config_path])
    r = subprocess.run(eval_args, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"WARNING: baseline evaluation failed. Using score 0.0.\n{r.stderr}", file=sys.stderr)
        baseline_score = 0.0
    else:
        print(r.stdout.strip())
        scores = json.load(open(baseline_scores))
        baseline_score = scores.get("combined_score", 0.0)

    if os.path.exists(baseline_scores):
        os.remove(baseline_scores)

    # 7. Initialize state with baseline score
    print(f"Baseline score: {baseline_score:.2f}")
    r = subprocess.run(
        ["python3", state_py, "init",
         "--base-dir", base,
         "--baseline-score", str(baseline_score)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"FAIL: state init failed.\n{r.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"\nInitialized .harness-evolver/ at {base}")
    print(f"Baseline score: {baseline_score:.2f}")
    print("Run /harness-evolve to start the optimization loop.")


if __name__ == "__main__":
    main()
