# Evolution Modes Design Spec

## Overview

A `mode` field in `.evolver.json` that controls evolution intensity per iteration. Three modes: `light`, `balanced`, `heavy`. Affects dataset size (setup), proposer count, waves, concurrency, timeout, analysis depth, pairwise comparison, and archiving strategy.

## Modes

| Parameter | `light` | `balanced` | `heavy` |
|---|---|---|---|
| Dataset size (testgen) | 20 examples | 30 examples | 50 examples |
| Examples evaluated | Sample 10 from train | All train | All train + held_out |
| Proposers | 2 | 3 | 5 |
| Waves | Single | Two-wave | Two-wave |
| Eval concurrency | 5 | 3 | 3 |
| Timeout per example | 60s | 120s | 300s |
| Analysis format | `--format summary` | `--format summary` | `--format full` |
| Pairwise comparison | No | If top 2 < 5% | Always |
| Archive | Winner only | All candidates | All candidates |
| Estimated time/iter | ~2 min | ~8 min | ~25 min |

## Config

Field in `.evolver.json`:
```json
{
  "mode": "balanced"
}
```

Default: `"balanced"` when not set (backward compatible).

## User Interaction

### At setup (`/harness:setup`)

AskUserQuestion with 3 options after evaluator selection:
```json
{
  "question": "Evolution mode?",
  "header": "Mode",
  "options": [
    {"label": "light", "description": "20 examples, 2 proposers, ~2 min/iter. Good for testing and exploration."},
    {"label": "balanced (Recommended)", "description": "30 examples, 3 proposers, ~8 min/iter. Best trade-off."},
    {"label": "heavy", "description": "50 examples, 5 proposers, ~25 min/iter. Maximum quality."}
  ]
}
```

Written to `.evolver.json` as `"mode": "light|balanced|heavy"`.

### At evolve start (`/harness:evolve`)

Shows current mode and asks to confirm or switch:
```json
{
  "question": "Mode: balanced (3 proposers, ~8 min/iter). Continue?",
  "header": "Mode",
  "options": [
    {"label": "Yes, continue with balanced"},
    {"label": "Switch to light (~2 min/iter)"},
    {"label": "Switch to heavy (~25 min/iter)"}
  ]
}
```

If `--mode light|balanced|heavy` is passed as argument, skip the question and use the flag.

If `--no-interactive` is set, use the mode from config without asking.

If mode is changed, update `.evolver.json`.

## File Changes

### `tools/setup.py`

- Write `"mode"` field to config (default: user selection or `"balanced"`)
- Pass testgen count based on mode: light=20, balanced=30, heavy=50

### `skills/setup/SKILL.md`

- Add mode selection question after evaluator configuration
- Pass mode to setup.py or write to config after setup completes

### `skills/evolve/SKILL.md`

Read mode from config. Apply mode parameters to each step:

**Step 0 (Read State)**:
```python
MODE = json.load(open('.evolver.json')).get('mode', 'balanced')
```

Mode parameter lookup (inline in skill or as a constant block):
```
MODES = {
  "light":    {"proposers": 2, "waves": 1, "concurrency": 5, "timeout": 60,  "sample": 10, "analysis": "summary", "pairwise": False, "archive": "winner"},
  "balanced": {"proposers": 3, "waves": 2, "concurrency": 3, "timeout": 120, "sample": None, "analysis": "summary", "pairwise": "if_close", "archive": "all"},
  "heavy":    {"proposers": 5, "waves": 2, "concurrency": 3, "timeout": 300, "sample": None, "analysis": "full", "pairwise": True, "archive": "all"},
}
```

**Step 1 (Gather)**:
- `light` + `balanced`: `--format summary`
- `heavy`: `--format full`

**Step 3 (Proposers)**:
- `light`: 2 proposers, single wave (top 2 lenses by severity)
- `balanced`: 3 proposers, two-wave
- `heavy`: 5 proposers, two-wave

**Step 4 (Evaluate)**:
- `light`: `--concurrency 5 --timeout 60` + `--sample 10` (new flag)
- `balanced`: `--concurrency 3 --timeout 120`
- `heavy`: `--concurrency 3 --timeout 300`

**Step 5 (Compare)**:
- `light`: no pairwise
- `balanced`: pairwise if top 2 within 5%
- `heavy`: always pairwise

**Step 6 (Archive)**:
- `light`: archive winner only
- `balanced` + `heavy`: archive all candidates

### `tools/run_eval.py`

New `--sample N` flag: randomly select N examples from the dataset for evaluation instead of running all. Used by `light` mode.

Implementation: after loading dataset, if `--sample` is set, randomly pick N example IDs and filter the evaluation to only those.

### `agents/evolver-testgen.md`

Receives example count in prompt:
```
Generate {count} test inputs...
```

Where count comes from mode (20/30/50). Currently hardcoded to 30 — make it dynamic.

### `tools/preflight.py`

Add `mode` to schema validation. Valid values: `"light"`, `"balanced"`, `"heavy"`, or absent (defaults to `"balanced"`).

## Backward Compatibility

- Missing `mode` field defaults to `"balanced"` (current behavior)
- Existing `.evolver.json` files work without changes
- `--mode` flag overrides config for a single run
- All existing flags (--iterations, --concurrency, --no-canary) still work and override mode defaults

## What Does NOT Change

- Loop architecture (same steps)
- Agent definitions (proposer, evaluator, critic, architect, consolidator)
- Output format (chart, archive, regression guards)
- `--iterations` flag (independent of mode)
- LangSmith backend (datasets, experiments, feedback)
