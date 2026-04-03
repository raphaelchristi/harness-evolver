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
import platform
import sys


def ensure_langsmith_api_key():
    """Load LANGSMITH_API_KEY from env, project .env, or global credentials.

    Priority: env var > project .env (CWD or --config dir) > global credentials.
    Project .env takes precedence over global credentials because the project-local
    key is more likely to be correct and up-to-date.
    """
    if os.environ.get("LANGSMITH_API_KEY"):
        return True
    # Check .env in CWD and in --config directory FIRST (project-local > global)
    env_candidates = [".env"]
    for i, arg in enumerate(sys.argv):
        if arg == "--config" and i + 1 < len(sys.argv):
            cfg_dir = os.path.dirname(os.path.abspath(sys.argv[i + 1]))
            env_candidates.append(os.path.join(cfg_dir, ".env"))
        elif arg.startswith("--config="):
            cfg_dir = os.path.dirname(os.path.abspath(arg.split("=", 1)[1]))
            env_candidates.append(os.path.join(cfg_dir, ".env"))
    for env_path in env_candidates:
        if os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("LANGSMITH_API_KEY=") and not line.startswith("#"):
                            key = line.split("=", 1)[1].strip().strip("'\"")
                            if key:
                                os.environ["LANGSMITH_API_KEY"] = key
                                return True
            except OSError:
                pass
    # Fallback: global langsmith-cli credentials file
    if platform.system() == "Darwin":
        creds_path = os.path.expanduser("~/Library/Application Support/langsmith-cli/credentials")
    else:
        creds_path = os.path.expanduser("~/.config/langsmith-cli/credentials")
    if os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    return False


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

    ensure_langsmith_api_key()
    from langsmith import Client
    client = Client()

    all_issues = []

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
                    with open(args.config, "w") as f:
                        json.dump(config, f, indent=2)
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
                    with open(args.config, "w") as f:
                        json.dump(config, f, indent=2)
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
