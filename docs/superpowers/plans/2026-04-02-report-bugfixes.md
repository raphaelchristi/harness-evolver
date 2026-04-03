# Report Bugfixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 4 bugs that hit 100% of real-world evolution runs (per REPORT.md from 3 independent repos): worktree file propagation, `{input}` protocol mismatch, canary run preflight, and LLM-judge on baseline.

**Architecture:** Fix 1 modifies the evolve skill to copy config files into worktrees. Fix 2 adds `{input_text}` placeholder to `run_eval.py` for agents expecting plain text. Fix 3 adds a `--canary` preflight to `run_eval.py`. Fix 4 adds a baseline LLM-judge step to the evolve skill pre-loop.

**Tech Stack:** Python 3 stdlib, LangSmith SDK, Markdown skills.

---

## File Map

| Action | File | Fix |
|--------|------|-----|
| Modify | `skills/evolve/SKILL.md:340-357` | Copy .evolver.json + .env to worktrees before eval |
| Modify | `skills/evolve/SKILL.md:108-134` | LLM-judge on baseline pre-loop |
| Modify | `tools/run_eval.py:63-131` | Add `{input_text}` placeholder + canary run |
| Modify | `CLAUDE.md` | Document `{input_text}` and `--no-canary` |

---

### Task 1: Fix `{input}` protocol — add `{input_text}` placeholder (P0)

**Files:**
- Modify: `tools/run_eval.py:73-86`

Every REPORT.md flagged this: `run_eval.py` replaces `{input}` with a temp JSON file path, but most agents expect plain text. The fix adds a `{input_text}` placeholder that extracts the actual text value from the inputs dict and passes it shell-escaped.

- [ ] **Step 1: Add `{input_text}` handling to `make_target()`**

In `tools/run_eval.py`, modify the placeholder handling block (lines 73-86). Add `{input_text}` BEFORE the `{input}` check so it takes priority:

```python
        try:
            cmd = entry_point

            # Extract plain text from inputs dict for {input_text} placeholder
            if "{input_text}" in cmd:
                import shlex
                text = ""
                for key in ("input", "question", "query", "prompt", "text", "user_input"):
                    if key in inputs and isinstance(inputs[key], str):
                        text = inputs[key]
                        break
                if not text and inputs:
                    # Fallback: stringify first value
                    first_val = next(iter(inputs.values()), "")
                    text = str(first_val) if not isinstance(first_val, str) else first_val
                cmd = cmd.replace("{input_text}", shlex.quote(text))
            elif "{input}" in cmd:
                # Placeholder: replace with path to JSON file
                cmd = cmd.replace("{input}", input_path)
            elif "{input_json}" in cmd:
                # Placeholder: replace with inline JSON string
                cmd = cmd.replace("{input_json}", input_json)
            elif "--input" in cmd or "-i " in cmd:
                cmd = f"{cmd} {input_path}"
            else:
                cmd = f"{cmd} --input {input_path} --output {output_path}"
```

- [ ] **Step 2: Test locally with a mock entry point**

```bash
python3 -c "
import json, tempfile, os

# Simulate what make_target does with {input_text}
inputs = {'input': 'What is Kotlin?'}
entry_point = 'echo {input_text}'

import shlex
text = inputs.get('input', '')
cmd = entry_point.replace('{input_text}', shlex.quote(text))
print(f'Command: {cmd}')
# Expected: echo 'What is Kotlin?'

# Test with special characters
inputs2 = {'input': \"What's 2+2? And how about 'quotes'?\"}
text2 = inputs2.get('input', '')
cmd2 = entry_point.replace('{input_text}', shlex.quote(text2))
print(f'Command: {cmd2}')
# Expected: echo 'What'\\''s 2+2? And how about '\\''quotes'\\''?'
"
```

- [ ] **Step 3: Commit**

```bash
git add tools/run_eval.py
git commit -m "fix: add {input_text} placeholder — extracts plain text for agents expecting --query"
```

---

### Task 2: Canary run preflight in `run_eval.py` (P1)

**Files:**
- Modify: `tools/run_eval.py:163-206`

OpenAI report #6: 160 API calls wasted on a broken agent. Add a canary: run 1 example first, verify it produces valid output, bail if not.

- [ ] **Step 1: Add `--no-canary` flag and canary logic**

In `tools/run_eval.py`, add the flag to argparse (after line 169):

```python
    parser.add_argument("--no-canary", action="store_true", help="Skip canary preflight check")
```

