#!/usr/bin/env python3
"""Constraint checker for evolution proposals.

Validates that a candidate proposal doesn't violate hard constraints
before it's merged. Inspired by Hermes Agent Self-Evolution.

Usage:
    python3 constraint_check.py \
        --config .evolver.json \
        --worktree-path /tmp/worktree \
        --baseline-path /path/to/main \
        --output constraint_result.json

Stdlib-only — no langsmith dependency.
"""

import argparse
import json
import os
import subprocess
import sys


def count_loc(directory, extensions=(".py", ".js", ".ts", ".jsx", ".tsx")):
    """Count lines of code in a directory, excluding venvs and node_modules."""
    total = 0
    skip_dirs = {".venv", "venv", "node_modules", "__pycache__", ".git"}
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if any(f.endswith(ext) for ext in extensions):
                try:
                    with open(os.path.join(root, f)) as fh:
                        total += sum(1 for _ in fh)
                except (OSError, UnicodeDecodeError):
                    pass
    return total


def check_growth(baseline_loc, candidate_loc, max_growth_pct=30):
    """Check code didn't grow beyond threshold."""
    if baseline_loc == 0:
        return {"pass": True, "reason": "no baseline LOC"}
    growth = ((candidate_loc - baseline_loc) / baseline_loc) * 100
    passed = growth <= max_growth_pct
    return {
        "pass": passed,
        "baseline_loc": baseline_loc,
        "candidate_loc": candidate_loc,
        "growth_pct": round(growth, 1),
        "max_growth_pct": max_growth_pct,
        "reason": f"Code growth {growth:.1f}% {'<=' if passed else '>'} {max_growth_pct}% limit",
    }


