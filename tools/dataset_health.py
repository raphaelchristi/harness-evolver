#!/usr/bin/env python3
"""Dataset health diagnostic for Harness Evolver.

Analyzes eval dataset quality: size adequacy, difficulty distribution,
dead examples, production coverage, and split configuration.
Outputs health_report.json with issues and recommended corrections.

Usage:
    python3 dataset_health.py --config .evolver.json --output health_report.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Shared imports from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_langsmith_api_key
try:
    from secret_filter import has_secrets
except ImportError:
    def has_secrets(text):
        return False


def load_json_safe(path):
    """Load JSON file, return None if missing or invalid."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def check_size(examples, evaluators):
    """Check dataset size adequacy."""
    count = len(examples)
    min_recommended = max(20, 10 * len(evaluators))
    return {
        "example_count": count,
        "min_recommended": min_recommended,
        "adequate": count >= min_recommended,
    }


def check_difficulty(client, config):
    """Check difficulty distribution from best experiment scores."""
    best_exp = config.get("best_experiment")
    if not best_exp:
        return None

    try:
        runs = list(client.list_runs(project_name=best_exp, is_root=True, limit=100))
        if not runs:
            return None

        all_run_ids = [run.id for run in runs]
        all_feedbacks = list(client.list_feedback(run_ids=all_run_ids))
        fb_map = {}
        for fb in all_feedbacks:
            fb_map.setdefault(str(fb.run_id), []).append(fb)

        scores = []
        example_difficulties = {}
        for run in runs:
            run_fbs = fb_map.get(str(run.id), [])
            run_scores = [fb.score for fb in run_fbs if fb.score is not None]
            if run_scores:
                avg = sum(run_scores) / len(run_scores)
                scores.append(avg)
                eid = str(run.reference_example_id or run.id)
                if avg > 0.9:
                    example_difficulties[eid] = "easy"
                elif avg >= 0.5:
                    example_difficulties[eid] = "medium"
                else:
                    example_difficulties[eid] = "hard"

        if not scores:
            return None

        easy = sum(1 for s in scores if s > 0.9)
        medium = sum(1 for s in scores if 0.5 <= s <= 0.9)
        hard = sum(1 for s in scores if s < 0.5)
        total = len(scores)
        skew = None
        if total > 0 and easy / total > 0.6:
            skew = "easy_heavy"
        elif total > 0 and hard / total > 0.6:
            skew = "hard_heavy"

        return {
            "easy": easy,
            "medium": medium,
            "hard": hard,
            "skew": skew,
            "example_difficulties": example_difficulties,
        }
    except Exception:
        return None


def check_dead_examples(client, config):
    """Find examples that scored >=0.9 across all recent experiments."""
    history = config.get("history", [])
    if len(history) < 2:
        return {"count": 0, "ids": []}

    recent_exps = [h["experiment"] for h in history[-3:]]
    example_scores = {}

    for exp_name in recent_exps:
        try:
            runs = list(client.list_runs(project_name=exp_name, is_root=True, limit=100))
            all_run_ids = [run.id for run in runs]
            if not all_run_ids:
                continue
            all_feedbacks = list(client.list_feedback(run_ids=all_run_ids))
            fb_map = {}
            for fb in all_feedbacks:
                fb_map.setdefault(str(fb.run_id), []).append(fb)

            for run in runs:
                eid = str(run.reference_example_id or run.id)
                run_fbs = fb_map.get(str(run.id), [])
                run_scores = [fb.score for fb in run_fbs if fb.score is not None]
                if run_scores:
                    avg = sum(run_scores) / len(run_scores)
                    if eid not in example_scores:
                        example_scores[eid] = []
                    example_scores[eid].append(avg)
        except Exception:
            continue

    dead_ids = []
    for eid, exp_scores in example_scores.items():
        if len(exp_scores) >= 2 and all(s >= 0.9 for s in exp_scores):
            dead_ids.append(eid)

    return {"count": len(dead_ids), "ids": dead_ids}