Then add canary logic after `target` and `evaluators` are created (after line 184, before the `print` block):

```python
    # Canary run: verify agent works before burning through full dataset
    if not args.no_canary:
        print("  Canary: running 1 example preflight...", file=sys.stderr)
        try:
            canary_examples = list(client.list_examples(dataset_name=config["dataset"], limit=1))
            if canary_examples:
                canary_result = target(canary_examples[0].inputs)
                canary_output = canary_result.get("output", "")
                canary_error = canary_result.get("error", "")
                if not canary_output and canary_error:
                    print(f"  CANARY FAILED: Agent produced no output.", file=sys.stderr)
                    print(f"  Error: {canary_error}", file=sys.stderr)
                    print(f"  Fix the agent before running full evaluation.", file=sys.stderr)
                    output = {
                        "experiment": None,
                        "prefix": args.experiment_prefix,
                        "combined_score": 0.0,
                        "error": f"Canary failed: {canary_error[:200]}",
                    }
                    print(json.dumps(output))
                    sys.exit(2)
                else:
                    print(f"  Canary passed: got output ({len(canary_output)} chars)", file=sys.stderr)
        except Exception as e:
            print(f"  Canary check failed: {e} (proceeding anyway)", file=sys.stderr)
```

- [ ] **Step 2: Test canary with a working command**

```bash
# This should pass canary (echo always produces output)
python3 tools/run_eval.py \
    --config playground/react-agent/.evolver.json \
    --worktree-path playground/react-agent \
    --experiment-prefix canary-test \
    --timeout 10 2>&1 | head -5
```

Expected: "Canary passed: got output" in stderr.

- [ ] **Step 3: Commit**

```bash
git add tools/run_eval.py
git commit -m "fix: canary preflight — run 1 example before full eval to catch broken agents"
```

---

### Task 3: Copy config files to worktrees before eval (P0)

**Files:**
- Modify: `skills/evolve/SKILL.md:340-357` (Step 3 — Run Target)

All 3 REPORTs hit this: `.evolver.json` and `.env` are untracked, so worktrees don't have them. Fix: copy them into each worktree before running eval.

- [ ] **Step 1: Add file propagation before eval in evolve skill**

In `skills/evolve/SKILL.md`, replace Step 3 "Run Target for Each Candidate" (lines 340-357):

```markdown
### 3. Run Target for Each Candidate (Parallel)

First, copy config files into each worktree (untracked files aren't replicated by git):

```bash
for WORKTREE in {worktree_paths_with_commits}; do
    WORKTREE_PROJECT="$WORKTREE"
    [ -n "$PROJECT_DIR" ] && WORKTREE_PROJECT="$WORKTREE/$PROJECT_DIR"

    # Copy config files that aren't tracked by git
    cp .evolver.json "$WORKTREE_PROJECT/.evolver.json" 2>/dev/null
    [ -f .env ] && cp .env "$WORKTREE_PROJECT/.env" 2>/dev/null
done
```

Then run evaluations for ALL candidates simultaneously:

```bash
for WORKTREE in {worktree_paths_with_commits}; do
    WORKTREE_PROJECT="$WORKTREE"
    [ -n "$PROJECT_DIR" ] && WORKTREE_PROJECT="$WORKTREE/$PROJECT_DIR"
    
    $EVOLVER_PY $TOOLS/run_eval.py \
        --config "$WORKTREE_PROJECT/.evolver.json" \
        --worktree-path "$WORKTREE_PROJECT" \
        --experiment-prefix v{NNN}-{lens_id} \
        --timeout 120 &
done
wait  # Wait for all evaluations to complete
```
```

- [ ] **Step 2: Also copy .env into worktrees for proposers**

In `skills/evolve/SKILL.md`, in the shared proposer context section (around line 240), add a note BEFORE the Agent() call for each proposer:

After the `<output>` block in the proposer prompt template (line 299), add this instruction:

```markdown
**IMPORTANT**: After each proposer worktree is created but before the agent starts, copy essential untracked files:

```bash
# Run this for each worktree BEFORE the proposer agent starts reading files
WORKTREE_PROJECT="$WORKTREE"
[ -n "$PROJECT_DIR" ] && WORKTREE_PROJECT="$WORKTREE/$PROJECT_DIR"
cp .evolver.json "$WORKTREE_PROJECT/.evolver.json" 2>/dev/null
[ -f .env ] && cp .env "$WORKTREE_PROJECT/.env" 2>/dev/null
```

Since proposers are spawned with `isolation: "worktree"` and `run_in_background: true`, the copy must happen after the worktree path is known from the Agent result. If the Agent tool creates the worktree and returns the path in the same call, copy the files immediately after dispatch, before the agent reads .evolver.json.

Alternatively, include the full .evolver.json content in the `<context>` block so proposers don't need to read it from disk.
```

