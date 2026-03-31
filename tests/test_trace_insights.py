"""Tests for trace_insights.py — clusters LangSmith traces and generates insights."""

import json
import os
import subprocess
import tempfile
import unittest

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
TRACE_INSIGHTS_PY = os.path.join(TOOLS_DIR, "trace_insights.py")


def run_insights(*args):
    result = subprocess.run(
        ["python3", TRACE_INSIGHTS_PY] + list(args),
        capture_output=True, text=True,
    )
    return result


class TestTraceInsightsBasic(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output = os.path.join(self.tmpdir, "trace_insights.json")
        self.tasks_dir = os.path.join(self.tmpdir, "tasks")
        os.makedirs(self.tasks_dir)

    def _write_json(self, name, data):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def _write_task(self, task_id, category="general", difficulty="medium"):
        path = os.path.join(self.tasks_dir, f"{task_id}.json")
        with open(path, "w") as f:
            json.dump({
                "id": task_id,
                "input": f"Test input for {task_id}",
                "metadata": {"category": category, "difficulty": difficulty, "type": "standard"},
            }, f)
        return path

    def test_no_data_produces_empty_insights(self):
        runs_path = self._write_json("runs.json", [])
        scores_path = self._write_json("scores.json", {"combined_score": 0, "per_task": {}})
        r = run_insights(
            "--langsmith-runs", runs_path,
            "--scores", scores_path,
            "--tasks-dir", self.tasks_dir,
            "--output", self.output,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.output) as f:
            data = json.load(f)
        self.assertIn("generated_at", data)
        self.assertEqual(data["error_clusters"], [])

    def test_error_clustering(self):
        runs = [
            {"name": "run1", "tokens": 100, "error": "TimeoutError: connection timed out", "llm_response": ""},
            {"name": "run2", "tokens": 200, "error": "TimeoutError: connection timed out", "llm_response": "ok"},
            {"name": "run3", "tokens": 300, "error": "ValueError: invalid JSON", "llm_response": "ok"},
            {"name": "run4", "tokens": 150, "error": None, "llm_response": "good response"},
        ]
        runs_path = self._write_json("runs.json", runs)
        scores_path = self._write_json("scores.json", {"combined_score": 0.5, "per_task": {}})
        r = run_insights(
            "--langsmith-runs", runs_path,
            "--scores", scores_path,
            "--tasks-dir", self.tasks_dir,
            "--output", self.output,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.output) as f:
            data = json.load(f)
        # Should have 2 error clusters: TimeoutError (2) and ValueError (1)
        self.assertEqual(len(data["error_clusters"]), 2)
        self.assertEqual(data["error_clusters"][0]["count"], 2)  # Timeout is most common
        self.assertIn("TimeoutError", data["error_clusters"][0]["pattern"])

    def test_token_analysis_buckets(self):
        runs = [
            {"name": "r1", "tokens": 100, "error": None, "llm_response": "short"},
            {"name": "r2", "tokens": 400, "error": None, "llm_response": "short"},
            {"name": "r3", "tokens": 1000, "error": None, "llm_response": "medium resp"},
            {"name": "r4", "tokens": 1500, "error": None, "llm_response": "medium resp"},
            {"name": "r5", "tokens": 3000, "error": None, "llm_response": "long " * 200},
        ]
        runs_path = self._write_json("runs.json", runs)
        scores_path = self._write_json("scores.json", {"combined_score": 0.7, "per_task": {}})
        r = run_insights(
            "--langsmith-runs", runs_path,
            "--scores", scores_path,
            "--tasks-dir", self.tasks_dir,
            "--output", self.output,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.output) as f:
            data = json.load(f)
        self.assertEqual(data["token_analysis"]["low"]["count"], 2)
        self.assertEqual(data["token_analysis"]["medium"]["count"], 2)
        self.assertEqual(data["token_analysis"]["high"]["count"], 1)

    def test_response_analysis_empty_detection(self):
        runs = [
            {"name": "r1", "tokens": 100, "error": None, "llm_response": ""},
            {"name": "r2", "tokens": 100, "error": None, "llm_response": ""},
            {"name": "r3", "tokens": 100, "error": None, "llm_response": "good response here"},
        ]
        runs_path = self._write_json("runs.json", runs)
        scores_path = self._write_json("scores.json", {"combined_score": 0.5, "per_task": {}})
        r = run_insights(
            "--langsmith-runs", runs_path,
            "--scores", scores_path,
            "--tasks-dir", self.tasks_dir,
            "--output", self.output,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.output) as f:
            data = json.load(f)
        self.assertEqual(data["response_analysis"]["empty"]["count"], 2)

    def test_score_cross_reference(self):
        self._write_task("task_001", "math")
        self._write_task("task_002", "math")
        self._write_task("task_003", "writing")
        runs_path = self._write_json("runs.json", [])
        scores_path = self._write_json("scores.json", {
            "combined_score": 0.5,
            "per_task": {
                "task_001": {"score": 0.2},
                "task_002": {"score": 0.3},
                "task_003": {"score": 0.9},
            },
        })
        r = run_insights(
            "--langsmith-runs", runs_path,
            "--scores", scores_path,
            "--tasks-dir", self.tasks_dir,
            "--output", self.output,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.output) as f:
            data = json.load(f)
        xref = data["score_cross_ref"]
        self.assertEqual(xref["failing_count"], 2)
        self.assertEqual(xref["passing_count"], 1)
        self.assertIn("math", xref["failure_categories"])
        self.assertEqual(len(xref["failure_categories"]["math"]), 2)

    def test_hypothesis_generation(self):
        runs = [
            {"name": "r1", "tokens": 100, "error": "TimeoutError", "llm_response": ""},
            {"name": "r2", "tokens": 100, "error": "TimeoutError", "llm_response": ""},
            {"name": "r3", "tokens": 100, "error": "TimeoutError", "llm_response": ""},
        ]
        self._write_task("task_001", "general")
        runs_path = self._write_json("runs.json", runs)
        scores_path = self._write_json("scores.json", {
            "combined_score": 0.3,
            "per_task": {"task_001": {"score": 0.3}},
        })
        r = run_insights(
            "--langsmith-runs", runs_path,
            "--scores", scores_path,
            "--tasks-dir", self.tasks_dir,
            "--output", self.output,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.output) as f:
            data = json.load(f)
        self.assertTrue(len(data["hypotheses"]) > 0)
        # Should mention errors
        self.assertTrue(any("error" in h.lower() or "timeout" in h.lower() for h in data["hypotheses"]))

    def test_top_issues_sorted_by_severity(self):
        runs = [
            {"name": "r1", "tokens": 100, "error": "Fatal error", "llm_response": ""},
            {"name": "r2", "tokens": 100, "error": "Fatal error", "llm_response": ""},
            {"name": "r3", "tokens": 100, "error": "Fatal error", "llm_response": ""},
        ]
        self._write_task("task_001", "math")
        self._write_task("task_002", "math")
        self._write_task("task_003", "math")
        runs_path = self._write_json("runs.json", runs)
        scores_path = self._write_json("scores.json", {
            "combined_score": 0.2,
            "per_task": {
                "task_001": {"score": 0.1},
                "task_002": {"score": 0.2},
                "task_003": {"score": 0.3},
            },
        })
        r = run_insights(
            "--langsmith-runs", runs_path,
            "--scores", scores_path,
            "--tasks-dir", self.tasks_dir,
            "--output", self.output,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.output) as f:
            data = json.load(f)
        self.assertTrue(len(data["top_issues"]) > 0)
        # First issue should be high severity
        self.assertEqual(data["top_issues"][0]["severity"], "high")

    def test_missing_files_graceful(self):
        """Should handle missing langsmith files gracefully."""
        scores_path = self._write_json("scores.json", {
            "combined_score": 0.5,
            "per_task": {"task_001": {"score": 0.5}},
        })
        r = run_insights(
            "--langsmith-runs", "/nonexistent/runs.json",
            "--scores", scores_path,
            "--tasks-dir", self.tasks_dir,
            "--output", self.output,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.output) as f:
            data = json.load(f)
        self.assertIn("generated_at", data)


if __name__ == "__main__":
    unittest.main()
