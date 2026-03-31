"""Tests for langsmith_adapter.py — bridges evaluate.py with LangSmith."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from langsmith_adapter import (
    setup_tracing,
    export_traces,
    run_evaluators,
    is_enabled,
)


class TestIsEnabled(unittest.TestCase):
    def test_disabled_when_no_config(self):
        self.assertFalse(is_enabled({}))

    def test_disabled_when_explicitly_false(self):
        config = {"eval": {"langsmith": {"enabled": False}}}
        self.assertFalse(is_enabled(config))

    def test_enabled_when_true(self):
        config = {"eval": {"langsmith": {"enabled": True}}}
        self.assertTrue(is_enabled(config))


class TestSetupTracing(unittest.TestCase):
    def test_sets_env_vars(self):
        config = {
            "eval": {
                "langsmith": {
                    "enabled": True,
                    "api_key_env": "TEST_LS_KEY",
                    "project_prefix": "test-evolver",
                }
            }
        }
        with patch.dict(os.environ, {"TEST_LS_KEY": "fake-key"}):
            env = setup_tracing(config, "v003")
            self.assertEqual(env["LANGCHAIN_TRACING_V2"], "true")
            self.assertEqual(env["LANGCHAIN_API_KEY"], "fake-key")
            self.assertEqual(env["LANGCHAIN_PROJECT"], "test-evolver-v003")

    def test_returns_empty_when_no_api_key(self):
        config = {
            "eval": {
                "langsmith": {
                    "enabled": True,
                    "api_key_env": "NONEXISTENT_KEY_12345",
                    "project_prefix": "test",
                }
            }
        }
        env = setup_tracing(config, "v001")
        self.assertEqual(env, {})


class TestExportTraces(unittest.TestCase):
    @patch("langsmith_adapter.langsmith_api")
    def test_export_creates_langsmith_dir(self, mock_api):
        mock_api.get_runs.return_value = {"runs": [
            {
                "id": "run1", "run_type": "llm", "name": "chat",
                "inputs": {"prompt": "hi"}, "outputs": {"text": "hello"},
                "error": None, "latency_ms": 500,
                "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30,
                "child_run_ids": [], "extra": {}, "feedback_stats": None,
            }
        ]}
        tmpdir = tempfile.mkdtemp()
        config = {
            "eval": {
                "langsmith": {
                    "enabled": True,
                    "api_key_env": "TEST_KEY",
                    "project_prefix": "test",
                    "export_traces": True,
                }
            }
        }
        with patch.dict(os.environ, {"TEST_KEY": "fake"}):
            export_traces(config, "v001", tmpdir)
        ls_dir = os.path.join(tmpdir, "langsmith")
        self.assertTrue(os.path.isdir(ls_dir))
        self.assertTrue(os.path.exists(os.path.join(ls_dir, "_summary.json")))
        self.assertTrue(os.path.exists(os.path.join(ls_dir, "run1.json")))

    @patch("langsmith_adapter.langsmith_api")
    def test_export_summary_has_correct_fields(self, mock_api):
        mock_api.get_runs.return_value = {"runs": [
            {
                "id": "r1", "run_type": "llm", "name": "c",
                "inputs": {}, "outputs": {}, "error": "boom",
                "latency_ms": 100, "prompt_tokens": 5,
                "completion_tokens": 10, "total_tokens": 15,
                "child_run_ids": [], "extra": {}, "feedback_stats": None,
            }
        ]}
        tmpdir = tempfile.mkdtemp()
        config = {"eval": {"langsmith": {
            "enabled": True, "api_key_env": "K",
            "project_prefix": "t", "export_traces": True,
        }}}
        with patch.dict(os.environ, {"K": "k"}):
            export_traces(config, "v001", tmpdir)
        with open(os.path.join(tmpdir, "langsmith", "_summary.json")) as f:
            summary = json.load(f)
        self.assertEqual(summary["total_runs"], 1)
        self.assertEqual(len(summary["errors"]), 1)
        self.assertEqual(summary["total_tokens"], 15)


class TestRunEvaluators(unittest.TestCase):
    @patch("langsmith_adapter.langsmith_api")
    def test_runs_builtin_evaluators(self, mock_api):
        mock_api.run_evaluator.return_value = {"aggregate_score": 0.85}
        config = {"eval": {"langsmith": {
            "enabled": True, "api_key_env": "K",
            "project_prefix": "t",
            "evaluators": {"builtin": ["correctness"], "custom": []},
        }}}
        with patch.dict(os.environ, {"K": "k"}):
            scores = run_evaluators(config, "v001")
        self.assertIn("correctness", scores)
        self.assertAlmostEqual(scores["correctness"], 0.85)

    def test_returns_empty_without_evaluators(self):
        config = {"eval": {"langsmith": {
            "enabled": True, "api_key_env": "K",
            "project_prefix": "t",
            "evaluators": {"builtin": [], "custom": []},
        }}}
        scores = run_evaluators(config, "v001")
        self.assertEqual(scores, {})


if __name__ == "__main__":
    unittest.main()
