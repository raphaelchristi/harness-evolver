#!/usr/bin/env python3
"""Validate .evolver.json state against LangSmith reality.

Checks that referenced experiments, datasets, and projects still exist.
Returns JSON with validation results and any divergences found.

Usage:
    python3 validate_state.py --config .evolver.json --output validation.json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_langsmith_api_key, write_config_atomic


def validate_config_schema(config):
    """Validate .evolver.json structure without API calls."""
    issues = []

    REQUIRED = {"project": str, "dataset": str, "entry_point": str, "evaluators": list, "history": list}
    for field, expected_type in REQUIRED.items():
        if field not in config:
            issues.append(f"missing required field: {field}")
        elif not isinstance(config[field], expected_type):
            issues.append(f"{field} must be {expected_type.__name__}, got {type(config[field]).__name__}")

    if isinstance(config.get("evaluators"), list) and len(config["evaluators"]) == 0:
        issues.append("evaluators list is empty")

    for i, h in enumerate(config.get("history", [])):
        if not isinstance(h, dict):
            issues.append(f"history[{i}] must be a dict")
            continue
        if "version" not in h:
            issues.append(f"history[{i}] missing 'version'")
        if "score" not in h:
            issues.append(f"history[{i}] missing 'score'")
        elif not isinstance(h["score"], (int, float)):
            issues.append(f"history[{i}].score must be numeric")

    bs = config.get("best_score")
    if bs is not None and not isinstance(bs, (int, float)):
        issues.append(f"best_score must be numeric or null")

    ew = config.get("evaluator_weights")
    if ew is not None and not isinstance(ew, dict):
        issues.append(f"evaluator_weights must be a dict or null")

    return issues


def validate_dataset(client, config):
    """Check dataset exists and has expected example count."""
    issues = []
    dataset_name = config.get("dataset")
    dataset_id = config.get("dataset_id")
    if not dataset_name:
        issues.append({"field": "dataset", "severity": "critical", "message": "No dataset configured"})
        return issues, 0
    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
        if dataset_id and str(dataset.id) != dataset_id:
            issues.append({
                "field": "dataset_id",
                "severity": "warning",
                "message": f"dataset_id mismatch: config has {dataset_id}, LangSmith has {dataset.id}",
            })
        count = len(list(client.list_examples(dataset_id=dataset.id, limit=500)))
        return issues, count
    except Exception as e:
        issues.append({"field": "dataset", "severity": "critical", "message": f"Dataset not found: {e}"})
        return issues, 0


def validate_best_experiment(client, config):
    """Check best_experiment still exists and score matches."""
    issues = []
    best = config.get("best_experiment")
    if not best:
        return issues
    try:
        runs = list(client.list_runs(project_name=best, is_root=True, limit=1))
        if not runs:
            issues.append({
                "field": "best_experiment",
                "severity": "critical",
                "message": f"Best experiment '{best}' has no runs in LangSmith",
            })
    except Exception as e:
        issues.append({
            "field": "best_experiment",
            "severity": "critical",
            "message": f"Best experiment '{best}' not accessible: {e}",
        })
    return issues


def validate_git_state(config):
    """Check that current git HEAD matches expected state."""
    import subprocess
    issues = []
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=10,
        )
        head = result.stdout.strip()
        if not head:
            issues.append({"field": "git", "severity": "warning", "message": "Could not read git HEAD"})
    except Exception as e:
        issues.append({"field": "git", "severity": "warning", "message": f"Git check failed: {e}"})
    return issues


def main():
    parser = argparse.ArgumentParser(description="Validate .evolver.json against LangSmith")
    parser.add_argument("--config", default=".evolver.json", help="Config path")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--fix", action="store_true", help="Auto-fix divergences where possible")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(json.dumps({"valid": False, "issues": [{"severity": "critical", "message": f"{args.config} not found"}]}))
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    # Schema validation first (no API needed)
    schema_issues = validate_config_schema(config)
    if schema_issues:
        # Critical schema errors — can't proceed with API validation
        critical = [i for i in schema_issues if "missing required" in i]
        if critical:
            result = {
                "valid": False,
                "issues": [{"severity": "critical", "message": f"Schema: {i}"} for i in schema_issues],
            }
            out = json.dumps(result, indent=2)
            if args.output:
                with open(args.output, "w") as f:
                    f.write(out)
            print(out)
            sys.exit(1)

    ensure_langsmith_api_key()
    from langsmith import Client
    client = Client()

    all_issues = []
    # Add non-critical schema warnings
    for si in schema_issues:
        all_issues.append({"field": "schema", "severity": "warning", "message": si})

    # Validate dataset
    dataset_issues, example_count = validate_dataset(client, config)
    all_issues.extend(dataset_issues)

    # Validate best experiment
    experiment_issues = validate_best_experiment(client, config)
    all_issues.extend(experiment_issues)

    # Validate git state
    git_issues = validate_git_state(config)
    all_issues.extend(git_issues)

    # Check history consistency
    history = config.get("history", [])
    if history:
        last = history[-1]
        if last.get("experiment") != config.get("best_experiment"):
            best_score = config.get("best_score", 0)
            last_score = last.get("score", 0)
            if last_score >= best_score:
                all_issues.append({
                    "field": "history",
                    "severity": "warning",
                    "message": f"Last history entry ({last['experiment']}) differs from best_experiment ({config.get('best_experiment')})",
                })

    # Auto-fix divergences if --fix flag is set
    if args.fix:
        fixed = []
        for issue in all_issues:
            if issue.get("field") == "dataset_id" and issue.get("severity") == "warning":
                try:
                    dataset = client.read_dataset(dataset_name=config["dataset"])
                    config["dataset_id"] = str(dataset.id)
                    write_config_atomic(args.config, config)
                    fixed.append(f"Fixed dataset_id: updated to {dataset.id}")
                    issue["severity"] = "fixed"
                except Exception:
                    pass
            elif issue.get("field") == "history" and issue.get("severity") == "warning":
                history = config.get("history", [])
                if history:
                    best_in_history = max(history, key=lambda h: h.get("score", 0))
                    config["best_experiment"] = best_in_history["experiment"]
                    config["best_score"] = best_in_history["score"]
                    write_config_atomic(args.config, config)
                    fixed.append(f"Fixed best_experiment: set to {best_in_history['experiment']}")
                    issue["severity"] = "fixed"
        if fixed:
            print(f"Auto-fixed {len(fixed)} issues:", file=sys.stderr)
            for f_msg in fixed:
                print(f"  {f_msg}", file=sys.stderr)

    all_issues = [i for i in all_issues if i.get("severity") != "fixed"]
    critical = [i for i in all_issues if i.get("severity") == "critical"]
    result = {
        "valid": len(critical) == 0,
        "issues": all_issues,
        "dataset_examples": example_count,
        "config_iterations": config.get("iterations", 0),
        "config_best_score": config.get("best_score", 0),
    }

    output = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    print(output)

    if critical:
        sys.exit(1)


if __name__ == "__main__":
    main()
