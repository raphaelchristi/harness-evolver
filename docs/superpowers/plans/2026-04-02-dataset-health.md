# Dataset Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect and auto-correct eval dataset quality issues — difficulty skew, coverage gaps, overfit risk, and dead examples.

**Architecture:** New `dataset_health.py` diagnostic tool + splits/metadata infrastructure in existing tools + auto-correction orchestration in evolve skill. Uses LangSmith native splits and metadata filtering.

**Tech Stack:** Python 3 (langsmith SDK), Claude Code plugin markdown (skills)

**Spec:** `docs/superpowers/specs/2026-04-02-dataset-health-design.md`

---

### Task 1: Create `dataset_health.py` diagnostic tool

**Files:**
- Create: `tools/dataset_health.py`

- [ ] **Step 1: Write the tool**

Create `tools/dataset_health.py` with the following complete implementation:

```python
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


def ensure_langsmith_api_key():
    """Load API key from langsmith-cli credentials if not in env."""
    if os.environ.get("LANGSMITH_API_KEY"):
        return True
    import platform
    if platform.system() == "Darwin":
        creds_path = os.path.expanduser("~/Library/Application Support/langsmith-cli/credentials")
    else:
        creds_path = os.path.expanduser("~/.config/langsmith-cli/credentials")
    if os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                for line in f:
                    if line.strip().startswith("api_key"):
                        key = line.split("=", 1)[1].strip().strip("'\"")
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
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
        runs = list(client.list_runs(project_name=best_exp, is_root=True, limit=200))
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
            runs = list(client.list_runs(project_name=exp_name, is_root=True, limit=200))
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

    # Compute health score and build report
    health_score = compute_health_score(size_info, difficulty, dead, coverage, splits)
    issues, corrections = build_issues_and_corrections(size_info, difficulty, dead, coverage, splits)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "health_score": health_score,
        "example_count": size_info["example_count"],
        "min_recommended": size_info["min_recommended"],
        "difficulty": {k: v for k, v in (difficulty or {}).items() if k != "example_difficulties"} or None,
        "dead_examples": dead,
        "coverage": coverage,
        "splits": splits,
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
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/dataset_health.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/dataset_health.py
git commit -m "feat: add dataset_health.py diagnostic tool"
```

---

### Task 2: Add splits and metadata to `setup.py`

**Files:**
- Modify: `tools/setup.py`

- [ ] **Step 1: Add split assignment after example creation**

In `setup.py`, find every place where `client.create_examples()` is called (lines 154, 184, and any others). After each batch creation, add split assignment:

```python
import random

# After client.create_examples(dataset_id=dataset.id, examples=examples)
all_examples = list(client.list_examples(dataset_id=dataset.id))
random.shuffle(all_examples)
split_point = int(len(all_examples) * 0.7)
for ex in all_examples[:split_point]:
    client.update_example(ex.id, split="train")
for ex in all_examples[split_point:]:
    client.update_example(ex.id, split="held_out")
```

This should be in a helper function to avoid repetition:

```python
def assign_splits(client, dataset_id, train_pct=70):
    """Assign train/held_out splits to all examples in a dataset."""
    import random
    examples = list(client.list_examples(dataset_id=dataset_id))
    random.shuffle(examples)
    split_point = int(len(examples) * train_pct / 100)
    for ex in examples[:split_point]:
        client.update_example(ex.id, split="train")
    for ex in examples[split_point:]:
        client.update_example(ex.id, split="held_out")
    return len(examples[:split_point]), len(examples[split_point:])
```

Add this function near the top (after `check_dependencies`), then call it after each dataset creation path (from_file, from_langsmith, from_testgen).

- [ ] **Step 2: Enrich metadata on example creation**

In `create_dataset_from_file()`, add `"source": "file"` and `"added_at_iteration": 0` to each example's metadata if not already present.

In `create_dataset_from_langsmith()`, add `"source": "production"` and `"added_at_iteration": 0`.

- [ ] **Step 3: Commit**

```bash
git add tools/setup.py
git commit -m "feat: add train/held-out splits and enriched metadata to setup.py"
```

---

### Task 3: Add splits and metadata to `adversarial_inject.py` and `regression_tracker.py`

**Files:**
- Modify: `tools/adversarial_inject.py`
- Modify: `tools/regression_tracker.py`

- [ ] **Step 1: Update adversarial_inject.py**

In the `create_example` call (around line 153), add split assignment and enrich metadata:

```python
import random

split = "train" if random.random() < 0.7 else "held_out"
client.create_example(
    inputs={"input": varied_input},
    dataset_id=dataset.id,
    metadata={
        "source": "adversarial",
        "original_example_id": str(example.id),
        "variation_type": vtype,
        "added_at_iteration": config.get("iterations", 0),
    },
    split=split,
)
```

