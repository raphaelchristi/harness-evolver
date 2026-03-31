"""Tests for state.py — manages summary.json, STATE.md, PROPOSER_HISTORY.md."""

import json
import os
import sys
import subprocess
import tempfile
import unittest

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
STATE_PY = os.path.join(TOOLS_DIR, "state.py")


def run_state(*args):
    result = subprocess.run(
        ["python3", STATE_PY] + list(args),
        capture_output=True, text=True,
    )
    return result


class TestStateInit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_init_creates_files(self):
        r = run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "summary.json")))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "STATE.md")))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "PROPOSER_HISTORY.md")))

    def test_init_summary_json_content(self):
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        self.assertEqual(data["iterations"], 0)
        self.assertEqual(data["best"]["version"], "baseline")
        self.assertAlmostEqual(data["best"]["combined_score"], 0.50)
        self.assertEqual(len(data["history"]), 1)
        self.assertIsNone(data["history"][0]["parent"])

    def test_init_state_md_contains_baseline(self):
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        with open(os.path.join(self.tmpdir, "STATE.md")) as f:
            content = f.read()
        self.assertIn("baseline", content)
        self.assertIn("0.50", content)

    def test_init_proposer_history_is_empty_with_header(self):
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        with open(os.path.join(self.tmpdir, "PROPOSER_HISTORY.md")) as f:
            content = f.read()
        self.assertIn("Proposer History", content)


class TestStateUpdate(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        self.scores_path = os.path.join(self.tmpdir, "test_scores.json")
        with open(self.scores_path, "w") as f:
            json.dump({"combined_score": 0.72, "accuracy": 0.72}, f)
        self.proposal_path = os.path.join(self.tmpdir, "test_proposal.md")
        with open(self.proposal_path, "w") as f:
            f.write("Based on baseline\n\nAdded few-shot examples to improve accuracy.")

    def test_update_increments_iteration(self):
        run_state("update", "--base-dir", self.tmpdir, "--version", "v001",
                  "--scores", self.scores_path, "--proposal", self.proposal_path)
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        self.assertEqual(data["iterations"], 1)

    def test_update_sets_best(self):
        run_state("update", "--base-dir", self.tmpdir, "--version", "v001",
                  "--scores", self.scores_path, "--proposal", self.proposal_path)
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        self.assertEqual(data["best"]["version"], "v001")
        self.assertAlmostEqual(data["best"]["combined_score"], 0.72)

    def test_update_detects_parent_from_proposal(self):
        run_state("update", "--base-dir", self.tmpdir, "--version", "v001",
                  "--scores", self.scores_path, "--proposal", self.proposal_path)
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        entry = [h for h in data["history"] if h["version"] == "v001"][0]
        self.assertEqual(entry["parent"], "baseline")

    def test_update_fallback_parent_to_best(self):
        with open(self.proposal_path, "w") as f:
            f.write("Improved the prompt template.")
        run_state("update", "--base-dir", self.tmpdir, "--version", "v001",
                  "--scores", self.scores_path, "--proposal", self.proposal_path)
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        entry = [h for h in data["history"] if h["version"] == "v001"][0]
        self.assertEqual(entry["parent"], "baseline")

    def test_update_appends_proposer_history(self):
        run_state("update", "--base-dir", self.tmpdir, "--version", "v001",
                  "--scores", self.scores_path, "--proposal", self.proposal_path)
        with open(os.path.join(self.tmpdir, "PROPOSER_HISTORY.md")) as f:
            content = f.read()
        self.assertIn("v001", content)
        self.assertIn("0.72", content)

    def test_update_marks_regression(self):
        run_state("update", "--base-dir", self.tmpdir, "--version", "v001",
                  "--scores", self.scores_path, "--proposal", self.proposal_path)
        bad_scores = os.path.join(self.tmpdir, "bad_scores.json")
        with open(bad_scores, "w") as f:
            json.dump({"combined_score": 0.30}, f)
        bad_proposal = os.path.join(self.tmpdir, "bad_proposal.md")
        with open(bad_proposal, "w") as f:
            f.write("Based on v001\n\nChanged prompt structure.")
        run_state("update", "--base-dir", self.tmpdir, "--version", "v002",
                  "--scores", bad_scores, "--proposal", bad_proposal)
        with open(os.path.join(self.tmpdir, "PROPOSER_HISTORY.md")) as f:
            content = f.read()
        self.assertIn("REGRESSION", content)


class TestStateShow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")

    def test_show_outputs_status(self):
        r = run_state("show", "--base-dir", self.tmpdir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("baseline", r.stdout)
        self.assertIn("0.50", r.stdout)


if __name__ == "__main__":
    unittest.main()
