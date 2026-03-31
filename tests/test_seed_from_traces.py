"""Tests for seed_from_traces.py — fetch and summarize production LangSmith traces."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
SEED_PY = os.path.join(TOOLS_DIR, "seed_from_traces.py")

# We can't call the real LangSmith API in tests, so we test the analysis
# and output generation functions by importing them directly.
sys.path.insert(0, TOOLS_DIR)
import seed_from_traces


class TestExtractInput(unittest.TestCase):
    def test_direct_input_field(self):
        run = {"inputs": {"input": "What is Python?"}}
        self.assertEqual(seed_from_traces.extract_input(run), "What is Python?")

    def test_question_field(self):
        run = {"inputs": {"question": "Explain quantum computing"}}
        self.assertEqual(seed_from_traces.extract_input(run), "Explain quantum computing")

    def test_langchain_messages_format(self):
        run = {"inputs": {"messages": [[
            {"type": "system", "content": "You are helpful"},
            {"type": "human", "content": "Hello world"},
        ]]}}
        self.assertEqual(seed_from_traces.extract_input(run), "Hello world")

    def test_flat_messages(self):
        run = {"inputs": {"messages": [
            {"type": "human", "content": "Flat format"},
        ]}}
        self.assertEqual(seed_from_traces.extract_input(run), "Flat format")

    def test_role_based_messages(self):
        run = {"inputs": {"messages": [
            {"role": "user", "content": "Role format"},
        ]}}
        self.assertEqual(seed_from_traces.extract_input(run), "Role format")

    def test_empty_inputs(self):
        run = {"inputs": {}}
        self.assertIsNone(seed_from_traces.extract_input(run))

    def test_no_inputs(self):
        run = {}
        self.assertIsNone(seed_from_traces.extract_input(run))


class TestExtractOutput(unittest.TestCase):
    def test_direct_output_field(self):
        run = {"outputs": {"output": "The answer is 42"}}
        self.assertEqual(seed_from_traces.extract_output(run), "The answer is 42")

    def test_ai_message_format(self):
        run = {"outputs": {"messages": [
            {"type": "ai", "content": "AI response here"},
        ]}}
        self.assertEqual(seed_from_traces.extract_output(run), "AI response here")

    def test_empty_outputs(self):
        run = {"outputs": {}}
        self.assertIsNone(seed_from_traces.extract_output(run))


class TestGetFeedback(unittest.TestCase):
    def test_negative_feedback(self):
        run = {"feedback_stats": {"thumbs_up": 0, "thumbs_down": 1}}
        self.assertEqual(seed_from_traces.get_feedback(run), "negative")

    def test_positive_feedback(self):
        run = {"feedback_stats": {"thumbs_up": 1, "thumbs_down": 0}}
        self.assertEqual(seed_from_traces.get_feedback(run), "positive")

    def test_no_feedback(self):
        run = {"feedback_stats": {}}
        self.assertIsNone(seed_from_traces.get_feedback(run))

    def test_missing_feedback(self):
        run = {}
        self.assertIsNone(seed_from_traces.get_feedback(run))


class TestAnalyzeRuns(unittest.TestCase):
    def _make_runs(self):
        return [
            {
                "name": "AgentA",
                "inputs": {"input": "Question about topic A"},
                "outputs": {"output": "Answer A"},
                "error": None,
                "total_tokens": 500,
                "feedback_stats": {"thumbs_up": 1, "thumbs_down": 0},
            },
            {
                "name": "AgentA",
                "inputs": {"input": "Another topic A question"},
                "outputs": {"output": "Answer A2"},
                "error": None,
                "total_tokens": 800,
                "feedback_stats": None,
            },
            {
                "name": "AgentB",
                "inputs": {"input": "Topic B question"},
                "outputs": {"output": "Answer B"},
                "error": None,
                "total_tokens": 300,
                "feedback_stats": {"thumbs_up": 0, "thumbs_down": 1},
            },
            {
                "name": "AgentB",
                "inputs": {"input": "Failing query"},
                "outputs": {},
                "error": "TimeoutError: took too long",
                "total_tokens": 0,
                "feedback_stats": None,
            },
        ]

    def test_basic_analysis(self):
        analysis = seed_from_traces.analyze_runs(self._make_runs())
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis["stats"]["total_traces"], 4)
        self.assertEqual(analysis["stats"]["with_error"], 1)

    def test_category_distribution(self):
        analysis = seed_from_traces.analyze_runs(self._make_runs())
        self.assertEqual(analysis["categories"]["AgentA"], 2)
        self.assertEqual(analysis["categories"]["AgentB"], 2)

    def test_error_patterns(self):
        analysis = seed_from_traces.analyze_runs(self._make_runs())
        self.assertTrue(len(analysis["error_patterns"]) >= 1)
        self.assertIn("TimeoutError", list(analysis["error_patterns"].keys())[0])

    def test_feedback_counts(self):
        analysis = seed_from_traces.analyze_runs(self._make_runs())
        fb = analysis["stats"]["feedback"]
        self.assertEqual(fb["positive"], 1)
        self.assertEqual(fb["negative"], 1)

    def test_token_stats(self):
        analysis = seed_from_traces.analyze_runs(self._make_runs())
        self.assertIn("tokens", analysis["stats"])
        self.assertGreater(analysis["stats"]["tokens"]["avg"], 0)

    def test_empty_runs(self):
        self.assertIsNone(seed_from_traces.analyze_runs([]))


class TestGenerateOutputs(unittest.TestCase):
    def setUp(self):
        self.runs = [
            {
                "name": "Agent",
                "inputs": {"input": f"Question {i}"},
                "outputs": {"output": f"Answer {i}"},
                "error": None if i < 8 else "SomeError",
                "total_tokens": 500 + i * 100,
                "feedback_stats": {"thumbs_down": 1} if i == 3 else None,
            }
            for i in range(10)
        ]
        self.analysis = seed_from_traces.analyze_runs(self.runs)

    def test_markdown_generation(self):
        md = seed_from_traces.generate_markdown_seed(self.analysis, "test-project")
        self.assertIn("test-project", md)
        self.assertIn("Traffic Distribution", md)
        self.assertIn("Sample Inputs", md)
        self.assertIn("Guidance for Test Generation", md)

    def test_json_generation(self):
        summary = seed_from_traces.generate_json_summary(self.analysis, "test-project")
        self.assertEqual(summary["project"], "test-project")
        self.assertIn("stats", summary)
        self.assertIn("categories", summary)
        self.assertIn("sample_inputs", summary)
        self.assertIn("negative_feedback_inputs", summary)

    def test_negative_feedback_in_json(self):
        summary = seed_from_traces.generate_json_summary(self.analysis, "test")
        # Run index 3 had negative feedback
        self.assertTrue(len(summary["negative_feedback_inputs"]) >= 1)


class TestCLIMissingApiKey(unittest.TestCase):
    def test_exits_without_api_key(self):
        """Should fail gracefully when no API key is set."""
        tmpdir = tempfile.mkdtemp()
        env = os.environ.copy()
        env.pop("LANGSMITH_API_KEY", None)
        r = subprocess.run(
            [sys.executable, SEED_PY,
             "--project", "fake-project",
             "--output-md", os.path.join(tmpdir, "seed.md"),
             "--output-json", os.path.join(tmpdir, "seed.json")],
            capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No API key", r.stderr)


class TestDetectLangsmithProject(unittest.TestCase):
    """Test the _detect_langsmith_project function from init.py."""

    def test_from_env_var(self):
        sys.path.insert(0, TOOLS_DIR)
        import init as init_module
        with patch.dict(os.environ, {"LANGCHAIN_PROJECT": "my-project"}):
            self.assertEqual(init_module._detect_langsmith_project(), "my-project")

    def test_from_langsmith_env_var(self):
        sys.path.insert(0, TOOLS_DIR)
        import init as init_module
        env = {"LANGSMITH_PROJECT": "other-project"}
        # Remove LANGCHAIN_PROJECT if it exists
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("LANGCHAIN_PROJECT", None)
            self.assertEqual(init_module._detect_langsmith_project(), "other-project")

    def test_from_env_file(self):
        sys.path.insert(0, TOOLS_DIR)
        import init as init_module
        tmpdir = tempfile.mkdtemp()
        env_file = os.path.join(tmpdir, ".env")
        with open(env_file, "w") as f:
            f.write('# Comment\nSOME_VAR=foo\nLANGCHAIN_PROJECT="ceppem-langgraph"\n')
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGCHAIN_PROJECT", None)
            os.environ.pop("LANGSMITH_PROJECT", None)
            result = init_module._detect_langsmith_project(tmpdir)
            self.assertEqual(result, "ceppem-langgraph")

    def test_returns_none_when_not_found(self):
        sys.path.insert(0, TOOLS_DIR)
        import init as init_module
        tmpdir = tempfile.mkdtemp()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGCHAIN_PROJECT", None)
            os.environ.pop("LANGSMITH_PROJECT", None)
            result = init_module._detect_langsmith_project(tmpdir)
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
