#!/usr/bin/env python3
"""LangSmith REST API client. Stdlib-only (urllib + json).

Provides low-level API calls to LangSmith for trace export, dataset access,
and evaluator execution. Used by langsmith_adapter.py.
"""

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

LANGSMITH_BASE_URL = os.environ.get(
    "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
)


def _request(method, path, api_key, data=None):
    url = f"{LANGSMITH_BASE_URL}{path}"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"LangSmith API error {e.code}: {error_body}")


def get_runs(api_key, project_name, run_type=None, limit=100):
    params = {"project_name": project_name, "limit": limit}
    if run_type:
        params["run_type"] = run_type
    return _request("POST", "/api/v1/runs/query", api_key, params)


def get_dataset_examples(api_key, dataset_id, limit=1000):
    return _request(
        "GET", f"/api/v1/datasets/{dataset_id}/examples?limit={limit}", api_key
    )


def create_project(api_key, project_name):
    return _request("POST", "/api/v1/projects", api_key, {"name": project_name})


def get_feedback(api_key, project_name):
    runs = get_runs(api_key, project_name)
    run_ids = [r["id"] for r in runs.get("runs", [])]
    if not run_ids:
        return []
    return _request("POST", "/api/v1/feedback/query", api_key, {"run_ids": run_ids})


def run_evaluator(api_key, project_name, evaluator_name):
    return _request(
        "POST",
        "/api/v1/evaluators/run",
        api_key,
        {"project_name": project_name, "evaluator": evaluator_name},
    )
