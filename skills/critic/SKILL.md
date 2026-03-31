---
name: harness-evolver:critic
description: "Use when scores converge suspiciously fast, eval quality is questionable, the harness reaches 1.0 in few iterations, or the user wants to validate that improvements are genuine. Also triggers automatically when score jumps >0.3 in one iteration."
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent]
---

# /harness-evolver:critic

Analyze eval quality and detect eval gaming.

## Resolve Tool Path

```bash
TOOLS=$([ -d ".harness-evolver/tools" ] && echo ".harness-evolver/tools" || echo "$HOME/.harness-evolver/tools")
```

## Prerequisites

`.harness-evolver/` must exist with at least one evaluated version (v001+).

## What To Do

1. Read `summary.json` to check for suspicious patterns:
   - Score jump >0.3 in a single iteration
   - Score reached 1.0 in <3 iterations
   - All tasks suddenly pass after failing

2. Spawn the `harness-evolver-critic` agent:
   > Analyze the eval quality for this harness evolution project.
   > Check if the eval at `.harness-evolver/eval/eval.py` is rigorous enough.
   > The best version is {version} with score {score} achieved in {iterations} iterations.

3. After the critic reports:
   - Show the eval quality assessment
   - If `eval_improved.py` was created, show the score comparison
   - Ask user: "Adopt the improved eval? This will re-baseline all scores."
   - If adopted: copy `eval_improved.py` to `eval/eval.py`, re-run baseline, update state