def check_coverage(examples, production):
    """Compare dataset categories vs production traffic."""
    if not production:
        return None

    prod_categories = set()
    for cat in production.get("categories", []):
        if isinstance(cat, str):
            prod_categories.add(cat)
        elif isinstance(cat, dict) and "category" in cat:
            prod_categories.add(cat["category"])

    if not prod_categories:
        return None

    dataset_categories = set()
    for ex in examples:
        meta = getattr(ex, "metadata", None) or {}
        if "category" in meta:
            dataset_categories.add(meta["category"])

    missing = prod_categories - dataset_categories
    coverage_pct = 0
    if prod_categories:
        coverage_pct = int(100 * len(prod_categories - missing) / len(prod_categories))

    return {
        "production": sorted(prod_categories),
        "dataset": sorted(dataset_categories),
        "missing": sorted(missing),
        "pct": coverage_pct,
    }


def check_splits(client, dataset_name):
    """Check if train/held_out splits exist."""
    has_train = False
    has_held_out = False
    try:
        train = list(client.list_examples(dataset_name=dataset_name, splits=["train"], limit=1))
        has_train = len(train) > 0
    except Exception:
        pass
    try:
        held = list(client.list_examples(dataset_name=dataset_name, splits=["held_out"], limit=1))
        has_held_out = len(held) > 0
    except Exception:
        pass
    return {"has_train": has_train, "has_held_out": has_held_out}


def compute_health_score(size_info, difficulty, dead, coverage, splits):
    """Compute overall health score 0-10."""
    score = 10

    if not size_info.get("adequate"):
        score -= 3

    if difficulty and difficulty.get("skew"):
        score -= 2

    if dead and dead.get("count", 0) > 0:
        total = size_info.get("example_count", 1)
        if dead["count"] / max(total, 1) > 0.2:
            score -= 1

    if coverage and coverage.get("pct", 100) < 75:
        score -= 2

    if splits and not splits.get("has_train"):
        score -= 2

    return max(0, score)


