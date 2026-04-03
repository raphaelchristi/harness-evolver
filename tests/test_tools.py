#!/usr/bin/env python3
"""Integration tests for all Python tools.

Tests that each tool:
1. Imports without error (syntax, dependencies)
2. Has a main() function or can be invoked via CLI
3. Handles --help without crashing
4. Handles missing/invalid input gracefully

These are smoke tests — they verify tools don't crash,
not that they produce correct output. Run with:

    python3 -m pytest tests/test_tools.py -v

Or without pytest:

    python3 tests/test_tools.py
"""

import json
import os
import subprocess
import sys
import tempfile

TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools")
PYTHON = sys.executable


def run_tool(tool_name, args=None, stdin=None, timeout=30):
    """Run a tool and return (exit_code, stdout, stderr)."""
    cmd = [PYTHON, os.path.join(TOOLS_DIR, tool_name)] + (args or [])
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        input=stdin, cwd=TOOLS_DIR,
    )
    return result.returncode, result.stdout, result.stderr


def make_mock_config():
    """Create a temporary mock .evolver.json for testing."""
    config = {
        "version": "3.0.0",
        "project": "test-project",
        "dataset": "test-dataset",
        "dataset_id": "00000000-0000-0000-0000-000000000000",
        "project_dir": "",
        "entry_point": "python3 echo.py {input_text}",
        "evaluators": ["correctness", "has_output"],
        "evaluator_weights": {"correctness": 0.7, "has_output": 0.3},
        "optimization_goals": ["accuracy"],
        "production_project": None,
        "baseline_experiment": "baseline-test",
        "best_experiment": "baseline-test",
        "best_score": 0.5,
        "iterations": 1,
        "framework": "custom",
        "created_at": "2026-01-01T00:00:00Z",
        "history": [
            {"version": "baseline", "score": 0.3, "experiment": "baseline-test"},
            {
                "version": "v001", "score": 0.5, "experiment": "v001-test",
                "tokens": 1500, "latency_ms": 400, "error_count": 0,
                "passing": 8, "total": 10, "approach": "Fixed input parsing",
                "lens": "failure_cluster", "code_loc": 150,
                "per_evaluator": {"correctness": 0.4, "has_output": 0.9},
            },
        ],
    }
    fd, path = tempfile.mkstemp(suffix=".json", prefix="evolver_test_")
    with os.fdopen(fd, "w") as f:
        json.dump(config, f, indent=2)
    return path


# ─── Test: All tools parse without syntax errors ───

def test_all_tools_syntax():
    """Every .py file in tools/ must be valid Python."""
    import ast
    errors = []
    for fname in sorted(os.listdir(TOOLS_DIR)):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(TOOLS_DIR, fname)
        try:
            with open(path) as f:
                ast.parse(f.read())
        except SyntaxError as e:
            errors.append(f"{fname}: {e}")
    assert not errors, f"Syntax errors:\n" + "\n".join(errors)


# ─── Test: Tools that accept --help ───

TOOLS_WITH_HELP = [
    "add_evaluator.py",
    "adversarial_inject.py",
    "analyze_architecture.py",
    "constraint_check.py",
    "dataset_health.py",
    "evolution_chart.py",
    "iteration_gate.py",
    "mine_sessions.py",
    "preflight.py",
    "read_results.py",
    "regression_tracker.py",
    "run_eval.py",
    "seed_from_traces.py",
    "setup.py",
    "synthesize_strategy.py",
    "trace_insights.py",
    "validate_state.py",
]


def test_help_flags():
    """Every tool with argparse should respond to --help."""
    errors = []
    for tool in TOOLS_WITH_HELP:
        code, stdout, stderr = run_tool(tool, ["--help"])
        if code != 0:
            errors.append(f"{tool}: exit {code}, stderr: {stderr[:200]}")
    assert not errors, f"--help failures:\n" + "\n".join(errors)


