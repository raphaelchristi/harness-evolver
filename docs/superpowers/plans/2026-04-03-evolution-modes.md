# Evolution Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `light`/`balanced`/`heavy` modes controlling evolution intensity — dataset size, proposers, concurrency, timeout, analysis depth — selectable at setup and switchable at evolve start.

**Architecture:** A `mode` field in `.evolver.json` maps to a parameter dict used by the evolve skill. `run_eval.py` gets `--sample N` for light mode. Setup asks the question, evolve confirms/switches. All mode logic lives in the skill, not in tools (tools just receive flags).

**Tech Stack:** Python 3 stdlib, existing skills/tools conventions.

---

## File Map

| Action | File | What changes |
|--------|------|-------------|
| Modify | `tools/setup.py:508-530` | Add `mode` field to config |
| Modify | `tools/run_eval.py:155-170` | Add `--sample N` flag |
| Modify | `tools/preflight.py:81-96` | Validate `mode` in schema |
| Modify | `skills/setup/SKILL.md` | Mode selection question |
| Modify | `skills/evolve/SKILL.md` | Mode confirm/switch + apply params per step |
| Modify | `agents/evolver-testgen.md` | Dynamic example count |
| Modify | `tests/test_tools.py` | Test --sample flag |

---

### Task 1: `--sample N` flag in run_eval.py

**Files:**
- Modify: `tools/run_eval.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Add `--sample` flag to argparse**

In `tools/run_eval.py`, after the `--no-canary` line (around line 167), add:

```python
    parser.add_argument("--sample", type=int, default=None, help="Evaluate a random sample of N examples instead of all")
```

- [ ] **Step 2: Add sampling logic after client initialization**

After `client = Client()` (line 175), before the canary block, add:

```python
    # Sample mode: evaluate subset of dataset (used by light mode)
    dataset_name = config["dataset"]
    if args.sample:
        import random
        all_examples = list(client.list_examples(dataset_name=dataset_name, limit=500))
        if args.sample < len(all_examples):
            sampled = random.sample(all_examples, args.sample)
            sample_ids = {str(ex.id) for ex in sampled}
            dataset_name = None  # Will pass example IDs directly
            print(f"  Sampling {args.sample}/{len(all_examples)} examples", file=sys.stderr)
```

Then modify the `client.evaluate()` call to use either `data=dataset_name` or `data=sampled`:

```python
        eval_kwargs = {
            "evaluators": evaluators,
            "experiment_prefix": args.experiment_prefix,
            "max_concurrency": concurrency,
        }
        if args.sample and dataset_name is None:
            eval_kwargs["data"] = sampled
        else:
            eval_kwargs["data"] = config["dataset"]

        results = client.evaluate(target, **eval_kwargs)
```

- [ ] **Step 3: Test**

```bash
python3 -c "import ast; ast.parse(open('tools/run_eval.py').read()); print('OK')"
python3 tests/test_tools.py 2>&1 | tail -3
```

- [ ] **Step 4: Commit**

```bash
git add tools/run_eval.py
git commit -m "feat: --sample N flag in run_eval.py for light mode subset evaluation"
```

---

### Task 2: Mode field in setup.py + preflight validation

**Files:**
- Modify: `tools/setup.py:508-530`
- Modify: `tools/preflight.py:81-96`

- [ ] **Step 1: Add `mode` to config output in setup.py**

In `tools/setup.py`, in the config dict (around line 508), add after `evaluator_weights`:

```python
            "mode": args.mode if hasattr(args, 'mode') and args.mode else "balanced",
```

Add `--mode` to argparse in setup.py's `main()`:

```python
    parser.add_argument("--mode", choices=["light", "balanced", "heavy"], default="balanced", help="Evolution mode")
```

- [ ] **Step 2: Add `mode` validation to preflight schema check**

In `tools/preflight.py`, inside `check_config_schema()`, after the `evaluator_weights` check, add:

```python
    mode = config.get("mode")
    if mode is not None and mode not in ("light", "balanced", "heavy"):
        issues.append(f"mode must be light/balanced/heavy, got '{mode}'")
```

- [ ] **Step 3: Test**

```bash
python3 -c "import ast; ast.parse(open('tools/setup.py').read()); ast.parse(open('tools/preflight.py').read()); print('OK')"
python3 tests/test_tools.py 2>&1 | tail -3
```

- [ ] **Step 4: Commit**

```bash
git add tools/setup.py tools/preflight.py
git commit -m "feat: mode field in .evolver.json + preflight validation"
```

---

### Task 3: Mode selection in setup skill

**Files:**
- Modify: `skills/setup/SKILL.md`

- [ ] **Step 1: Add mode question after evaluator selection**

In `skills/setup/SKILL.md`, after the evaluator/goals question block (around line 130), add:

```markdown
### Phase 2.5: Mode Selection

```json
{
  "questions": [{
    "question": "Evolution mode?",
    "header": "Mode",
    "multiSelect": false,
    "options": [
      {"label": "light", "description": "20 examples, 2 proposers, ~2 min/iter. Good for testing."},
      {"label": "balanced (Recommended)", "description": "30 examples, 3 proposers, ~8 min/iter. Best trade-off."},
      {"label": "heavy", "description": "50 examples, 5 proposers, ~25 min/iter. Maximum quality."}
    ]
  }]
}
```

Pass selection to setup.py as `--mode light|balanced|heavy`.

