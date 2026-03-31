"""Tests for import_traces.py — converts LangSmith traces to eval tasks."""

import json
import os
import subprocess
import tempfile
import unittest

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
IMPORT_TRACES_PY = os.path.join(TOOLS_DIR, "import_traces.py")


def run_import(*args):
    result = subprocess.run(
        ["python3", IMPORT_TRACES_PY] + list(args),
        capture_output=True, text=True,
    )
    return result


class TestImportTraces(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.tmpdir, "tasks")
        os.makedirs(self.output_dir)

    def _write_traces(self, traces):
        path = os.path.join(self.tmpdir, "traces.json")
        with open(path, "w") as f:
            json.dump(traces, f)
        return path

    def test_basic_import(self):
        traces = [
            {
                "id": "run_abc123",
                "name": "ChatAgent",
                "inputs": {"input": "What is Python?"},
                "outputs": {"output": "Python is a programming language"},
                "error": None,
                "feedback_stats": None,
                "total_tokens": 150,
            },
        ]
        traces_path = self._write_traces(traces)
        r = run_import(
            "--traces-json", traces_path,
            "--output-dir", self.output_dir,
            "--prefix", "imported",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.endswith(".json")]
        self.assertEqual(len(files), 1)

        with open(os.path.join(self.output_dir, files[0])) as f:
            task = json.load(f)
        self.assertEqual(task["input"], "What is Python?")
        self.assertEqual(task["metadata"]["source"], "imported")
        self.assertEqual(task["metadata"]["type"], "production")
        self.assertEqual(task["metadata"]["langsmith_run_id"], "run_abc123")

    def test_langchain_messages_format(self):
        """Should extract input from LangChain message format."""
        traces = [
            {
                "id": "run_msg123",
                "name": "ChatModel",
                "inputs": {
                    "messages": [[
                        {"type": "system", "content": "You are a helpful assistant"},
                        {"type": "human", "content": "Explain quantum computing"},
                    ]]
                },
                "outputs": {"output": "Quantum computing uses..."},
                "error": None,
                "feedback_stats": None,
            },
        ]
        traces_path = self._write_traces(traces)
        r = run_import(
            "--traces-json", traces_path,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.output_dir, files[0])) as f:
            task = json.load(f)
        self.assertEqual(task["input"], "Explain quantum computing")

    def test_negative_feedback_prioritized(self):
        """Traces with negative feedback should be imported first."""
        traces = [
            {
                "id": "run_good",
                "name": "Agent",
                "inputs": {"input": "Good question"},
                "outputs": {},
                "error": None,
                "feedback_stats": {"thumbs_up": 1, "thumbs_down": 0},
            },
            {
                "id": "run_bad",
                "name": "Agent",
                "inputs": {"input": "Bad response question"},
                "outputs": {},
                "error": None,
                "feedback_stats": {"thumbs_up": 0, "thumbs_down": 1},
            },
        ]
        traces_path = self._write_traces(traces)
        r = run_import(
            "--traces-json", traces_path,
            "--output-dir", self.output_dir,
            "--max-tasks", "1",  # Only import 1
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.output_dir, files[0])) as f:
            task = json.load(f)
        # Should have picked the negative feedback trace
        self.assertEqual(task["input"], "Bad response question")
        self.assertEqual(task["metadata"]["user_feedback"], "negative")

    def test_max_tasks_limit(self):
        traces = [
            {"id": f"run_{i}", "name": "Agent", "inputs": {"input": f"Question {i}"}, "outputs": {}, "error": None, "feedback_stats": None}
            for i in range(10)
        ]
        traces_path = self._write_traces(traces)
        r = run_import(
            "--traces-json", traces_path,
            "--output-dir", self.output_dir,
            "--max-tasks", "3",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.endswith(".json")]
        self.assertEqual(len(files), 3)

    def test_skip_no_input(self):
        """Traces with no extractable input should be skipped."""
        traces = [
            {"id": "run_empty", "name": "Agent", "inputs": {}, "outputs": {}, "error": None, "feedback_stats": None},
            {"id": "run_good", "name": "Agent", "inputs": {"input": "Valid question"}, "outputs": {}, "error": None, "feedback_stats": None},
        ]
        traces_path = self._write_traces(traces)
        r = run_import(
            "--traces-json", traces_path,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.endswith(".json")]
        self.assertEqual(len(files), 1)
        self.assertIn("skipped", r.stdout.lower())

    def test_skip_duplicates(self):
        """Already-imported traces should be skipped."""
        # Pre-create an imported task
        existing = {
            "id": "imported_existing",
            "input": "Old question",
            "metadata": {"source": "imported", "langsmith_run_id": "run_dup123"},
        }
        with open(os.path.join(self.output_dir, "imported_existing.json"), "w") as f:
            json.dump(existing, f)

        traces = [
            {"id": "run_dup123", "name": "Agent", "inputs": {"input": "Old question"}, "outputs": {}, "error": None, "feedback_stats": None},
            {"id": "run_new456", "name": "Agent", "inputs": {"input": "New question"}, "outputs": {}, "error": None, "feedback_stats": None},
        ]
        traces_path = self._write_traces(traces)
        r = run_import(
            "--traces-json", traces_path,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        # Should only add the new one
        files = [f for f in os.listdir(self.output_dir) if f.endswith(".json")]
        self.assertEqual(len(files), 2)  # 1 existing + 1 new

    def test_difficulty_inference(self):
        """Should infer difficulty from input characteristics."""
        traces = [
            {"id": "run_easy", "name": "Agent", "inputs": {"input": "Hi"}, "outputs": {}, "error": None, "feedback_stats": None},
            {"id": "run_hard", "name": "Agent", "inputs": {"input": "Please analyze the following complex scenario involving multiple interacting systems. " * 10}, "outputs": {}, "error": None, "feedback_stats": None},
        ]
        traces_path = self._write_traces(traces)
        r = run_import(
            "--traces-json", traces_path,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = sorted(os.listdir(self.output_dir))
        tasks = []
        for f in files:
            if f.endswith(".json"):
                with open(os.path.join(self.output_dir, f)) as fh:
                    tasks.append(json.load(fh))
        difficulties = {t["metadata"]["difficulty"] for t in tasks}
        # Should have at least two different difficulties
        self.assertTrue(len(difficulties) >= 1)

    def test_error_traces_flagged(self):
        """Traces with errors should have had_error: true."""
        traces = [
            {"id": "run_err", "name": "Agent", "inputs": {"input": "Question that errors"}, "outputs": {}, "error": "ValueError: something broke", "feedback_stats": None},
        ]
        traces_path = self._write_traces(traces)
        r = run_import(
            "--traces-json", traces_path,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.output_dir, files[0])) as f:
            task = json.load(f)
        self.assertTrue(task["metadata"]["had_error"])

    def test_empty_traces_json(self):
        """Should handle empty traces gracefully."""
        traces_path = self._write_traces([])
        r = run_import(
            "--traces-json", traces_path,
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        files = [f for f in os.listdir(self.output_dir) if f.endswith(".json")]
        self.assertEqual(len(files), 0)

    def test_missing_file(self):
        """Should handle missing traces file gracefully."""
        r = run_import(
            "--traces-json", "/nonexistent/traces.json",
            "--output-dir", self.output_dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("No traces", r.stdout)


if __name__ == "__main__":
    unittest.main()
