---
name: harness-evolver:evolve
description: "Use when the user wants to run the optimization loop, improve harness performance, evolve the harness, or iterate on harness quality. Requires .harness-evolver/ to exist (run harness-evolver:init first)."
argument-hint: "[--iterations N]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent]
---

# /harness-evolve

Run the autonomous propose-evaluate-iterate loop.

## Prerequisites

`.harness-evolver/summary.json` must exist. If not, tell user to run `harness-evolver:init`.

## Resolve Tool Path

```bash
TOOLS=$([ -d ".harness-evolver/tools" ] && echo ".harness-evolver/tools" || echo "$HOME/.harness-evolver/tools")
```

## Parse Arguments

- `--iterations N` (default: 10)
- Read `config.json` for `evolution.stagnation_limit` (default: 3) and `evolution.target_score`

## The Loop

For each iteration:

### 1. Get Next Version

```bash
python3 -c "import json; s=json.load(open('.harness-evolver/summary.json')); print(f'v{s[\"iterations\"]+1:03d}')"
```

### 2. Propose

Spawn the `harness-evolver-proposer` agent:

> You are proposing iteration {i}. Create version {version} in `.harness-evolver/harnesses/{version}/`.
> Working directory contains `.harness-evolver/` with all prior candidates and traces.

The proposer creates: `harness.py`, `config.json`, `proposal.md`.

### 3. Validate

```bash
python3 $TOOLS/evaluate.py validate \
    --harness .harness-evolver/harnesses/{version}/harness.py \
    --config .harness-evolver/harnesses/{version}/config.json
```

If fails: one retry via proposer. If still fails: score 0.0, continue.

### 4. Evaluate

```bash
python3 $TOOLS/evaluate.py run \
    --harness .harness-evolver/harnesses/{version}/harness.py \
    --config .harness-evolver/harnesses/{version}/config.json \
    --tasks-dir .harness-evolver/eval/tasks/ \
    --eval .harness-evolver/eval/eval.py \
    --traces-dir .harness-evolver/harnesses/{version}/traces/ \
    --scores .harness-evolver/harnesses/{version}/scores.json \
    --timeout 60
```

### 5. Update State

```bash
python3 $TOOLS/state.py update \
    --base-dir .harness-evolver \
    --version {version} \
    --scores .harness-evolver/harnesses/{version}/scores.json \
    --proposal .harness-evolver/harnesses/{version}/proposal.md
```

### 6. Report

Read `summary.json`. Print: `Iteration {i}/{N}: {version} scored {score} (best: {best} at {best_score})`

### 6.5. Check for Eval Gaming

After updating state, read the latest `summary.json` and check:
- Did the score jump >0.3 from parent version?
- Did we reach 1.0 in fewer than 3 total iterations?

If either is true, warn:

> Suspicious convergence detected: score jumped from {parent_score} to {score} in one iteration.
> The eval may be too lenient. Run `/harness-evolver:critic` to analyze eval quality.

If score is 1.0 and iterations < 3, STOP the loop and strongly recommend the critic:

> Perfect score reached in only {iterations} iteration(s). This usually indicates
> the eval is too easy, not that the harness is perfect. Run `/harness-evolver:critic`
> before continuing.

### 7. Auto-trigger Architect (on stagnation or regression)

Check if the architect should be auto-spawned. This happens when:
- **Stagnation**: 3 consecutive iterations within 1% of each other
- **Regression**: score dropped below parent score (even once)

AND `.harness-evolver/architecture.json` does NOT already exist.

If triggered:

```bash
python3 $TOOLS/analyze_architecture.py \
    --harness .harness-evolver/harnesses/{best_version}/harness.py \
    --traces-dir .harness-evolver/harnesses/{best_version}/traces \
    --summary .harness-evolver/summary.json \
    -o .harness-evolver/architecture_signals.json
```

Then spawn the `harness-evolver-architect` agent:

> The evolution loop has stagnated/regressed after {iterations} iterations (best: {best_score}).
> Analyze the harness architecture and recommend a topology change.
> Raw signals at `.harness-evolver/architecture_signals.json`.
> Write `.harness-evolver/architecture.json` and `.harness-evolver/architecture.md`.

After the architect completes, report:

> Architect recommends: {current} → {recommended} ({confidence} confidence)
> Migration path: {N} steps. Continuing evolution with architecture guidance.

Then **continue the loop** — the proposer will read `architecture.json` in the next iteration.

If `architecture.json` already exists (architect already ran), skip — don't re-run.

### 8. Check Stop Conditions

- **Target**: `combined_score >= target_score` → stop
- **N reached**: done
- **Stagnation post-architect**: 3 more iterations without improvement AFTER architect ran → stop (architecture change didn't help)

## When Loop Ends — Final Report

- Best version and score
- Improvement over baseline (absolute and %)
- Total iterations run
- Whether architect was triggered and what it recommended
- Suggest: "The best harness is at `.harness-evolver/harnesses/{best}/harness.py`. Copy it to your project."
