"""Tests for test_growth.py — generates regression tasks from score improvements."""

import json
import os
import subprocess
import tempfile
import unittest

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
TEST_GROWTH_PY = os.path.join(TOOLS_DIR, "test_growth.py")


def run_growth(*args):
    result = subprocess.run(
        ["python3", TEST_GROWTH_PY] + list(args),
        capture_output=True, text=True,
    )
    return result


class TestTestGrowth(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tasks_dir = os.path.join(self.tmpdir, "tasks")
        self.output_dir = os.path.join(self.tmpdir, "output")
        os.makedirs(self.tasks_dir)
        os.makedirs(self.output_dir)

    def _write_scores(self, name, per_task):
        path = os.path.join(self.tmpdir, name)
        combined = sum(v["score"] for v in per_task.values()) / max(len(per_task), 1)
        with open(path, "w") as f:
            json.dump({"combined_score": combined, "per_task": per_task}, f)
        return path

    def _write_task(self, task_id, input_text="What is 2+2?", category="math"):
        path = os.path.join(self.tasks_dir, f"{task_id}.json")
        with open(path, "w") as f:
            json.dump({
                "id": task_id,
                "input": input_text,
                "metadata": {"category": category, "difficulty": "medium", "type": "standard"},
            }, f)
        return path

    def test_no_improvement_no_tasks(self):
        """When no tasks improved, no regression tasks should be generated."""
        prev = self._write_scores("prev.json", {
            "task_001": {"score": 0.8},
            "task_002": {"score": 0.7},
        })
        curr = self._write_scores("curr.json", {
            "task_001": {"score": 0.85},
            "task_002": {"score": 0.75},
        })
        r = run_growth(
            "--current-scores", curr,
            "--previous-scores", prev,
            "--tasks-dir", self.tasks_dir,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        # No regression files should exist
        files = [f for f in os.listdir(self.output_dir) if f.startswith("regression_")]
        self.assertEqual(len(files), 0)

    def test_significant_improvement_generates_tasks(self):
        """Tasks that go from <0.5 to >0.8 should generate regressions."""
        self._write_task("task_001", "What is the capital of France?", "geography")
        self._write_task("task_002", "Explain photosynthesis", "biology")

        prev = self._write_scores("prev.json", {
            "task_001": {"score": 0.2},  # Was failing
            "task_002": {"score": 0.9},  # Already passing
        })
        curr = self._write_scores("curr.json", {
            "task_001": {"score": 0.9},  # Now passing — FIXED!
            "task_002": {"score": 0.9},  # Still passing
        })
        r = run_growth(
            "--current-scores", curr,
            "--previous-scores", prev,
            "--tasks-dir", self.tasks_dir,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.startswith("regression_")]
        self.assertTrue(len(files) >= 1, f"Expected regression tasks, got: {files}")

        # Check regression task format
        with open(os.path.join(self.output_dir, files[0])) as f:
            task = json.load(f)
        self.assertIn("id", task)
        self.assertIn("input", task)
        self.assertEqual(task["metadata"]["source"], "regression")
        self.assertEqual(task["metadata"]["regression_for"], "task_001")
        self.assertEqual(task["metadata"]["type"], "regression")

    def test_max_total_tasks_cap(self):
        """Should not exceed max-total-tasks."""
        # Pre-fill output dir with some tasks
        for i in range(55):
            path = os.path.join(self.output_dir, f"existing_{i:03d}.json")
            with open(path, "w") as f:
                json.dump({"id": f"existing_{i:03d}", "input": "test"}, f)

        self._write_task("task_001", "Test question")
        prev = self._write_scores("prev.json", {"task_001": {"score": 0.1}})
        curr = self._write_scores("curr.json", {"task_001": {"score": 0.95}})

        r = run_growth(
            "--current-scores", curr,
            "--previous-scores", prev,
            "--tasks-dir", self.tasks_dir,
            "--output-dir", self.output_dir,
            "--max-total-tasks", "60",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        total = len(os.listdir(self.output_dir))
        self.assertLessEqual(total, 60)

    def test_at_capacity_skips(self):
        """When already at capacity, should skip entirely."""
        for i in range(60):
            path = os.path.join(self.output_dir, f"existing_{i:03d}.json")
            with open(path, "w") as f:
                json.dump({"id": f"existing_{i:03d}", "input": "test"}, f)

        self._write_task("task_001", "Test question")
        prev = self._write_scores("prev.json", {"task_001": {"score": 0.1}})
        curr = self._write_scores("curr.json", {"task_001": {"score": 0.95}})

        r = run_growth(
            "--current-scores", curr,
            "--previous-scores", prev,
            "--tasks-dir", self.tasks_dir,
            "--output-dir", self.output_dir,
            "--max-total-tasks", "60",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("capacity", r.stdout)

    def test_regression_metadata_preserved(self):
        """Regression tasks should preserve original category and add regression metadata."""
        self._write_task("task_001", "Calculate the integral of x^2", "calculus")
        prev = self._write_scores("prev.json", {"task_001": {"score": 0.3}})
        curr = self._write_scores("curr.json", {"task_001": {"score": 0.9}})

        r = run_growth(
            "--current-scores", curr,
            "--previous-scores", prev,
            "--tasks-dir", self.tasks_dir,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.startswith("regression_")]
        self.assertTrue(len(files) >= 1)
        with open(os.path.join(self.output_dir, files[0])) as f:
            task = json.load(f)
        self.assertEqual(task["metadata"]["category"], "calculus")
        self.assertAlmostEqual(task["metadata"]["previous_score"], 0.3)
        self.assertAlmostEqual(task["metadata"]["fixed_at_score"], 0.9)

    def test_missing_scores_files(self):
        """Should handle missing score files gracefully."""
        r = run_growth(
            "--current-scores", "/nonexistent/curr.json",
            "--previous-scores", "/nonexistent/prev.json",
            "--tasks-dir", self.tasks_dir,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Missing", r.stdout)

    def test_multiple_fixed_tasks(self):
        """Multiple fixed tasks should each generate regressions."""
        self._write_task("task_001", "Question one about math", "math")
        self._write_task("task_002", "Question two about science", "science")
        self._write_task("task_003", "Question three about history", "history")

        prev = self._write_scores("prev.json", {
            "task_001": {"score": 0.1},
            "task_002": {"score": 0.2},
            "task_003": {"score": 0.8},
        })
        curr = self._write_scores("curr.json", {
            "task_001": {"score": 0.85},
            "task_002": {"score": 0.9},
            "task_003": {"score": 0.85},
        })
        r = run_growth(
            "--current-scores", curr,
            "--previous-scores", prev,
            "--tasks-dir", self.tasks_dir,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.startswith("regression_")]
        # At least 2 regressions per fixed task (2 fixed tasks), so >= 4
        self.assertGreaterEqual(len(files), 4)

    def test_regression_ids_increment(self):
        """Regression IDs should not collide with existing ones."""
        # Pre-create regression_001 and regression_002
        for i in [1, 2]:
            path = os.path.join(self.output_dir, f"regression_{i:03d}.json")
            with open(path, "w") as f:
                json.dump({"id": f"regression_{i:03d}", "input": "old"}, f)

        self._write_task("task_001", "New question")
        prev = self._write_scores("prev.json", {"task_001": {"score": 0.1}})
        curr = self._write_scores("curr.json", {"task_001": {"score": 0.9}})

        r = run_growth(
            "--current-scores", curr,
            "--previous-scores", prev,
            "--tasks-dir", self.tasks_dir,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = sorted(f for f in os.listdir(self.output_dir) if f.startswith("regression_"))
        # Should have regression_001, regression_002 (old) + regression_003+ (new)
        new_files = [f for f in files if f not in ["regression_001.json", "regression_002.json"]]
        self.assertTrue(len(new_files) >= 1)
        self.assertTrue(new_files[0].startswith("regression_003"))


if __name__ == "__main__":
    unittest.main()