# ─── Test: evolution_chart.py with mock config ───

def test_evolution_chart():
    """evolution_chart.py renders without crashing on mock data."""
    config_path = make_mock_config()
    try:
        code, stdout, stderr = run_tool("evolution_chart.py", ["--config", config_path, "--no-color"])
        assert code == 0, f"exit {code}: {stderr[:300]}"
        assert "EVOLUTION REPORT" in stdout
        assert "SCORE PROGRESSION" in stdout
        assert "SCORE CHART" in stdout
        # Should show LOC column (mock has code_loc)
        assert "LOC" in stdout or "150" in stdout
    finally:
        os.unlink(config_path)


# ─── Test: evolution_chart.py backward compat (lean history) ───

def test_evolution_chart_lean_history():
    """evolution_chart.py handles old-format history without enriched fields."""
    config = {
        "project": "test", "dataset": "test", "evaluators": ["correctness"],
        "history": [{"version": "baseline", "score": 0.5, "experiment": "test"}],
    }
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(config, f)
    try:
        code, stdout, stderr = run_tool("evolution_chart.py", ["--config", path, "--no-color"])
        assert code == 0, f"exit {code}: {stderr[:300]}"
        assert "EVOLUTION REPORT" in stdout
    finally:
        os.unlink(path)


# ─── Test: secret_filter.py ───

def test_secret_filter_detects():
    """secret_filter.py detects API keys."""
    code, stdout, stderr = run_tool(
        "secret_filter.py", stdin="my key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
    )
    assert code == 1  # exit 1 = secrets found
    result = json.loads(stdout)
    assert result["has_secrets"] is True
    assert result["count"] > 0


def test_secret_filter_clean():
    """secret_filter.py passes clean text."""
    code, stdout, stderr = run_tool(
        "secret_filter.py", stdin="This is normal text about APIs and authentication"
    )
    assert code == 0
    result = json.loads(stdout)
    assert result["has_secrets"] is False


# ─── Test: constraint_check.py ───

def test_constraint_check():
    """constraint_check.py validates a directory without crashing."""
    config_path = make_mock_config()
    try:
        code, stdout, stderr = run_tool("constraint_check.py", [
            "--config", config_path,
            "--worktree-path", TOOLS_DIR,
            "--baseline-path", TOOLS_DIR,
        ])
        result = json.loads(stdout)
        assert "all_pass" in result
        assert "constraints" in result
        assert "growth" in result["constraints"]
        assert "entry_point" in result["constraints"]
        assert "tests" in result["constraints"]
    finally:
        os.unlink(config_path)


# ─── Test: mine_sessions.py (no sessions = graceful exit) ───

def test_mine_sessions_no_data():
    """mine_sessions.py exits gracefully when no session files exist."""
    code, stdout, stderr = run_tool("mine_sessions.py", [
        "--agent-description", "test agent",
        "--output", os.path.join(tempfile.gettempdir(), "mine_test.json"),
        "--max-examples", "5",
    ])
    assert code == 0  # graceful exit, not crash


# ─── Test: read_results.py --format summary with mock ───

def test_read_results_format_summary():
    """read_results.py format_summary produces compact output."""
    # We can't call read_results without LangSmith, but we can test format_summary directly
    sys.path.insert(0, TOOLS_DIR)
    try:
        from read_results import format_summary
        mock_result = {
            "experiment": "test-exp",
            "combined_score": 0.5,
            "num_examples": 10,
            "total_tokens": 5000,
            "avg_latency_ms": 400,
            "error_count": 1,
            "error_rate": 0.1,
            "per_example": {
                "ex1": {
                    "score": 0.5, "scores": {"correctness": 0.0, "has_output": 1.0},
                    "feedback": {"correctness": "Failed to answer"},
                    "tokens": 500, "latency_ms": 400,
                    "error": None,
                    "input_preview": "What is Python?",
                    "output_preview": "I cannot access the file",
                },
                "ex2": {
                    "score": 1.0, "scores": {"correctness": 1.0, "has_output": 1.0},
                    "feedback": {}, "tokens": 500, "latency_ms": 400,
                    "error": None, "input_preview": "Hello", "output_preview": "Hi there",
                },
            },
        }
        summary = format_summary(mock_result)
        assert summary["combined_score"] == 0.5
        assert summary["num_examples"] == 10
        assert "correctness" in summary["per_evaluator"]
        assert len(summary["top_failing"]) == 1
        assert summary["top_failing"][0]["score"] == 0.5
        assert "scores" in summary["top_failing"][0]
        assert summary["top_failing"][0]["scores"]["correctness"] == 0.0
        assert "output" in summary["top_failing"][0]
    finally:
        sys.path.pop(0)