Read `.evolver.json` at the start of main to get the iteration count. The config path can use `--config` flag (add if missing).

- [ ] **Step 2: Update regression_tracker.py**

Same pattern in the `create_example` call (around line 116):

```python
import random

split = "train" if random.random() < 0.7 else "held_out"
client.create_example(
    inputs=parsed_input_data,
    dataset_id=dataset.id,
    metadata={
        "source": "regression_guard",
        "original_example_id": t["example_id"],
        "added_at_iteration": config.get("iterations", 0),
    },
    split=split,
)
```

- [ ] **Step 3: Commit**

```bash
git add tools/adversarial_inject.py tools/regression_tracker.py
git commit -m "feat: add splits and enriched metadata to adversarial and regression tools"
```

---

### Task 4: Batch feedback fix + `--split` flag in `read_results.py`

**Files:**
- Modify: `tools/read_results.py`

- [ ] **Step 1: Fix N+1 feedback queries**

In `read_experiment()` (around line 64), replace the per-run feedback loop:

Find the pattern:
```python
for run in runs:
    ...
    feedbacks = list(client.list_feedback(run_ids=[run.id]))
```

Replace with batch approach:
```python
# Batch fetch all feedback
all_run_ids = [run.id for run in runs]
all_feedbacks = list(client.list_feedback(run_ids=all_run_ids))
fb_map = {}
for fb in all_feedbacks:
    fb_map.setdefault(str(fb.run_id), []).append(fb)

for run in runs:
    ...
    feedbacks = fb_map.get(str(run.id), [])
```

- [ ] **Step 2: Add `--split` CLI flag**

Add to the argparse in `main()`:
```python
parser.add_argument("--split", default=None, help="Filter by dataset split (e.g., 'train')")
```

When `--split` is set and `--experiment` is used, filter the results to only include runs whose `reference_example_id` is in the specified split. Do this by reading the dataset examples for that split:

```python
if args.split:
    with open(args.config) as f:
        cfg = json.load(f)
    split_example_ids = set()
    for ex in client.list_examples(dataset_name=cfg["dataset"], splits=[args.split]):
        split_example_ids.add(str(ex.id))
    # Filter per_example to only include split examples
    result["per_example"] = {k: v for k, v in result["per_example"].items() if k in split_example_ids}
    # Recompute combined score
    all_scores = [v["score"] for v in result["per_example"].values()]
    result["combined_score"] = sum(all_scores) / len(all_scores) if all_scores else 0.0
    result["num_examples"] = len(result["per_example"])
```

- [ ] **Step 3: Commit**

```bash
git add tools/read_results.py
git commit -m "feat: batch feedback queries and --split filter in read_results.py"
```

---

### Task 5: Batch feedback in `trace_insights.py` and `regression_tracker.py`

**Files:**
- Modify: `tools/trace_insights.py`
- Modify: `tools/regression_tracker.py`

- [ ] **Step 1: Fix N+1 in trace_insights.py**

Find the feedback loop pattern (around line 341) and apply same batch fix as Task 4.

- [ ] **Step 2: Fix N+1 in regression_tracker.py**

Find the feedback loop pattern (around line 65) and apply same batch fix.

- [ ] **Step 3: Commit**

```bash
git add tools/trace_insights.py tools/regression_tracker.py
git commit -m "fix: batch feedback queries in trace_insights and regression_tracker"
```

---

### Task 6: Evolve skill integration (Steps 0.6 + 0.7)

**Files:**
- Modify: `skills/evolve/SKILL.md`

- [ ] **Step 1: Add Step 0.6 Dataset Health Check**

After Step 0.5 (Validate State) and before Step 1 (Get Next Version), insert:

```markdown
### 0.6. Dataset Health Check

Run the dataset health diagnostic:

```bash
$EVOLVER_PY $TOOLS/dataset_health.py \
    --config .evolver.json \
    --production-seed production_seed.json \
    --output health_report.json 2>/dev/null
```

Read `health_report.json`. Print summary:
```bash
python3 -c "
import json, os
if os.path.exists('health_report.json'):
    r = json.load(open('health_report.json'))
    print(f'Dataset Health: {r[\"health_score\"]}/10 ({r[\"example_count\"]} examples)')
    for issue in r.get('issues', []):
        print(f'  [{issue[\"severity\"]}] {issue[\"message\"]}')
