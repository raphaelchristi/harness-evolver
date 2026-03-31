"""Integration test: init → evaluate → state update — full pipeline with mock classifier."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
EXAMPLE_DIR = os.path.join(REPO_ROOT, "examples", "classifier")


class TestFullPipeline(unittest.TestCase):
    def setUp(self):
        self.project_dir = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.project_dir, ".harness-evolver")

    def _run(self, *cmd):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, f"Command failed: {' '.join(cmd)}\nstderr: {r.stderr}")
        return r

    def test_init_evaluate_update_cycle(self):
        """Simulates one full cycle: init, create v001, evaluate, update state."""

        # 1. Init
        self._run(
            "python3", os.path.join(TOOLS_DIR, "init.py"),
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )

        # Verify init created everything
        summary = json.load(open(os.path.join(self.base_dir, "summary.json")))
        self.assertEqual(summary["iterations"], 0)
        baseline_score = summary["best"]["combined_score"]
        self.assertGreater(baseline_score, 0.0)

        # 2. Create v001 directory (simulating what proposer would do)
        v001_dir = os.path.join(self.base_dir, "harnesses", "v001")
        os.makedirs(v001_dir, exist_ok=True)
        shutil.copy2(
            os.path.join(self.base_dir, "baseline", "harness.py"),
            os.path.join(v001_dir, "harness.py"),
        )
        shutil.copy2(
            os.path.join(self.base_dir, "baseline", "config.json"),
            os.path.join(v001_dir, "config.json"),
        )
        with open(os.path.join(v001_dir, "proposal.md"), "w") as f:
            f.write("Based on baseline\n\nCopy of baseline for testing.")

        # 3. Evaluate v001
        traces_dir = os.path.join(v001_dir, "traces")
        scores_path = os.path.join(v001_dir, "scores.json")
        self._run(
            "python3", os.path.join(TOOLS_DIR, "evaluate.py"), "run",
            "--harness", os.path.join(v001_dir, "harness.py"),
            "--config", os.path.join(v001_dir, "config.json"),
            "--tasks-dir", os.path.join(self.base_dir, "eval", "tasks"),
            "--eval", os.path.join(self.base_dir, "eval", "eval.py"),
            "--traces-dir", traces_dir,
            "--scores", scores_path,
            "--timeout", "30",
        )

        scores = json.load(open(scores_path))
        self.assertIn("combined_score", scores)

        # 4. Update state
        self._run(
            "python3", os.path.join(TOOLS_DIR, "state.py"), "update",
            "--base-dir", self.base_dir,
            "--version", "v001",
            "--scores", scores_path,
            "--proposal", os.path.join(v001_dir, "proposal.md"),
        )

        summary = json.load(open(os.path.join(self.base_dir, "summary.json")))
        self.assertEqual(summary["iterations"], 1)
        self.assertEqual(len(summary["history"]), 2)

        history = open(os.path.join(self.base_dir, "PROPOSER_HISTORY.md")).read()
        self.assertIn("v001", history)

        state_md = open(os.path.join(self.base_dir, "STATE.md")).read()
        self.assertIn("v001", state_md)

        self.assertTrue(os.path.exists(os.path.join(traces_dir, "timing.json")))
        self.assertTrue(os.path.exists(os.path.join(traces_dir, "stdout.log")))

        # 5. Show status
        r = self._run(
            "python3", os.path.join(TOOLS_DIR, "state.py"), "show",
            "--base-dir", self.base_dir,
        )
        self.assertIn("v001", r.stdout)


if __name__ == "__main__":
    unittest.main()
