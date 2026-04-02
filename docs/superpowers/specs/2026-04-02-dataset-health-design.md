# Dataset Health: Eval Quality Detection + Auto-Correction

*Design spec for detecting and fixing eval dataset quality issues.*

**Date**: 2026-04-02
**Branch**: `feat/dataset-health`
**Baseline**: harness-evolver v4.1.0

## Problem

The evolution loop's quality depends on the eval dataset, but there's no validation of dataset quality. Six gaps:

1. No minimum size check — datasets with 0-10 examples produce volatile scores
2. No difficulty analysis — datasets can be 90% easy with no discriminative power
3. No coverage analysis — dataset may not represent production traffic
4. No dead example detection — examples scored 1.0 by all candidates waste eval tokens
5. No train/held-out split — proposers can overfit to the exact examples they're scored on
6. No structured metadata — can't filter or analyze examples by category/difficulty/source

## Solution: Approach B — Detect + Correct Split

**Detection:** New `tools/dataset_health.py` — pure diagnostic tool. Reads data from LangSmith, computes metrics, outputs `health_report.json`. Zero side-effects.

**Correction:** Orchestrated by `skills/evolve/SKILL.md`. Reads health report, takes action using existing mechanisms (testgen agent, seed_from_traces.py, SDK calls for splits).

**Infrastructure:** Add LangSmith native splits and enriched metadata to all tools that create examples.

## Design

### 1. `tools/dataset_health.py` (NEW)

Stdlib-only tool (uses langsmith SDK only for reading). Shares `ensure_langsmith_api_key()` pattern with other tools.

**CLI:**
```bash
$EVOLVER_PY $TOOLS/dataset_health.py \
    --config .evolver.json \
    --production-seed production_seed.json \
    --output health_report.json
```

**Computes 5 metrics:**

1. **Size adequacy** — example count vs minimum (heuristic: `10 * len(evaluators)`, floor 20). Output: `adequate: bool`.

2. **Difficulty distribution** — requires at least 1 experiment with scores. Reads scores from best experiment via `client.list_runs()` + `client.list_feedback()`. Buckets: easy (>0.9), medium (0.5-0.9), hard (<0.5). Flags `skew: "easy_heavy"` if >60% easy.

3. **Dead examples** — requires 2+ experiments. Examples that scored >=0.9 across ALL candidates in the last 3 experiments. These waste eval budget. Output: `dead_count`, `dead_ids`.

4. **Coverage** — requires `production_seed.json`. Compares production traffic categories against dataset example metadata categories. Output: `missing` categories, `coverage_pct`.

5. **Splits** — checks if train/held_out splits exist via `client.list_examples(splits=["train"])`. Output: `has_train`, `has_held_out`.

**Output format** (`health_report.json`):
```json
{
  "health_score": 4,
  "example_count": 30,
  "min_recommended": 20,
  "difficulty": {"easy": 22, "medium": 5, "hard": 3, "skew": "easy_heavy"},
  "dead_examples": {"count": 7, "ids": ["ex-1", "ex-5"]},
  "coverage": {"production": ["multi-step","factual"], "dataset": ["factual"], "missing": ["multi-step"], "pct": 50},
  "splits": {"has_train": false, "has_held_out": false},
  "issues": [
    {"type": "difficulty_skew", "severity": "high", "message": "73% easy examples — low discriminative power"},
    {"type": "no_splits", "severity": "medium", "message": "No train/held-out split — proposer overfit risk"},
    {"type": "coverage_gap", "severity": "high", "message": "Missing categories: multi-step, code-gen"}
  ],
  "corrections": [
    {"action": "generate_hard", "count": 10},
    {"action": "create_splits", "train_pct": 70},
    {"action": "fill_coverage", "categories": ["multi-step", "code-gen"]}
  ]
}
```

**Health score:** 0-10 scale. Subtract points for each issue: no_splits -2, difficulty_skew -2, coverage_gap -2 (per 25% missing), dead_examples -1 (if >20% dead), size_inadequate -3.

### 2. Splits Infrastructure

LangSmith native splits. Three tools modified:

**`tools/setup.py`** — After creating all examples, assign splits:
```python
import random
examples = list(client.list_examples(dataset_id=dataset.id))
random.shuffle(examples)
split_point = int(len(examples) * 0.7)
for ex in examples[:split_point]:
    client.update_example(ex.id, split="train")
for ex in examples[split_point:]:
    client.update_example(ex.id, split="held_out")
```