def build_issues_and_corrections(size_info, difficulty, dead, coverage, splits):
    """Build issues and corrections lists."""
    issues = []
    corrections = []

    if not size_info.get("adequate"):
        issues.append({
            "type": "size_inadequate",
            "severity": "high",
            "message": f"Only {size_info['example_count']} examples (recommended: {size_info['min_recommended']}+)",
        })
        corrections.append({
            "action": "generate_more",
            "count": size_info["min_recommended"] - size_info["example_count"],
        })

    if difficulty and difficulty.get("skew") == "easy_heavy":
        easy_pct = int(100 * difficulty["easy"] / max(difficulty["easy"] + difficulty["medium"] + difficulty["hard"], 1))
        issues.append({
            "type": "difficulty_skew",
            "severity": "high",
            "message": f"{easy_pct}% easy examples — low discriminative power",
        })
        corrections.append({
            "action": "generate_hard",
            "count": max(5, difficulty["easy"] // 3),
        })

    if dead and dead.get("count", 0) > 0:
        total = size_info.get("example_count", 1)
        dead_pct = int(100 * dead["count"] / max(total, 1))
        if dead_pct > 10:
            issues.append({
                "type": "dead_examples",
                "severity": "medium",
                "message": f"{dead['count']} dead examples ({dead_pct}%) — scored >=0.9 in all recent experiments",
            })
            corrections.append({
                "action": "retire_dead",
                "ids": dead["ids"],
            })

    if coverage and coverage.get("missing"):
        issues.append({
            "type": "coverage_gap",
            "severity": "high",
            "message": f"Missing categories: {', '.join(coverage['missing'])} ({coverage['pct']}% coverage)",
        })
        corrections.append({
            "action": "fill_coverage",
            "categories": coverage["missing"],
        })

    if splits and not splits.get("has_train"):
        issues.append({
            "type": "no_splits",
            "severity": "medium",
            "message": "No train/held-out split — proposer overfit risk",
        })
        corrections.append({
            "action": "create_splits",
            "train_pct": 70,
        })

    return issues, corrections


def main():
    parser = argparse.ArgumentParser(description="Dataset health diagnostic")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--production-seed", default="production_seed.json")
    parser.add_argument("--output", default="health_report.json")
    args = parser.parse_args()

    ensure_langsmith_api_key()

    with open(args.config) as f:
        config = json.load(f)

    production = load_json_safe(args.production_seed)

    from langsmith import Client
    client = Client()

    dataset_name = config["dataset"]

    # Get all examples
    examples = list(client.list_examples(dataset_name=dataset_name, limit=500))

    # Run checks
    evaluators = config.get("evaluators", ["correctness"])
    size_info = check_size(examples, evaluators)
    difficulty = check_difficulty(client, config)
    dead = check_dead_examples(client, config)
    coverage = check_coverage(examples, production)
    splits = check_splits(client, dataset_name)

    # Tag difficulty metadata on examples if we computed it
    if difficulty and difficulty.get("example_difficulties"):
        for ex in examples:
            eid = str(ex.id)
            diff = difficulty["example_difficulties"].get(eid)
            if diff:
                meta = dict(getattr(ex, "metadata", None) or {})
                if meta.get("difficulty") != diff:
                    meta["difficulty"] = diff
                    try:
                        client.update_example(ex.id, metadata=meta)
                    except Exception:
                        pass

    # Check for secrets in dataset examples
    secrets_check = {"checked": True, "flagged_count": 0, "flagged_ids": [], "clean": True}
    for ex in examples:
        text = str(getattr(ex, 'inputs', '') or '') + str(getattr(ex, 'outputs', '') or '')
        if has_secrets(text):
            secrets_check["flagged_count"] += 1
            secrets_check["flagged_ids"].append(str(ex.id))
            secrets_check["clean"] = False
    secrets_check["flagged_ids"] = secrets_check["flagged_ids"][:10]  # Cap at 10

    # Compute health score and build report
    health_score = compute_health_score(size_info, difficulty, dead, coverage, splits)
    issues, corrections = build_issues_and_corrections(size_info, difficulty, dead, coverage, splits)

    # Add secret issues
    if not secrets_check["clean"]:
        issues.append({
            "severity": "critical",
            "message": f"{secrets_check['flagged_count']} example(s) contain potential secrets (API keys, tokens)",
        })
        corrections.append({
            "action": "remove_secrets",
            "description": f"Remove or redact {secrets_check['flagged_count']} examples with detected secrets",
            "example_ids": secrets_check["flagged_ids"],
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "health_score": health_score,
        "example_count": size_info["example_count"],
        "min_recommended": size_info["min_recommended"],
        "difficulty": {k: v for k, v in (difficulty or {}).items() if k != "example_difficulties"} or None,
        "dead_examples": dead,
        "coverage": coverage,
        "splits": splits,
        "secrets": secrets_check,
        "issues": issues,
        "corrections": corrections,
    }

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    # Print human-readable summary
    print(f"Dataset Health: {health_score}/10")
    print(f"Examples: {size_info['example_count']} (min recommended: {size_info['min_recommended']})")
    if difficulty:
        print(f"Difficulty: {difficulty.get('easy', 0)} easy, {difficulty.get('medium', 0)} medium, {difficulty.get('hard', 0)} hard")
    if dead and dead["count"] > 0:
        print(f"Dead examples: {dead['count']}")
    if coverage:
        print(f"Coverage: {coverage['pct']}% ({len(coverage.get('missing', []))} categories missing)")
    if splits:
        print(f"Splits: train={'yes' if splits['has_train'] else 'no'}, held_out={'yes' if splits['has_held_out'] else 'no'}")
    if issues:
        print(f"\nIssues ({len(issues)}):")
        for issue in issues:
            print(f"  [{issue['severity']}] {issue['message']}")


if __name__ == "__main__":
    main()
