#!/usr/bin/env python3
"""Project initializer for Harness Evolver.

Usage:
    init.py [DIR]                                          # auto-detect in DIR (or CWD)
    init.py --harness PATH --eval PATH --tasks PATH        # explicit paths
    init.py --base-dir PATH [--harness-config PATH]        # advanced options

Auto-detects harness.py, eval.py, tasks/ and config.json in the working directory.
Falls back to fuzzy matching (*harness*, *eval*, *score*, dirs with .json files).
Stdlib-only. No external dependencies.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile


def _auto_detect(search_dir):
    """Auto-detect harness, eval, and tasks in a directory.

    Returns (harness_path, eval_path, tasks_path, config_path) or raises SystemExit.
    """
    search_dir = os.path.abspath(search_dir)

    # Exact convention names first
    harness = None
    eval_script = None
    tasks = None
    config = None

    # 1. Exact matches
    for name in ["harness.py"]:
        p = os.path.join(search_dir, name)
        if os.path.isfile(p):
            harness = p
    for name in ["eval.py"]:
        p = os.path.join(search_dir, name)
        if os.path.isfile(p):
            eval_script = p
    for name in ["tasks", "tasks/"]:
        p = os.path.join(search_dir, name.rstrip("/"))
        if os.path.isdir(p):
            tasks = p
    for name in ["config.json"]:
        p = os.path.join(search_dir, name)
        if os.path.isfile(p):
            config = p

    # 2. Fuzzy fallback for harness
    if not harness:
        candidates = [f for f in glob.glob(os.path.join(search_dir, "*.py"))
                      if any(k in os.path.basename(f).lower() for k in ["harness", "agent", "run"])]
        if len(candidates) == 1:
            harness = candidates[0]

    # 3. Fuzzy fallback for eval
    if not eval_script:
        candidates = [f for f in glob.glob(os.path.join(search_dir, "*.py"))
                      if any(k in os.path.basename(f).lower() for k in ["eval", "score", "judge"])
                      and f != harness]
        if len(candidates) == 1:
            eval_script = candidates[0]

    # 4. Fuzzy fallback for tasks
    if not tasks:
        for d in os.listdir(search_dir):
            dp = os.path.join(search_dir, d)
            if os.path.isdir(dp) and any(f.endswith(".json") for f in os.listdir(dp)):
                # Check if at least one JSON has "id" and "input" keys
                for f in os.listdir(dp):
                    if f.endswith(".json"):
                        try:
                            with open(os.path.join(dp, f)) as fh:
                                data = json.load(fh)
                            if "id" in data and "input" in data:
                                tasks = dp
                                break
                        except (json.JSONDecodeError, KeyError):
                            pass
                if tasks:
                    break

    return harness, eval_script, tasks, config


def _detect_api_keys():
    """Detect which LLM/service API keys are available in the environment."""
    KNOWN_KEYS = {
        "ANTHROPIC_API_KEY": "Anthropic (Claude)",
        "OPENAI_API_KEY": "OpenAI (GPT)",
        "GOOGLE_API_KEY": "Google (Gemini)",
        "GEMINI_API_KEY": "Google Gemini",
        "OPENROUTER_API_KEY": "OpenRouter",
        "LANGSMITH_API_KEY": "LangSmith",
        "TOGETHER_API_KEY": "Together AI",
        "GROQ_API_KEY": "Groq",
        "MISTRAL_API_KEY": "Mistral",
        "COHERE_API_KEY": "Cohere",
        "FIREWORKS_API_KEY": "Fireworks AI",
        "DEEPSEEK_API_KEY": "DeepSeek",
        "XAI_API_KEY": "xAI (Grok)",
    }
    detected = {}
    for env_var, display_name in KNOWN_KEYS.items():
        if os.environ.get(env_var):
            detected[env_var] = {"name": display_name, "status": "detected"}
    return detected


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


def _resolve_python():
    """Resolve the Python interpreter for subprocesses.

    Uses the current interpreter (sys.executable) instead of hardcoded 'python3'.
    This prevents version mismatches in monorepo setups where the harness may
    need a specific venv Python different from the system python3.
    """
    exe = sys.executable
    if exe and os.path.isfile(exe):
        return exe
    return "python3"


def _detect_stack(harness_path):
    """Detect technology stack from harness imports."""
    detect_stack_py = os.path.join(os.path.dirname(__file__), "detect_stack.py")
    if not os.path.exists(detect_stack_py):
        return {}
    try:
        r = subprocess.run(
            [_resolve_python(), detect_stack_py, harness_path],
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
    parser = argparse.ArgumentParser(
        description="Initialize Harness Evolver project",
        usage="init.py [DIR] [--harness PATH] [--eval PATH] [--tasks PATH]",
    )
    parser.add_argument("dir", nargs="?", default=".",
                        help="Directory to scan (default: current directory)")
    parser.add_argument("--harness", default=None, help="Path to harness script")
    parser.add_argument("--eval", default=None, help="Path to eval script")
    parser.add_argument("--tasks", default=None, help="Path to tasks directory")
    parser.add_argument("--base-dir", default=None, help="Path for .harness-evolver/")
    parser.add_argument("--harness-config", default=None, help="Path to harness config.json")
    parser.add_argument("--tools-dir", default=None, help="Path to tools directory")
    parser.add_argument("--validation-timeout", type=int, default=30,
                        help="Timeout for harness validation in seconds (default: 30). "
                             "Increase for LLM-powered agents that make real API calls.")
    parser.add_argument("--skip-validation", action="store_true",
                        help="Skip harness validation step. Use when you know the harness "
                             "works but validation times out (e.g. real LLM agent calls).")
    args = parser.parse_args()

    # Auto-detect missing args
    search_dir = os.path.abspath(args.dir)
    if not args.harness or not args.eval or not args.tasks:
        detected_harness, detected_eval, detected_tasks, detected_config = _auto_detect(search_dir)
        if not args.harness:
            args.harness = detected_harness
        if not args.eval:
            args.eval = detected_eval
        if not args.tasks:
            args.tasks = detected_tasks
        if not args.harness_config and detected_config:
            args.harness_config = detected_config

    # Validate we have everything
    missing = []
    if not args.harness:
        missing.append("harness (no harness.py or *harness*.py found)")
    if not args.eval:
        missing.append("eval (no eval.py or *eval*.py found)")
    if not args.tasks:
        missing.append("tasks (no tasks/ directory with JSON files found)")
    if missing:
        print("Could not auto-detect:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        print(f"\nSearched in: {search_dir}", file=sys.stderr)
        print("\nProvide explicitly:", file=sys.stderr)
        print("  /harness-evolve-init --harness PATH --eval PATH --tasks PATH", file=sys.stderr)
        sys.exit(1)

    # Print what was detected
    print(f"Harness: {os.path.relpath(args.harness, search_dir)}")
    print(f"Eval:    {os.path.relpath(args.eval, search_dir)}")
    print(f"Tasks:   {os.path.relpath(args.tasks, search_dir)}/")
    if args.harness_config:
        print(f"Config:  {os.path.relpath(args.harness_config, search_dir)}")
    print()

    base = args.base_dir or os.path.join(search_dir, ".harness-evolver")
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
    # Detect API keys available in environment
    api_keys = _detect_api_keys()
    config["api_keys"] = api_keys

    with open(os.path.join(base, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    if api_keys:
        print("API keys detected:")
        for env_var, info in api_keys.items():
            print(f"  {info['name']} ({env_var})")
        print()

    ls_config = config["eval"].get("langsmith", {})
    if ls_config.get("enabled"):
        print("  LangSmith tracing enabled (LANGSMITH_API_KEY detected)")
        if _check_langsmith_cli():
            print("  langsmith-cli detected — proposer will use it for trace analysis")
        else:
            print("  Recommendation: install langsmith-cli for rich trace analysis:")
            print("    uv tool install langsmith-cli && langsmith-cli auth login")

    # Detect stack — try original harness first, then baseline copy, then scan entire source dir
    stack = _detect_stack(os.path.abspath(args.harness))
    if not stack:
        stack = _detect_stack(os.path.join(base, "baseline", "harness.py"))
    if not stack:
        # Scan the original directory for any .py files with known imports
        harness_dir = os.path.dirname(os.path.abspath(args.harness))
        detect_stack_py = os.path.join(os.path.dirname(__file__), "detect_stack.py")
        if os.path.exists(detect_stack_py):
            try:
                r = subprocess.run(
                    [_resolve_python(), detect_stack_py, harness_dir],
                    capture_output=True, text=True, timeout=30,
                )
                if r.returncode == 0 and r.stdout.strip():
                    stack = json.loads(r.stdout)
            except Exception:
                pass
    config["stack"] = {
        "detected": stack if stack else {},
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

    # Architecture analysis (quick, advisory)
    analyze_py = os.path.join(tools, "analyze_architecture.py")
    if os.path.exists(analyze_py):
        try:
            r = subprocess.run(
                [_resolve_python(), analyze_py, "--harness", args.harness],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0 and r.stdout.strip():
                arch_signals = json.loads(r.stdout)
                config["architecture"] = {
                    "current_topology": arch_signals.get("code_signals", {}).get("estimated_topology", "unknown"),
                    "auto_analyzed": True,
                }
                # Re-write config with architecture
                with open(os.path.join(base, "config.json"), "w") as f:
                    json.dump(config, f, indent=2)
                topo = config["architecture"]["current_topology"]
                if topo != "unknown":
                    print(f"Architecture: {topo}")
        except Exception:
            pass

    # 5. Validate baseline harness
    config_path = os.path.join(base, "baseline", "config.json")
    if args.skip_validation:
        print("Skipping baseline validation (--skip-validation).")
    else:
        print(f"Validating baseline harness (timeout: {args.validation_timeout}s)...")
        val_args = [_resolve_python(), evaluate_py, "validate",
                    "--harness", os.path.join(base, "baseline", "harness.py"),
                    "--timeout", str(args.validation_timeout)]
        if os.path.exists(config_path):
            val_args.extend(["--config", config_path])
        r = subprocess.run(val_args, capture_output=True, text=True)
        if r.returncode != 0:
            hint = ""
            if "TIMEOUT" in r.stderr:
                hint = (f"\n\nHint: The harness timed out after {args.validation_timeout}s. "
                        "This is common for LLM-powered agents that make real API calls.\n"
                        "Try: --validation-timeout 120  (or --skip-validation to bypass)")
            print(f"FAIL: baseline harness validation failed.\n{r.stderr}{hint}", file=sys.stderr)
            sys.exit(1)
        print(r.stdout.strip())

    # 6. Evaluate baseline
    print("Evaluating baseline harness...")
    baseline_traces = tempfile.mkdtemp()
    baseline_scores = os.path.join(base, "baseline_scores.json")
    eval_args = [
        _resolve_python(), evaluate_py, "run",
        "--harness", os.path.join(base, "baseline", "harness.py"),
        "--tasks-dir", os.path.join(base, "eval", "tasks"),
        "--eval", os.path.join(base, "eval", "eval.py"),
        "--traces-dir", baseline_traces,
        "--scores", baseline_scores,
        "--timeout", str(max(args.validation_timeout, 60)),
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
        [_resolve_python(), state_py, "init",
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