The mode determines testgen count:
- `light`: pass `--count 20` to testgen agent (or generate 20 examples)
- `balanced`: pass `--count 30` (default, current behavior)
- `heavy`: pass `--count 50`
```

- [ ] **Step 2: Commit**

```bash
git add skills/setup/SKILL.md
git commit -m "feat: mode selection question in setup skill"
```

---

### Task 4: Dynamic testgen count

**Files:**
- Modify: `agents/evolver-testgen.md`

- [ ] **Step 1: Make example count dynamic**

In `agents/evolver-testgen.md`, change the hardcoded "Generate 30 test inputs" to:

```markdown
Generate {count} test inputs as a JSON file (count specified in your prompt — default 30 if not specified):
```

The evolve/setup skill passes the count in the testgen prompt based on mode.

- [ ] **Step 2: Commit**

```bash
git add agents/evolver-testgen.md
git commit -m "feat: dynamic testgen count based on evolution mode"
```

---

### Task 5: Mode confirm/switch + apply params in evolve skill

**Files:**
- Modify: `skills/evolve/SKILL.md`

This is the main task. The evolve skill reads mode and applies different parameters per step.

- [ ] **Step 1: Add mode constants and confirm/switch block**

In `skills/evolve/SKILL.md`, replace the current "Arguments" and "Pre-Loop" interactive section with:

After the `## Arguments` section, add a mode parameter block:

```markdown
## Mode Parameters

```
MODE_PARAMS = {
  "light":    {"proposers": 2, "waves": 1, "concurrency": 5, "timeout": 60, "sample": 10, "analysis": "summary", "pairwise": False, "archive": "winner"},
  "balanced": {"proposers": 3, "waves": 2, "concurrency": 3, "timeout": 120, "sample": None, "analysis": "summary", "pairwise": "if_close", "archive": "all"},
  "heavy":    {"proposers": 5, "waves": 2, "concurrency": 3, "timeout": 300, "sample": None, "analysis": "full", "pairwise": True, "archive": "all"},
}
```

Read mode from config:
```bash
MODE=$(python3 -c "import json; print(json.load(open('.evolver.json')).get('mode', 'balanced'))")
```

If `--mode` argument provided, use it and update config. Otherwise, show current mode and ask to confirm or switch (unless `--no-interactive`):

```json
{
  "question": "Mode: {MODE} ({proposers} proposers, ~{time} min/iter). Continue?",
  "header": "Mode",
  "options": [
    {"label": "Yes, continue with {MODE}"},
    {"label": "Switch to light (~2 min/iter)"},
    {"label": "Switch to heavy (~25 min/iter)"}
  ]
}
```

If mode changed, update `.evolver.json`:
```bash
python3 -c "import json; c=json.load(open('.evolver.json')); c['mode']='{NEW_MODE}'; json.dump(c, open('.evolver.json','w'), indent=2)"
```
```

- [ ] **Step 2: Apply mode to each step**

Update each step in the skill to reference mode params:

**Step 1 (Gather)**: 
- `light`/`balanced`: `--format summary`
- `heavy`: `--format full` (remove `--format summary`)

**Step 3 (Proposers)**:
- Read `MODE_PARAMS[MODE]["proposers"]` for lens count cap
- Read `MODE_PARAMS[MODE]["waves"]` for single vs two-wave

**Step 4 (Evaluate)**:
- Add `--sample {MODE_PARAMS[MODE]["sample"]}` if not None
- Add `--timeout {MODE_PARAMS[MODE]["timeout"]}`
- Concurrency from mode: `--concurrency {MODE_PARAMS[MODE]["concurrency"]}`

**Step 5 (Compare)**:
- Pairwise: `MODE_PARAMS[MODE]["pairwise"]`

**Step 6 (Archive)**:
- `"winner"`: only archive the winning candidate
- `"all"`: archive all candidates (current behavior)

- [ ] **Step 3: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: evolve skill reads mode and applies per-step parameters"
```

---

### Task 6: Update docs + tests

**Files:**
- Modify: `CLAUDE.md`
- Modify: `tests/test_tools.py`
- Modify: `docs/FEATURES.md`

- [ ] **Step 1: Add mode to CLAUDE.md**

In the "Key conventions" section:

```markdown
- Evolution modes: `light` (20 examples, 2 proposers, ~2 min/iter), `balanced` (30, 3, ~8 min), `heavy` (50, 5, ~25 min). Set in `.evolver.json` `mode` field or via `--mode` flag.
```

- [ ] **Step 2: Add mode to FEATURES.md**

In the Core section:

```markdown
| **Evolution Modes** | Three intensity levels: `light` (fast exploration, 2 proposers, sample eval), `balanced` (recommended, 3 proposers, full train), `heavy` (maximum quality, 5 proposers, full dataset). Selected at setup, switchable at evolve start. |
```

- [ ] **Step 3: Add test for --sample flag**

In `tests/test_tools.py`:

```python
def test_run_eval_sample_flag():
    """run_eval.py accepts --sample flag."""
    code, stdout, stderr = run_tool("run_eval.py", ["--help"])
    assert "--sample" in stdout
```

- [ ] **Step 4: Run tests**

```bash
python3 tests/test_tools.py 2>&1 | tail -3
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/FEATURES.md tests/test_tools.py
git commit -m "docs: evolution modes in CLAUDE.md, FEATURES.md + test for --sample"
```