- [ ] **Step 3: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "fix: copy .evolver.json + .env to worktrees before eval and proposer runs"
```

---

### Task 4: LLM-judge on baseline (P1)

**Files:**
- Modify: `skills/evolve/SKILL.md:108-134` (pre-loop section)

ARAG report #4: baseline scored 1.0 from `has_output` only, making evolution think it was perfect. The LLM-judge (correctness) was never applied to the baseline. Fix: after step 0.6 (health check), check if baseline has LLM-judge scores. If not, trigger the evaluator agent.

- [ ] **Step 1: Add baseline LLM-judge step to evolve skill**

In `skills/evolve/SKILL.md`, add a new step 0.7 after step 0.6 (Dataset Health Check) and before step 0.8:

```markdown
### 0.7. Ensure Baseline Has LLM-Judge Scores

The baseline experiment (from setup) only runs code-based evaluators (has_output, token_efficiency). Without LLM-judge scores, the baseline score is inflated — any agent that produces text gets 1.0.

Check if LLM-based evaluators are configured and baseline needs scoring:

```bash
LLM_EVALS=$(python3 -c "import json; c=json.load(open('.evolver.json')); llm=[k for k in c['evaluators'] if k in ('correctness','conciseness')]; print(','.join(llm) if llm else '')")
BASELINE=$(python3 -c "import json; print(json.load(open('.evolver.json')).get('baseline_experiment', ''))")
```

If `LLM_EVALS` is non-empty and `BASELINE` exists, check if scores already exist:

```bash
HAS_SCORES=$($EVOLVER_PY $TOOLS/read_results.py --experiment "$BASELINE" --config .evolver.json 2>/dev/null | python3 -c "
import sys, json
try:
    r = json.load(sys.stdin)
    scores = set()
    for ex in r.get('per_example', {}).values():
        scores.update(ex.get('scores', {}).keys())
    # Check if LLM evaluators are already scored
    llm = set('$LLM_EVALS'.split(','))
    print('yes' if llm.issubset(scores) else 'no')
except: print('no')
")
```

If `HAS_SCORES` is "no", trigger the evaluator agent on the baseline:

```
Agent(
  subagent_type: "evolver-evaluator",
  description: "Score baseline with LLM-judge",
  prompt: "Experiments to evaluate: {baseline_experiment}. Evaluators: {llm_evaluator_list}. Framework: {framework}. Entry point: {entry_point}. Dataset: {dataset_name}. NOTE: This is the baseline — score it fairly so evolution has a meaningful starting point."
)
```

After the evaluator completes, re-read the baseline score and update `.evolver.json`:

```bash
$EVOLVER_PY $TOOLS/read_results.py --experiment "$BASELINE" --config .evolver.json --output best_results.json 2>/dev/null
NEW_SCORE=$(python3 -c "import json; print(json.load(open('best_results.json')).get('combined_score', 0))")
python3 -c "
import json
c = json.load(open('.evolver.json'))
c['best_score'] = float('$NEW_SCORE')
c['history'][0]['score'] = float('$NEW_SCORE')
json.dump(c, open('.evolver.json', 'w'), indent=2)
print(f'Baseline re-scored with LLM-judge: {float(\"$NEW_SCORE\"):.3f}')
"
```
```

- [ ] **Step 2: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "fix: run LLM-judge on baseline before evolution loop — prevent inflated has_output scores"
```

---

### Task 5: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document `{input_text}` and canary**

In the `## Running tools locally` section, update the `run_eval.py` entry:

```bash
# Run evaluation for a candidate in a worktree
python tools/run_eval.py --config .evolver.json --worktree-path /tmp/wt --experiment-prefix v001a
# Use --no-canary to skip preflight check
```

In the `## Key conventions` section, add:

```
- Entry points support three input placeholders: `{input}` (JSON file path), `{input_text}` (extracted plain text, shell-escaped), `{input_json}` (inline JSON string). Use `{input_text}` for agents that take `--query "text"` or positional text arguments.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document {input_text} placeholder and --no-canary flag"
```
