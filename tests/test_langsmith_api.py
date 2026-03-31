"""Tests for langsmith_api.py — REST API client (stdlib urllib)."""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from langsmith_api import get_runs, get_dataset_examples, create_project, get_feedback


class TestLangSmithAPI(unittest.TestCase):
    @patch("langsmith_api.urlopen")
    def test_get_runs_sends_correct_request(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"runs": []}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = get_runs("fake-key", "my-project")
        self.assertEqual(result, {"runs": []})

        call_args = mock_urlopen.call_args[0][0]
        self.assertIn("runs/query", call_args.full_url)
        self.assertEqual(call_args.get_header("X-api-key"), "fake-key")

    @patch("langsmith_api.urlopen")
    def test_get_runs_with_run_type(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"runs": [{"id": "r1"}]}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = get_runs("fake-key", "proj", run_type="llm")
        self.assertEqual(len(result["runs"]), 1)

        call_args = mock_urlopen.call_args[0][0]
        body = json.loads(call_args.data.decode())
        self.assertEqual(body["run_type"], "llm")

    @patch("langsmith_api.urlopen")
    def test_get_dataset_examples(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([{"id": "ex1"}]).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = get_dataset_examples("fake-key", "ds-123")
        self.assertEqual(result, [{"id": "ex1"}])

    @patch("langsmith_api.urlopen")
    def test_create_project(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": "p1", "name": "test"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = create_project("fake-key", "test")
        self.assertEqual(result["name"], "test")

    @patch("langsmith_api.urlopen")
    def test_get_feedback_empty_when_no_runs(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"runs": []}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = get_feedback("fake-key", "proj")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
