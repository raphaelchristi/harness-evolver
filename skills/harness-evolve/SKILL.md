---
name: harness-evolve
description: "Run the harness evolution loop. Autonomously proposes, evaluates, and iterates on harness designs using full execution traces as feedback."
argument-hint: "[--iterations N] [--candidates-per-iter N]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent]
---

# /harness-evolve

Run the Meta-Harness optimization loop.

## Arguments

- `--iterations N` (default: 10) — number of evolution iterations
- `--candidates-per-iter N` (default: 1) — harnesses per iteration

## Prerequisites

Run `/harness-evolve-init` first. The `.harness-evolver/` directory must exist with a valid `summary.json`.

## The Loop

For each iteration i from 1 to N:

### 1. PROPOSE

Determine the next version number by reading `summary.json`:

```bash
python3 -c "import json; s=json.load(open('.harness-evolver/summary.json')); print(f'v{s[\"iterations\"]+1:03d}')"
```

Spawn the `harness-evolver-proposer` agent with this prompt:

> You are proposing iteration {i}. Create version {version_number} in `.harness-evolver/harnesses/{version_number}/`.
> Working directory contains `.harness-evolver/` with all prior candidates and traces.

The proposer agent will create:
- `.harness-evolver/harnesses/v{NNN}/harness.py`
- `.harness-evolver/harnesses/v{NNN}/config.json`
- `.harness-evolver/harnesses/v{NNN}/proposal.md`

### 2. VALIDATE

```bash
python3 ~/.harness-evolver/tools/evaluate.py validate \
    --harness .harness-evolver/harnesses/v{NNN}/harness.py \
    --config .harness-evolver/harnesses/v{NNN}/config.json
```

If validation fails, ask the proposer to fix (1 retry). If it fails again, set score to 0.0 and continue.

### 3. EVALUATE

```bash
python3 ~/.harness-evolver/tools/evaluate.py run \
    --harness .harness-evolver/harnesses/v{NNN}/harness.py \
    --config .harness-evolver/harnesses/v{NNN}/config.json \
    --tasks-dir .harness-evolver/eval/tasks/ \
    --eval .harness-evolver/eval/eval.py \
    --traces-dir .harness-evolver/harnesses/v{NNN}/traces/ \
    --scores .harness-evolver/harnesses/v{NNN}/scores.json \
    --timeout 60
```

### 4. UPDATE STATE

```bash
python3 ~/.harness-evolver/tools/state.py update \
    --base-dir .harness-evolver \
    --version v{NNN} \
    --scores .harness-evolver/harnesses/v{NNN}/scores.json \
    --proposal .harness-evolver/harnesses/v{NNN}/proposal.md
```

### 5. REPORT

Read the updated `summary.json` and report:
- `Iteration {i}/{N}: v{NNN} scored {score} (best: v{best} at {best_score})`
- If regression (score < parent score): warn
- If new best: celebrate

### Stop Conditions

- All N iterations completed
- **Stagnation**: 3 consecutive iterations without >1% improvement. Read `summary.json` history to check.
- **Target reached**: if `config.json` has `target_score` set and achieved.

When stopping, report final summary: best version, score, number of iterations, improvement over baseline.

## Tool Path Resolution

Check `.harness-evolver/tools/` first (local override), then `~/.harness-evolver/tools/` (global install).
