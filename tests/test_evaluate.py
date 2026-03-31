"""Tests for evaluate.py — evaluation orchestrator."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
EVALUATE_PY = os.path.join(TOOLS_DIR, "evaluate.py")
EXAMPLE_DIR = os.path.join(REPO_ROOT, "examples", "classifier")


def run_evaluate(*args):
    result = subprocess.run(
        ["python3", EVALUATE_PY] + list(args),
        capture_output=True, text=True, timeout=120,
    )
    return result


class TestValidate(unittest.TestCase):
    def test_validate_passes_for_valid_harness(self):
        r = run_evaluate(
            "validate",
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--config", os.path.join(EXAMPLE_DIR, "config.json"),
        )
        self.assertEqual(r.returncode, 0, f"stdout: {r.stdout}\nstderr: {r.stderr}")

    def test_validate_fails_for_missing_harness(self):
        r = run_evaluate("validate", "--harness", "/nonexistent/harness.py")
        self.assertNotEqual(r.returncode, 0)

    def test_validate_fails_for_broken_harness(self):
        tmpdir = tempfile.mkdtemp()
        broken = os.path.join(tmpdir, "broken.py")
        with open(broken, "w") as f:
            f.write("import sys; sys.exit(1)\n")
        r = run_evaluate("validate", "--harness", broken)
        self.assertNotEqual(r.returncode, 0)


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.traces_dir = os.path.join(self.tmpdir, "traces")
        self.scores_path = os.path.join(self.tmpdir, "scores.json")

    def test_run_produces_scores(self):
        r = run_evaluate(
            "run",
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tasks-dir", os.path.join(EXAMPLE_DIR, "tasks"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--traces-dir", self.traces_dir,
            "--scores", self.scores_path,
            "--timeout", "30",
        )
        self.assertEqual(r.returncode, 0, f"stdout: {r.stdout}\nstderr: {r.stderr}")
        self.assertTrue(os.path.exists(self.scores_path))
        scores = json.load(open(self.scores_path))
        self.assertIn("combined_score", scores)
        self.assertIn("per_task", scores)
        self.assertGreater(scores["combined_score"], 0.0)

    def test_run_creates_per_task_traces(self):
        run_evaluate(
            "run",
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tasks-dir", os.path.join(EXAMPLE_DIR, "tasks"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--traces-dir", self.traces_dir,
            "--scores", self.scores_path,
            "--timeout", "30",
        )
        self.assertTrue(os.path.exists(os.path.join(self.traces_dir, "stdout.log")))
        self.assertTrue(os.path.exists(os.path.join(self.traces_dir, "stderr.log")))
        self.assertTrue(os.path.exists(os.path.join(self.traces_dir, "timing.json")))
        task_trace_dir = os.path.join(self.traces_dir, "task_001")
        self.assertTrue(os.path.isdir(task_trace_dir))
        self.assertTrue(os.path.exists(os.path.join(task_trace_dir, "input.json")))
        self.assertTrue(os.path.exists(os.path.join(task_trace_dir, "output.json")))

    def test_run_handles_harness_crash(self):
        broken = os.path.join(self.tmpdir, "broken.py")
        with open(broken, "w") as f:
            f.write("import sys; sys.exit(1)\n")
        r = run_evaluate(
            "run",
            "--harness", broken,
            "--tasks-dir", os.path.join(EXAMPLE_DIR, "tasks"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--traces-dir", self.traces_dir,
            "--scores", self.scores_path,
            "--timeout", "30",
        )
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        scores = json.load(open(self.scores_path))
        self.assertEqual(scores["combined_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