**`tools/adversarial_inject.py`** — When creating adversarial examples, assign split randomly (70/30):
```python
split = "train" if random.random() < 0.7 else "held_out"
client.create_example(inputs=..., dataset_id=..., metadata=..., split=split)
```

**`tools/regression_tracker.py`** — Same 70/30 random split for guard examples.

### 3. Metadata Enrichment

All tools that create examples include standardized metadata fields:

```python
metadata = {
    "source": "generated" | "production" | "adversarial" | "regression_guard" | "coverage_fill",
    "added_at_iteration": config.get("iterations", 0),
    # "category" when available from production seed
    # "difficulty" tagged post-hoc by dataset_health.py based on actual scores
}
```

Modified tools: `setup.py`, `adversarial_inject.py`, `regression_tracker.py`.

The `difficulty` field is NOT set at creation time — it's tagged by `dataset_health.py` after the baseline/experiment scores are known, using `client.update_example(id, metadata={"difficulty": "easy"})`.

### 4. Evolve Skill Integration

New steps in `skills/evolve/SKILL.md`:

**Step 0.6: Dataset Health Check** (after validate_state, before iteration loop):
```bash
$EVOLVER_PY $TOOLS/dataset_health.py \
    --config .evolver.json \
    --production-seed production_seed.json \
    --output health_report.json 2>/dev/null
```

Read health_report.json. Print summary.

**Step 0.7: Auto-Correct** (if issues found):

For each correction in `health_report.json.corrections`:

- `"create_splits"` → Run inline Python to assign 70/30 splits via SDK
- `"generate_hard"` → Spawn `evolver-testgen` agent with prompt: "Generate {count} HARD examples that the current agent is likely to fail on. Focus on edge cases, adversarial inputs, and complex multi-step queries."
- `"fill_coverage"` → If production_seed.json exists, call `seed_from_traces.py` with `--categories` filter. If not, spawn testgen with: "Generate examples for these categories: {missing}."
- `"retire_dead"` → Update dead examples' split to `"retired"` via SDK: `client.update_example(id, split="retired")`

After corrections, re-run health check to verify improvement. Log corrections applied.

**Step 1.8 modification:** When calling `read_results.py` for proposer briefing, add `--split train` flag so proposers only see train-split scores. The Step 4 comparison uses all examples (no split filter).

### 5. Batch Feedback Fix

`read_results.py`, `trace_insights.py`, and `regression_tracker.py` all have N+1 feedback queries (one `client.list_feedback(run_ids=[run.id])` per run). Fix by collecting all run IDs first and batching:

```python
all_run_ids = [run.id for run in runs]
all_feedbacks = list(client.list_feedback(run_ids=all_run_ids))
# Group by run_id
feedback_map = {}
for fb in all_feedbacks:
    feedback_map.setdefault(str(fb.run_id), []).append(fb)
```

This changes the data access pattern, not the logic. Applied to: `read_results.py`, `trace_insights.py`, `regression_tracker.py`.

### 6. `read_results.py` — Split Filter

Add `--split` CLI flag:
```bash
$EVOLVER_PY $TOOLS/read_results.py --experiment "v003-1" --config .evolver.json --split train --output best_results.json
```

When `--split` is set, filter examples by split before scoring. Implementation: read dataset examples with `client.list_examples(dataset_id=id, splits=[split])`, get their IDs, and only include runs whose `reference_example_id` matches.

## Files to modify

1. `tools/dataset_health.py` — NEW: diagnostic tool
2. `tools/setup.py` — Add split assignment after example creation, enrich metadata
3. `tools/adversarial_inject.py` — Add split assignment, enrich metadata
4. `tools/regression_tracker.py` — Add split assignment, enrich metadata, batch feedback
5. `tools/read_results.py` — Add `--split` flag, batch feedback
6. `tools/trace_insights.py` — Batch feedback
7. `skills/evolve/SKILL.md` — Steps 0.6 + 0.7, Step 1.8 `--split train`
8. `CLAUDE.md` — Update tool descriptions

## Out of scope

- evaluate_comparative() — current comparison works, not worth rewriting
- Summary evaluators — evaluator agent via CLI handles this role
- Example weighting — complexity vs gain not justified yet
- Annotation queues — no humans in autonomous loop
- Online evaluation/automations — post-deploy concern, not core loop
