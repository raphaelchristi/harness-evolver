---
name: diagnose
description: "Use when the user wants to understand why a specific harness version failed, investigate a regression, analyze trace data, or debug a low score. Also use when the user says 'why did v003 fail' or 'what went wrong'."
argument-hint: "[version]"
allowed-tools: [Read, Bash, Glob, Grep]
---

# /harness-evolver:diagnose

Deep analysis of a harness version's execution traces and scores.

## Arguments

- `version` — version to diagnose (e.g., `v003`). If not given, diagnose the worst or most recent regression.

## Resolve Tool Path

```bash
TOOLS=$([ -d ".harness-evolver/tools" ] && echo ".harness-evolver/tools" || echo "$HOME/.harness-evolver/tools")
```

## What To Do

### 1. Identify the Version

If not specified, find the worst or most recent regression:

```bash
python3 $TOOLS/state.py show --base-dir .harness-evolver
cat .harness-evolver/summary.json
```

### 2. Score Breakdown

```bash
cat .harness-evolver/harnesses/{version}/scores.json
```

Identify which tasks failed (`score: 0.0`) and which passed.

### 3. Trace Analysis (failed tasks)

For each failed task:

```bash
cat .harness-evolver/harnesses/{version}/traces/{task_id}/input.json
cat .harness-evolver/harnesses/{version}/traces/{task_id}/output.json
```

Look for patterns: wrong format? wrong category? empty output? crash?

### 4. Error Search

```bash
grep -r "error\|Error\|FAIL\|exception\|Traceback" .harness-evolver/harnesses/{version}/traces/
cat .harness-evolver/harnesses/{version}/traces/stderr.log
```

### 5. Compare with Parent

Read the proposal to find the parent version:

```bash
cat .harness-evolver/harnesses/{version}/proposal.md
```

Then diff:

```bash
diff .harness-evolver/harnesses/{parent}/harness.py .harness-evolver/harnesses/{version}/harness.py
```

### 6. LangSmith (if available)

If `langsmith-cli` is installed and LangSmith is configured:

```bash
langsmith-cli --json runs list --project harness-evolver-{version} --failed --fields id,name,error,inputs
langsmith-cli --json runs stats --project harness-evolver-{version}
```

### 7. Report

```
Diagnosis: v003 (score: 0.31) — REGRESSION from v001 (0.62)

Root cause: Prompt template change broke JSON parsing
  - 4/10 tasks returned malformed output
  - stderr shows: json.JSONDecodeError on 4 tasks
  - The change on line 42 removed the "Reply with ONLY..." instruction

Affected tasks: task_002, task_005, task_007, task_010
Unaffected tasks: task_001, task_003, task_004, task_006, task_008, task_009

Recommendation: Revert the prompt change, keep the retry logic from v002
```
