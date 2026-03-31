"""Tests for LangSmith detection in init.py."""

import json
import os
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
EXAMPLE_DIR = os.path.join(REPO_ROOT, "examples", "classifier")


class TestLangSmithDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.tmpdir, ".harness-evolver")

    def _run_init(self, env):
        return subprocess.run(
            ["python3", os.path.join(TOOLS_DIR, "init.py"),
             "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
             "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
             "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
             "--base-dir", self.base_dir,
             "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
             "--tools-dir", TOOLS_DIR],
            capture_output=True, text=True, timeout=120, env=env,
        )

    def test_init_detects_langsmith_api_key(self):
        env = {**os.environ, "LANGSMITH_API_KEY": "lsv2_fake_key"}
        r = self._run_init(env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.base_dir, "config.json")) as f:
            config = json.load(f)
        self.assertTrue(config["eval"]["langsmith"]["enabled"])
        self.assertEqual(config["eval"]["langsmith"]["project_prefix"], "harness-evolver")

    def test_init_no_langsmith_without_key(self):
        env = {k: v for k, v in os.environ.items() if k != "LANGSMITH_API_KEY"}
        r = self._run_init(env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.base_dir, "config.json")) as f:
            config = json.load(f)
        self.assertFalse(config["eval"]["langsmith"]["enabled"])


if __name__ == "__main__":
    unittest.main()
