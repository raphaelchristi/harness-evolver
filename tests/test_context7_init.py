"""Tests for Context7 stack detection in init.py."""

import json
import os
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")


class TestStackDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.tmpdir, ".harness-evolver")
        self.tasks_dir = os.path.join(self.tmpdir, "tasks")
        os.makedirs(self.tasks_dir)
        with open(os.path.join(self.tasks_dir, "task_001.json"), "w") as f:
            json.dump({"id": "t1", "input": "test", "expected": "test"}, f)

    def _write_harness(self, content):
        path = os.path.join(self.tmpdir, "harness.py")
        with open(path, "w") as f:
            f.write(content)
        return path

    def _write_eval(self):
        path = os.path.join(self.tmpdir, "eval.py")
        with open(path, "w") as f:
            f.write(
                'import argparse, json, os\n'
                'p = argparse.ArgumentParser()\n'
                'p.add_argument("--results-dir")\n'
                'p.add_argument("--tasks-dir")\n'
                'p.add_argument("--scores")\n'
                'a = p.parse_args()\n'
                'json.dump({"combined_score": 0.5, "per_task": {}}, open(a.scores, "w"))\n'
            )
        return path

    def test_init_detects_langchain_stack(self):
        harness = self._write_harness(
            'import argparse, json, os\n'
            'try:\n'
            '    import langchain\n'
            'except ImportError:\n'
            '    langchain = None\n'
            'try:\n'
            '    from langgraph.graph import StateGraph\n'
            'except ImportError:\n'
            '    StateGraph = None\n'
            'p = argparse.ArgumentParser()\n'
            'p.add_argument("--input", required=True)\n'
            'p.add_argument("--output", required=True)\n'
            'p.add_argument("--traces-dir")\n'
            'p.add_argument("--config")\n'
            'a = p.parse_args()\n'
            't = json.load(open(a.input))\n'
            'json.dump({"id": t["id"], "output": "test"}, open(a.output, "w"))\n'
        )
        eval_py = self._write_eval()
        r = subprocess.run(
            ["python3", os.path.join(TOOLS_DIR, "init.py"),
             "--harness", harness,
             "--eval", eval_py,
             "--tasks", self.tasks_dir,
             "--base-dir", self.base_dir,
             "--tools-dir", TOOLS_DIR],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        with open(os.path.join(self.base_dir, "config.json")) as f:
            config = json.load(f)
        self.assertIn("stack", config)
        self.assertIn("langchain", config["stack"]["detected"])
        self.assertIn("langgraph", config["stack"]["detected"])

    def test_init_empty_stack_for_stdlib_only(self):
        harness = self._write_harness(
            'import argparse, json, os\n'
            'p = argparse.ArgumentParser()\n'
            'p.add_argument("--input", required=True)\n'
            'p.add_argument("--output", required=True)\n'
            'p.add_argument("--traces-dir")\n'
            'p.add_argument("--config")\n'
            'a = p.parse_args()\n'
            't = json.load(open(a.input))\n'
            'json.dump({"id": t["id"], "output": "test"}, open(a.output, "w"))\n'
        )
        eval_py = self._write_eval()
        r = subprocess.run(
            ["python3", os.path.join(TOOLS_DIR, "init.py"),
             "--harness", harness,
             "--eval", eval_py,
             "--tasks", self.tasks_dir,
             "--base-dir", self.base_dir,
             "--tools-dir", TOOLS_DIR],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        with open(os.path.join(self.base_dir, "config.json")) as f:
            config = json.load(f)
        self.assertIn("stack", config)
        self.assertEqual(config["stack"]["detected"], {})


if __name__ == "__main__":
    unittest.main()
