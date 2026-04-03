#!/usr/bin/env python3
"""Integrated preflight check for the evolution loop.

Runs all pre-loop validations in one pass:
1. API key resolution (env var, .env, credentials)
2. Config schema validation (.evolver.json structure)
3. State validation (config matches LangSmith reality)
4. Dataset health (size, difficulty, splits, secrets)
5. Entry point canary (1 example to verify agent works)

Usage:
    python3 preflight.py --config .evolver.json
    python3 preflight.py --config .evolver.json --skip-canary

Exits 0 if all checks pass, 1 if any fail.
Stdlib-only for core logic; langsmith SDK for state/health/canary checks.
"""

import argparse
import json
import os
import subprocess
import sys


def resolve_tools_dir():
    """Find the tools directory."""
    # Same directory as this script
    return os.path.dirname(os.path.abspath(__file__))


def resolve_python():
    """Find the evolver Python interpreter."""
    evolver_py = os.environ.get("EVOLVER_PY")
    if evolver_py and os.path.isfile(evolver_py):
        return evolver_py
    venv = os.path.expanduser("~/.evolver/venv/bin/python")
    if os.path.isfile(venv):
        return venv
    return sys.executable


def check_api_key(config_path):
    """Check if LANGSMITH_API_KEY can be resolved."""
    if os.environ.get("LANGSMITH_API_KEY"):
        return {"pass": True, "source": "environment variable"}

    # Check .env in config directory
    config_dir = os.path.dirname(os.path.abspath(config_path))
    for env_path in [".env", os.path.join(config_dir, ".env")]:
        if os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("LANGSMITH_API_KEY=") and not line.startswith("#"):
                            key = line.split("=", 1)[1].strip().strip("'\"")
                            if key:
                                return {"pass": True, "source": f".env ({env_path})"}
            except OSError:
                pass

    # Check credentials file
    import platform
    if platform.system() == "Darwin":
        creds = os.path.expanduser("~/Library/Application Support/langsmith-cli/credentials")
    else:
        creds = os.path.expanduser("~/.config/langsmith-cli/credentials")
    if os.path.exists(creds):
        try:
            with open(creds) as f:
                for line in f:
                    if line.strip().startswith("LANGSMITH_API_KEY="):
                        return {"pass": True, "source": f"credentials ({creds})"}
        except OSError:
            pass

    return {"pass": False, "source": None, "error": "LANGSMITH_API_KEY not found in env, .env, or credentials"}


def check_config_schema(config):
    """Validate .evolver.json structure."""
    issues = []

    REQUIRED_FIELDS = {
        "project": str,
        "dataset": str,
        "entry_point": str,
        "evaluators": list,
        "history": list,
    }

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in config:
            issues.append(f"missing required field: {field}")
        elif not isinstance(config[field], expected_type):
            issues.append(f"{field} must be {expected_type.__name__}, got {type(config[field]).__name__}")

    if "evaluators" in config and isinstance(config["evaluators"], list):
        if len(config["evaluators"]) == 0:
            issues.append("evaluators list is empty")

    if "history" in config and isinstance(config["history"], list):
        for i, h in enumerate(config["history"]):
            if not isinstance(h, dict):
                issues.append(f"history[{i}] must be a dict")
                continue
            if "version" not in h:
                issues.append(f"history[{i}] missing 'version'")
            if "score" not in h:
                issues.append(f"history[{i}] missing 'score'")
            elif not isinstance(h["score"], (int, float)):
                issues.append(f"history[{i}].score must be numeric, got {type(h['score']).__name__}")

    if "best_score" in config:
        bs = config["best_score"]
        if bs is not None and not isinstance(bs, (int, float)):
            issues.append(f"best_score must be numeric or null, got {type(bs).__name__}")

    if "evaluator_weights" in config:
        ew = config["evaluator_weights"]
        if ew is not None and not isinstance(ew, dict):
            issues.append(f"evaluator_weights must be a dict or null, got {type(ew).__name__}")

    mode = config.get("mode")
    if mode is not None and mode not in ("light", "balanced", "heavy"):
        issues.append(f"mode must be light/balanced/heavy, got '{mode}'")

    return {"pass": len(issues) == 0, "issues": issues}