# ─── Test: weighted_score ───

def test_weighted_score():
    """weighted_score() computes correctly with and without weights."""
    sys.path.insert(0, TOOLS_DIR)
    try:
        from read_results import weighted_score

        # No weights = flat average
        assert weighted_score({"a": 0.8, "b": 0.2}) == 0.5

        # With weights
        result = weighted_score({"a": 0.8, "b": 0.2}, {"a": 0.7, "b": 0.3})
        expected = (0.8 * 0.7 + 0.2 * 0.3) / (0.7 + 0.3)
        assert abs(result - expected) < 0.001

        # Empty scores
        assert weighted_score({}) == 0.0
        assert weighted_score({}, {"a": 1.0}) == 0.0
    finally:
        sys.path.pop(0)


# ─── Test: pareto_front ───

def test_pareto_front():
    """pareto_front() identifies non-dominated candidates."""
    sys.path.insert(0, TOOLS_DIR)
    try:
        from read_results import pareto_front

        candidates = [
            {"experiment": "A", "evaluator_scores": {"correctness": 0.9, "latency": 0.3}},
            {"experiment": "B", "evaluator_scores": {"correctness": 0.7, "latency": 0.8}},
            {"experiment": "C", "evaluator_scores": {"correctness": 0.5, "latency": 0.5}},
        ]
        front = pareto_front(candidates)
        names = [c["experiment"] for c in front]
        # A dominates C (0.9>0.5, but 0.3<0.5 — actually A does NOT dominate C on latency)
        # B dominates C (0.7>0.5, 0.8>0.5)
        # A and B are non-dominated (A better correctness, B better latency)
        assert "A" in names
        assert "B" in names
        assert "C" not in names  # dominated by B
    finally:
        sys.path.pop(0)


# ─── Test: archive.py ───

def test_archive():
    """archive.py creates and lists archive entries."""
    config_path = make_mock_config()
    try:
        code, stdout, stderr = run_tool("archive.py", [
            "--config", config_path,
            "--version", "test-v001",
            "--experiment", "test-exp",
            "--score", "0.75",
            "--approach", "test approach",
            "--won",
        ])
        assert code == 0, f"exit {code}: {stderr[:200]}"
        result = json.loads(stdout)
        assert "archived" in result

        # List
        code2, stdout2, stderr2 = run_tool("archive.py", ["--config", config_path, "--list"])
        assert code2 == 0
        entries = json.loads(stdout2)
        assert len(entries) == 1
        assert entries[0]["version"] == "test-v001"
        assert entries[0]["won"] is True
    finally:
        os.unlink(config_path)
        import shutil
        archive_dir = os.path.join(os.path.dirname(config_path), "evolution_archive")
        if os.path.isdir(archive_dir):
            shutil.rmtree(archive_dir)


# ─── Runner ───

if __name__ == "__main__":
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        # Run without pytest
        import traceback
        tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
        passed = failed = 0
        for test_fn in tests:
            name = test_fn.__name__
            try:
                test_fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
                traceback.print_exc()
                failed += 1
        print(f"\n{passed} passed, {failed} failed")
        sys.exit(1 if failed else 0)
