---
name: compare
description: "Use when the user wants to compare two harness versions, understand what changed between iterations, see why one version scored better than another, or debug a regression."
argument-hint: "<vA> <vB>"
allowed-tools: [Read, Bash, Glob, Grep]
---

# /harness-evolver:compare

Compare two harness versions side by side.

## Arguments

- `vA` — first version (e.g., `v001`, `baseline`)
- `vB` — second version (e.g., `v003`)

If only one version given, compare it against the current best.
If no versions given, compare the two most recent.

## What To Do

### 1. Code Diff

```bash
diff .harness-evolver/harnesses/{vA}/harness.py .harness-evolver/harnesses/{vB}/harness.py
```

If config changed:
```bash
diff .harness-evolver/harnesses/{vA}/config.json .harness-evolver/harnesses/{vB}/config.json
```

### 2. Score Comparison

```bash
cat .harness-evolver/harnesses/{vA}/scores.json
cat .harness-evolver/harnesses/{vB}/scores.json
```

Report: combined_score delta, per-task wins/losses.

### 3. Per-Task Analysis

For tasks where scores diverge, show what each version produced:

```bash
cat .harness-evolver/harnesses/{vA}/traces/task_{ID}/output.json
cat .harness-evolver/harnesses/{vB}/traces/task_{ID}/output.json
```

### 4. Proposal Context

```bash
cat .harness-evolver/harnesses/{vB}/proposal.md
```

Show what the proposer intended and whether the result matched expectations.

## Report Format

```
v001 (0.62) vs v003 (0.71) — +0.09 improvement

Code changes:
  + Added few-shot examples (3 examples)
  ~ Changed prompt template
  - Removed retry logic

Per-task:
  task_001: 1.0 → 1.0 (unchanged)
  task_007: 0.0 → 1.0 (FIXED — was cardiac, now correctly classified)
  task_008: 1.0 → 0.0 (REGRESSION — was neurological, now wrong)
```