def run_tool(python, tool_path, args, timeout=60):
    """Run a Python tool and capture output."""
    cmd = [python, tool_path] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ},
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"timeout after {timeout}s"}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Integrated preflight check for evolution")
    parser.add_argument("--config", default=".evolver.json", help="Path to .evolver.json")
    parser.add_argument("--skip-canary", action="store_true", help="Skip canary run")
    parser.add_argument("--skip-health", action="store_true", help="Skip dataset health check")
    parser.add_argument("--output", default=None, help="Write results to file")
    args = parser.parse_args()

    tools_dir = resolve_tools_dir()
    python = resolve_python()

    if not os.path.exists(args.config):
        print(json.dumps({"all_pass": False, "error": f"Config not found: {args.config}"}))
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    checks = {}

    # 1. API Key
    print("  [1/5] API key...", end="", flush=True, file=sys.stderr)
    checks["api_key"] = check_api_key(args.config)
    status = "OK" if checks["api_key"]["pass"] else "FAIL"
    print(f" {status}", file=sys.stderr)

    # 2. Config Schema
    print("  [2/5] Config schema...", end="", flush=True, file=sys.stderr)
    checks["schema"] = check_config_schema(config)
    status = "OK" if checks["schema"]["pass"] else f"FAIL ({len(checks['schema']['issues'])} issues)"
    print(f" {status}", file=sys.stderr)

    # 3. State Validation (requires API key)
    if checks["api_key"]["pass"]:
        print("  [3/5] State validation...", end="", flush=True, file=sys.stderr)
        result = run_tool(python, os.path.join(tools_dir, "validate_state.py"),
                          ["--config", args.config])
        if result["exit_code"] == 0 and result["stdout"]:
            try:
                state = json.loads(result["stdout"])
                checks["state"] = {
                    "pass": state.get("valid", False),
                    "issues": state.get("issues", []),
                    "dataset_examples": state.get("dataset_examples", 0),
                }
            except json.JSONDecodeError:
                checks["state"] = {"pass": False, "error": "invalid JSON from validate_state"}
        else:
            checks["state"] = {"pass": False, "error": result["stderr"][:200] or "validate_state failed"}
        status = "OK" if checks["state"]["pass"] else "FAIL"
        print(f" {status}", file=sys.stderr)
    else:
        checks["state"] = {"pass": False, "skipped": True, "error": "no API key"}
        print("  [3/5] State validation... SKIP (no API key)", file=sys.stderr)

    # 4. Dataset Health
    if not args.skip_health and checks["api_key"]["pass"]:
        print("  [4/5] Dataset health...", end="", flush=True, file=sys.stderr)
        health_output = os.path.join(os.path.dirname(args.config) or ".", "health_report.json")
        result = run_tool(python, os.path.join(tools_dir, "dataset_health.py"),
                          ["--config", args.config, "--output", health_output])
        if os.path.exists(health_output):
            try:
                health = json.load(open(health_output))
                critical = [i for i in health.get("issues", []) if i.get("severity") == "critical"]
                # Check held_out split exists (required for unbiased comparison)
                splits = health.get("splits", {})
                has_held_out = splits.get("has_held_out", False) if splits else False
                if not has_held_out:
                    critical.append({"severity": "critical", "message": "No held_out split — run /evolver:health to create train/held_out splits"})

                checks["health"] = {
                    "pass": len(critical) == 0,
                    "health_score": health.get("health_score", 0),
                    "example_count": health.get("example_count", 0),
                    "has_held_out": has_held_out,
                    "critical_issues": len(critical),
                }
            except json.JSONDecodeError:
                checks["health"] = {"pass": False, "error": "invalid health report"}
        else:
            checks["health"] = {"pass": False, "error": result["stderr"][:200] or "health check failed"}
        status = "OK" if checks["health"]["pass"] else "FAIL"
        print(f" {status}", file=sys.stderr)
    else:
        checks["health"] = {"pass": True, "skipped": True}
        print("  [4/5] Dataset health... SKIP", file=sys.stderr)

    # 5. Canary Run
    if not args.skip_canary and checks["api_key"]["pass"]:
        print("  [5/5] Canary run...", end="", flush=True, file=sys.stderr)
        result = run_tool(python, os.path.join(tools_dir, "run_eval.py"),
                          ["--config", args.config, "--worktree-path", ".",
                           "--experiment-prefix", "preflight-canary", "--preflight-only"],
                          timeout=120)
        if result["exit_code"] == 0:
            checks["canary"] = {"pass": True}
        elif result["exit_code"] == 2:
            checks["canary"] = {"pass": False, "error": "agent produced no output"}
        else:
            checks["canary"] = {"pass": False, "error": result["stderr"][:200] or "canary failed"}
        status = "OK" if checks["canary"]["pass"] else "FAIL"
        print(f" {status}", file=sys.stderr)
    else:
        checks["canary"] = {"pass": True, "skipped": True}
        print("  [5/5] Canary run... SKIP", file=sys.stderr)

    # Summary
    all_pass = all(c["pass"] for c in checks.values())
    output = {"all_pass": all_pass, "checks": checks}

    out_str = json.dumps(output, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(out_str + "\n")
    print(out_str)

    print(file=sys.stderr)
    if all_pass:
        print("  PREFLIGHT PASSED — ready to evolve", file=sys.stderr)
    else:
        failed = [k for k, v in checks.items() if not v["pass"]]
        print(f"  PREFLIGHT FAILED — {len(failed)} check(s): {', '.join(failed)}", file=sys.stderr)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