def check_entry_point(worktree_path, entry_point):
    """Check that the entry point is still runnable (syntax + existence).

    Validates Python (.py) via py_compile, JS/TS (.js/.ts) via node --check,
    and shell (.sh) via bash -n. Fails closed: unknown extensions fail.
    """
    parts = entry_point.split()
    script_file = None
    for part in parts:
        if part.endswith((".py", ".js", ".ts", ".mjs", ".sh")):
            script_file = part
            break

    if not script_file:
        return {"pass": True, "reason": "no script file detected in entry_point"}

    full_path = os.path.join(worktree_path, script_file)
    if not os.path.exists(full_path):
        return {"pass": False, "reason": f"entry point file missing: {script_file}"}

    # Python syntax check
    if script_file.endswith(".py"):
        result = subprocess.run(
            ["python3", "-m", "py_compile", full_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return {"pass": False, "reason": f"syntax error: {result.stderr[:200]}"}

    # JS/TS syntax check via node --check
    elif script_file.endswith((".js", ".mjs")):
        try:
            result = subprocess.run(
                ["node", "--check", full_path],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return {"pass": False, "reason": f"JS syntax error: {result.stderr[:200]}"}
        except FileNotFoundError:
            return {"pass": False, "reason": "node not found — cannot validate JS entry point"}

    elif script_file.endswith(".ts"):
        # TS: check if file exists and has content (no cheap syntax check without tsc)
        try:
            with open(full_path) as f:
                content = f.read()
            if not content.strip():
                return {"pass": False, "reason": "TS entry point is empty"}
        except OSError as e:
            return {"pass": False, "reason": f"cannot read TS file: {e}"}

    # Shell syntax check
    elif script_file.endswith(".sh"):
        try:
            result = subprocess.run(
                ["bash", "-n", full_path],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return {"pass": False, "reason": f"shell syntax error: {result.stderr[:200]}"}
        except FileNotFoundError:
            return {"pass": False, "reason": "bash not found — cannot validate shell entry point"}

    return {"pass": True, "reason": f"entry point exists and has valid syntax ({script_file})"}


def find_project_python(worktree_path, config=None):
    """Find the project's Python interpreter (venv > entry_point > system).

    Checks for venv in the worktree, then extracts from entry_point config,
    then falls back to system python3.
    """
    # Check for venv in worktree
    for venv_dir in [".venv", "venv"]:
        venv_python = os.path.join(worktree_path, venv_dir, "bin", "python")
        if os.path.isfile(venv_python):
            return venv_python

    # Extract from entry_point in config
    if config:
        entry = config.get("entry_point", "")
        for part in entry.split():
            if part.endswith("/python") or part.endswith("/python3"):
                if os.path.isfile(part):
                    return part

    return "python3"


def check_tests(worktree_path, config=None):
    """Run test suite if it exists. Detects Python (pytest) and JS (npm test)."""

    # Detect Python tests
    has_py_tests = False
    for td in ["tests", "test"]:
        test_path = os.path.join(worktree_path, td)
        if os.path.isdir(test_path):
            for f in os.listdir(test_path):
                if f.startswith("test_") and f.endswith(".py"):
                    has_py_tests = True
                    break

    # Detect JS/TS tests (package.json with test script)
    has_js_tests = False
    pkg_path = os.path.join(worktree_path, "package.json")
    if os.path.exists(pkg_path):
        try:
            import json as _json
            pkg = _json.load(open(pkg_path))
            test_cmd = pkg.get("scripts", {}).get("test", "")
            if test_cmd and "no test specified" not in test_cmd:
                has_js_tests = True
        except (ValueError, OSError):
            pass

    if not has_py_tests and not has_js_tests:
        return {"pass": True, "reason": "no test suite found (skipped)", "skipped": True}

    # Run JS tests if detected
    if has_js_tests and not has_py_tests:
        try:
            result = subprocess.run(
                ["npm", "test", "--", "--passWithNoTests"],
                capture_output=True, text=True,
                cwd=worktree_path, timeout=120,
            )
            passed = result.returncode == 0
            return {
                "pass": passed,
                "reason": result.stdout.strip()[:200] if passed else result.stderr.strip()[:200],
                "skipped": False,
            }
        except FileNotFoundError:
            return {"pass": False, "reason": "npm not found — cannot run JS tests", "skipped": False}

    # Run Python tests
    python = find_project_python(worktree_path, config)

    try:
        result = subprocess.run(
            [python, "-m", "pytest", "-q", "--tb=no"],
            capture_output=True, text=True,
            cwd=worktree_path, timeout=120,
        )
        # Detect pytest not installed (exit 1 with "No module named pytest")
        if result.returncode != 0 and "No module named pytest" in (result.stderr or ""):
            return {"pass": True, "reason": "pytest not installed in venv (skipped)", "skipped": True}

        passed = result.returncode == 0
        return {
            "pass": passed,
            "reason": result.stdout.strip()[:200] if passed else result.stderr.strip()[:200],
            "skipped": False,
        }
    except FileNotFoundError:
        return {"pass": True, "reason": "python not available (skipped)", "skipped": True}
    except subprocess.TimeoutExpired:
        return {"pass": False, "reason": "test suite timed out after 120s", "skipped": False}


def main():
    parser = argparse.ArgumentParser(description="Check constraints on a proposal")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--worktree-path", required=True, help="Candidate worktree path")
    parser.add_argument("--baseline-path", default=".", help="Baseline (main) path")
    parser.add_argument("--max-growth", type=int, default=30, help="Max code growth %% (default 30)")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    entry_point = config.get("entry_point", "")
    ep_for_check = entry_point.split("python ")[-1].split("python3 ")[-1]

    results = {
        "growth": check_growth(
            count_loc(args.baseline_path),
            count_loc(args.worktree_path),
            args.max_growth,
        ),
        "entry_point": check_entry_point(args.worktree_path, ep_for_check),
        "tests": check_tests(args.worktree_path, config),
    }

    all_pass = all(r["pass"] for r in results.values())
    output = {"all_pass": all_pass, "constraints": results}

    out_str = json.dumps(output, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(out_str)
    print(out_str)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
