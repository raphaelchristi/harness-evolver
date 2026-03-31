"""Tests for init.py — project initialization."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
INIT_PY = os.path.join(TOOLS_DIR, "init.py")
EXAMPLE_DIR = os.path.join(REPO_ROOT, "examples", "classifier")


def run_init(*args):
    result = subprocess.run(
        ["python3", INIT_PY] + list(args),
        capture_output=True, text=True, timeout=120,
    )
    return result


class TestInit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.tmpdir, ".harness-evolver")

    def test_init_creates_structure(self):
        r = run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        self.assertEqual(r.returncode, 0, f"stdout: {r.stdout}\nstderr: {r.stderr}")
        self.assertTrue(os.path.isdir(os.path.join(self.base_dir, "baseline")))
        self.assertTrue(os.path.isdir(os.path.join(self.base_dir, "eval", "tasks")))
        self.assertTrue(os.path.isdir(os.path.join(self.base_dir, "harnesses")))

    def test_init_copies_baseline(self):
        run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        self.assertTrue(os.path.exists(os.path.join(self.base_dir, "baseline", "harness.py")))
        self.assertTrue(os.path.exists(os.path.join(self.base_dir, "baseline", "config.json")))

    def test_init_copies_eval_and_tasks(self):
        run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        self.assertTrue(os.path.exists(os.path.join(self.base_dir, "eval", "eval.py")))
        tasks = os.listdir(os.path.join(self.base_dir, "eval", "tasks"))
        self.assertGreater(len(tasks), 0)

    def test_init_creates_config_json(self):
        run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        config_path = os.path.join(self.base_dir, "config.json")
        self.assertTrue(os.path.exists(config_path))
        config = json.load(open(config_path))
        self.assertIn("harness", config)
        self.assertIn("eval", config)
        self.assertIn("evolution", config)

    def test_init_creates_summary_with_baseline_score(self):
        run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        summary_path = os.path.join(self.base_dir, "summary.json")
        self.assertTrue(os.path.exists(summary_path))
        summary = json.load(open(summary_path))
        self.assertEqual(summary["best"]["version"], "baseline")
        self.assertGreater(summary["best"]["combined_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
