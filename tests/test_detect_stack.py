"""Tests for detect_stack.py — AST-based stack detection."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from detect_stack import detect_from_file, detect_from_directory


class TestDetectFromFile(unittest.TestCase):
    def _write_py(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_detects_langchain(self):
        path = self._write_py("from langchain_openai import ChatOpenAI\nimport langchain\n")
        result = detect_from_file(path)
        self.assertIn("langchain", result)
        self.assertEqual(result["langchain"]["context7_id"], "/langchain-ai/langchain")
        self.assertIn("langchain", result["langchain"]["modules_found"])
        self.assertIn("langchain_openai", result["langchain"]["modules_found"])

    def test_detects_langgraph(self):
        path = self._write_py("from langgraph.graph import StateGraph\n")
        result = detect_from_file(path)
        self.assertIn("langgraph", result)
        self.assertEqual(result["langgraph"]["context7_id"], "/langchain-ai/langgraph")

    def test_detects_anthropic(self):
        path = self._write_py("import anthropic\n")
        result = detect_from_file(path)
        self.assertIn("anthropic", result)

    def test_detects_openai(self):
        path = self._write_py("from openai import OpenAI\n")
        result = detect_from_file(path)
        self.assertIn("openai", result)

    def test_detects_multiple(self):
        path = self._write_py("import langchain\nimport chromadb\nimport fastapi\n")
        result = detect_from_file(path)
        self.assertIn("langchain", result)
        self.assertIn("chromadb", result)
        self.assertIn("fastapi", result)

    def test_no_detection_for_stdlib(self):
        path = self._write_py("import json\nimport os\nimport sys\n")
        result = detect_from_file(path)
        self.assertEqual(result, {})

    def test_handles_syntax_error(self):
        path = self._write_py("def broken(\n")
        result = detect_from_file(path)
        self.assertEqual(result, {})

    def test_no_detection_for_unknown_lib(self):
        path = self._write_py("import some_custom_library\n")
        result = detect_from_file(path)
        self.assertEqual(result, {})


class TestDetectFromDirectory(unittest.TestCase):
    def test_merges_across_files(self):
        tmpdir = tempfile.mkdtemp()
        with open(os.path.join(tmpdir, "a.py"), "w") as f:
            f.write("import langchain\n")
        with open(os.path.join(tmpdir, "b.py"), "w") as f:
            f.write("from langchain_openai import ChatOpenAI\nimport chromadb\n")
        result = detect_from_directory(tmpdir)
        self.assertIn("langchain", result)
        self.assertIn("chromadb", result)
        self.assertIn("langchain_openai", result["langchain"]["modules_found"])
        self.assertIn("langchain", result["langchain"]["modules_found"])


if __name__ == "__main__":
    unittest.main()