"
```

### 0.7. Auto-Correct Dataset Issues

If `health_report.json` has corrections, apply them automatically:

```bash
CORRECTIONS=$(python3 -c "
import json, os
if os.path.exists('health_report.json'):
    r = json.load(open('health_report.json'))
    for c in r.get('corrections', []):
        print(c['action'])
" 2>/dev/null)
```

For each correction:

**If `create_splits`**: Run inline Python to assign 70/30 splits:
```bash
$EVOLVER_PY -c "
from langsmith import Client
import json, random
client = Client()
config = json.load(open('.evolver.json'))
examples = list(client.list_examples(dataset_name=config['dataset']))
random.shuffle(examples)
sp = int(len(examples) * 0.7)
for ex in examples[:sp]:
    client.update_example(ex.id, split='train')
for ex in examples[sp:]:
    client.update_example(ex.id, split='held_out')
print(f'Assigned splits: {sp} train, {len(examples)-sp} held_out')
"
```

**If `generate_hard`**: Spawn testgen agent with hard-mode instruction:
```
Agent(
  subagent_type: "evolver-testgen",
  description: "Generate hard examples to rebalance dataset",
  prompt: |
    <objective>
    The dataset is skewed toward easy examples. Generate {count} HARD examples
    that the current agent is likely to fail on.
    Focus on: edge cases, adversarial inputs, complex multi-step queries,
    ambiguous questions, and inputs that require deep reasoning.
    </objective>
    <files_to_read>
    - .evolver.json
    - strategy.md (if exists)
    - production_seed.json (if exists)
    </files_to_read>
)
```

**If `fill_coverage`**: Spawn testgen agent with coverage-fill instruction:
```
Agent(
  subagent_type: "evolver-testgen",
  description: "Generate examples for missing categories",
  prompt: |
    <objective>
    The dataset is missing these production categories: {categories}.
    Generate 5 examples per missing category.
    Use production_seed.json for real-world patterns in these categories.
    </objective>
    <files_to_read>
    - .evolver.json
    - production_seed.json (if exists)
    </files_to_read>
)
```

**If `retire_dead`**: Move dead examples to retired split:
```bash
$EVOLVER_PY -c "
from langsmith import Client
import json
client = Client()
report = json.load(open('health_report.json'))
dead_ids = report.get('dead_examples', {}).get('ids', [])
config = json.load(open('.evolver.json'))
examples = {str(e.id): e for e in client.list_examples(dataset_name=config['dataset'])}
retired = 0
for eid in dead_ids:
    if eid in examples:
        client.update_example(examples[eid].id, split='retired')
        retired += 1
print(f'Retired {retired} dead examples')
"
```

After corrections, log what was done. Do NOT re-run health check (corrections may need an experiment cycle to show effect).
```

- [ ] **Step 2: Update Step 1.8 to use `--split train` for proposer briefing**

Find the `read_results.py` call in Step 1.8:
```bash
$EVOLVER_PY $TOOLS/read_results.py \
    --experiment "$BEST" \
    --config .evolver.json \
    --output best_results.json 2>/dev/null
```

Replace with:
```bash
$EVOLVER_PY $TOOLS/read_results.py \
    --experiment "$BEST" \
    --config .evolver.json \
    --split train \
    --output best_results.json 2>/dev/null
```

This ensures proposers only see train-split results, preventing overfit to held-out examples.

- [ ] **Step 3: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: add dataset health check and auto-correction to evolve loop"
```

---

### Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add dataset_health.py to tool descriptions**

In the tool listing, add:
```
# Dataset health diagnostic
python tools/dataset_health.py --config .evolver.json --output health_report.json
```

- [ ] **Step 2: Update tool descriptions in Architecture section**

Add `dataset_health.py` to the tools list. Note that it checks dataset quality before evolution.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add dataset_health.py to CLAUDE.md"
```

---

### Task 8: End-to-end verification

- [ ] **Step 1: Verify dataset_health.py syntax**
```bash
python3 -c "import ast; ast.parse(open('tools/dataset_health.py').read()); print('OK')"
```

- [ ] **Step 2: Verify no old N+1 feedback patterns remain**
```bash
grep -n "list_feedback(run_ids=\[run" tools/read_results.py tools/trace_insights.py tools/regression_tracker.py || echo "CLEAN: No N+1 patterns"
```

- [ ] **Step 3: Verify splits usage in tools**
```bash
grep -rn "split" tools/setup.py tools/adversarial_inject.py tools/regression_tracker.py | grep -v "\.split(" | head -20
```

- [ ] **Step 4: Verify evolve skill has health check steps**
```bash
grep -n "health" skills/evolve/SKILL.md | head -10
```

- [ ] **Step 5: Show commit log**
```bash
git log --oneline feat/dataset-health ^main
```
