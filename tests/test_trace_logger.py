"""Tests for trace_logger.py — stdlib-only TraceLogger helper."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from trace_logger import TraceLogger


class TestTraceLogger(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_step_records_entry(self):
        tl = TraceLogger(self.tmpdir)
        tl.step("llm_call", {"prompt": "hello", "response": "world"})
        self.assertEqual(len(tl.steps), 1)
        self.assertEqual(tl.steps[0]["name"], "llm_call")
        self.assertEqual(tl.steps[0]["data"]["prompt"], "hello")
        self.assertIn("timestamp", tl.steps[0])

    def test_save_writes_json(self):
        tl = TraceLogger(self.tmpdir)
        tl.step("step_a", {"key": "val"})
        tl.step("step_b")
        tl.save()
        path = os.path.join(self.tmpdir, "trace.json")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "step_a")
        self.assertEqual(data[1]["name"], "step_b")
        self.assertEqual(data[1]["data"], {})

    def test_save_noop_when_no_dir(self):
        tl = TraceLogger(None)
        tl.step("ignored")
        tl.save()  # should not raise

    def test_creates_dir_if_missing(self):
        nested = os.path.join(self.tmpdir, "a", "b", "c")
        tl = TraceLogger(nested)
        tl.step("x")
        tl.save()
        self.assertTrue(os.path.exists(os.path.join(nested, "trace.json")))

    def test_steps_returns_copy(self):
        tl = TraceLogger(self.tmpdir)
        tl.step("a")
        steps = tl.steps
        steps.append({"fake": True})
        self.assertEqual(len(tl.steps), 1)


if __name__ == "__main__":
    unittest.main()
