---
name: harness-evolver:import-traces
description: "Use when the user wants to import real production traces from LangSmith as test tasks, convert traces to eval tasks, enrich their eval set with real-world data, or pull production data into their harness evaluation."
argument-hint: "[--project NAME] [--limit N]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep]
---

# /harness-evolver:import-traces

Import production traces from LangSmith and convert them into eval tasks. This enriches the test suite with real-world inputs, prioritizing traces with negative user feedback.

## Prerequisites

- `.harness-evolver/` must exist. If not, tell user to run `harness-evolver:init` first.
- `langsmith-cli` must be available. Check:

```bash
which langsmith-cli 2>/dev/null
```

If not found: "Install langsmith-cli first: `uv tool install langsmith-cli && langsmith-cli auth login`"

## Resolve Tool Path

```bash
TOOLS=$([ -d ".harness-evolver/tools" ] && echo ".harness-evolver/tools" || echo "$HOME/.harness-evolver/tools")
```

## Parse Arguments

- `--project NAME` — LangSmith project name (if not provided, discover interactively)
- `--limit N` — max traces to import (default: 20)

## Phase 1: Discover Projects

If `--project` not provided, list available projects:

```bash
langsmith-cli --json projects list --limit 20 2>/dev/null
```

Show the user a list of projects with run counts. Let them pick one, or use the most recent.

If `--project` is provided, use it directly.

## Phase 2: Fetch Traces

```bash
langsmith-cli --json runs list \
    --project "{project_name}" \
    --limit {limit} \
    --fields id,name,inputs,outputs,error,feedback_stats,total_tokens \
    > /tmp/harness_import_traces.json 2>/dev/null
```

Check the output has data:
```bash
python3 -c "import json; data=json.load(open('/tmp/harness_import_traces.json')); print(f'{len(data)} traces fetched')"
```

If no traces found, tell user the project may be empty or the name may be wrong.

## Phase 3: Convert to Tasks

```bash
python3 $TOOLS/import_traces.py \
    --traces-json /tmp/harness_import_traces.json \
    --output-dir .harness-evolver/eval/tasks/ \
    --prefix imported \
    --max-tasks {limit}
```

## Phase 4: Report

Read the tool output and report:
- How many traces were imported
- How many had negative feedback (high priority)
- How many were skipped (no extractable input, duplicates)
- Total tasks now in eval set

```bash
ls .harness-evolver/eval/tasks/*.json | wc -l
```

Print:
```
Imported {N} production traces as eval tasks.
  {M} with negative user feedback (high priority)
  {K} skipped (no input or duplicates)
  Total eval tasks: {total}

Next: run `harness-evolver:evolve` to optimize against real-world inputs.
```

## Gotchas

- Traces with no extractable user input are skipped (e.g., system-only runs)
- Duplicate traces (same run ID) are automatically skipped
- Imported tasks are tagged with `metadata.source: "imported"` and `metadata.type: "production"`
- Tasks with negative feedback get `metadata.user_feedback: "negative"` — the proposer should prioritize these
- The `metadata.langsmith_run_id` field links back to the original trace for debugging
- Cleanup: `rm /tmp/harness_import_traces.json` after import
