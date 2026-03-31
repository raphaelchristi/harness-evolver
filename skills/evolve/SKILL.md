---
name: harness-evolver:evolve
description: "Use when the user wants to run the optimization loop, improve harness performance, evolve the harness, or iterate on harness quality. Requires .harness-evolver/ to exist (run harness-evolver:init first)."
argument-hint: "[--iterations N]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent]
---

# /harness-evolver:evolve

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

### 1.5. Gather Diagnostic Context (LangSmith + Context7)

**This step is MANDATORY before every propose.** The orchestrator gathers data so the proposer receives it as files.

**LangSmith (if enabled):**

Check if LangSmith is enabled and langsmith-cli is available:
```bash
cat .harness-evolver/config.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('eval',{}).get('langsmith',{}).get('enabled',False))"
which langsmith-cli 2>/dev/null
```

If BOTH are true AND at least one iteration has run, gather LangSmith data:
```bash
langsmith-cli --json runs list --project harness-evolver-{best_version} --failed --fields id,name,error,inputs --limit 10 > .harness-evolver/langsmith_diagnosis.json 2>/dev/null || echo "[]" > .harness-evolver/langsmith_diagnosis.json

langsmith-cli --json runs stats --project harness-evolver-{best_version} > .harness-evolver/langsmith_stats.json 2>/dev/null || echo "{}" > .harness-evolver/langsmith_stats.json
```

**Context7 (if available):**

Check `config.json` field `stack.detected`. For each detected library, use the Context7 MCP tools to fetch relevant documentation:

```
For each library in stack.detected:
  1. resolve-library-id with the context7_id
  2. get-library-docs with a query relevant to the current failure modes
  3. Save output to .harness-evolver/context7_docs.md (append each library's docs)
```

This runs ONCE per iteration, not per library. Focus on the library most relevant to the current failures.

If Context7 MCP is not available, skip silently.

### 2. Propose

Dispatch a subagent using the **Agent tool** with `subagent_type: "harness-evolver-proposer"`.

The prompt MUST be the full XML block below. The `<files_to_read>` MUST include the LangSmith/Context7 files if they were gathered in step 1.5.

```
Agent(
  subagent_type: "harness-evolver-proposer",
  description: "Propose harness {version}",
  prompt: |
    <objective>
    Propose harness version {version} that improves on the current best score of {best_score}.
    </objective>

    <files_to_read>
    - .harness-evolver/summary.json
    - .harness-evolver/PROPOSER_HISTORY.md
    - .harness-evolver/config.json
    - .harness-evolver/baseline/harness.py
    - .harness-evolver/harnesses/{best_version}/harness.py
    - .harness-evolver/harnesses/{best_version}/scores.json
    - .harness-evolver/harnesses/{best_version}/proposal.md
    - .harness-evolver/langsmith_diagnosis.json (if exists — LangSmith failure analysis)
    - .harness-evolver/langsmith_stats.json (if exists — LangSmith aggregate stats)
    - .harness-evolver/context7_docs.md (if exists — current library documentation)
    - .harness-evolver/architecture.json (if exists — architect topology recommendation)
    </files_to_read>

    <output>
    Create directory .harness-evolver/harnesses/{version}/ containing:
    - harness.py (the improved harness)
    - config.json (parameters, copy from parent if unchanged)
    - proposal.md (reasoning, must start with "Based on v{PARENT}")
    </output>

    <success_criteria>
    - harness.py maintains CLI interface (--input, --output, --traces-dir, --config)
    - proposal.md documents evidence-based reasoning
    - Changes are motivated by trace analysis (LangSmith data if available), not guesswork
    - If context7_docs.md was provided, API usage must match current documentation
    </success_criteria>
)
```

Wait for `## PROPOSAL COMPLETE` in the response. The subagent gets a fresh context window and loads the agent definition from `~/.claude/agents/harness-evolver-proposer.md`.

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

### 6.5. Auto-trigger Critic (on eval gaming)

Read `summary.json` and check:
- Did the score jump >0.3 from parent version?
- Did we reach 1.0 in fewer than 3 total iterations?

If EITHER is true, **AUTO-SPAWN the critic agent** (do not just suggest — actually spawn it):

```bash
python3 $TOOLS/evaluate.py run \
    --harness .harness-evolver/harnesses/{version}/harness.py \
    --tasks-dir .harness-evolver/eval/tasks/ \
    --eval .harness-evolver/eval/eval.py \
    --traces-dir /tmp/critic-check/ \
    --scores /tmp/critic-check-scores.json \
    --timeout 60
```

Dispatch critic subagent using the **Agent tool** with `subagent_type: "harness-evolver-critic"`:

```
Agent(
  subagent_type: "harness-evolver-critic",
  description: "Critic: analyze eval quality",
  prompt: |
    <objective>
    EVAL GAMING DETECTED: Score jumped from {parent_score} to {score} in one iteration.
    Analyze the eval quality and propose a stricter eval.
    </objective>

    <files_to_read>
    - .harness-evolver/eval/eval.py
    - .harness-evolver/summary.json
    - .harness-evolver/harnesses/{version}/scores.json
    - .harness-evolver/harnesses/{version}/harness.py
    - .harness-evolver/harnesses/{version}/proposal.md
    - .harness-evolver/config.json
    - .harness-evolver/langsmith_stats.json (if exists)
    </files_to_read>

    <output>
    Write:
    - .harness-evolver/critic_report.md
    - .harness-evolver/eval/eval_improved.py (if weaknesses found)
    </output>

    <success_criteria>
    - Identifies specific weaknesses in eval.py with task/output examples
    - If gaming detected, shows exact tasks that expose the weakness
    - Improved eval preserves the --results-dir/--tasks-dir/--scores interface
    - Re-scores the best version with improved eval to show the difference
    </success_criteria>
)
```

Wait for `## CRITIC REPORT COMPLETE`.

If critic wrote `eval_improved.py`:
- Re-score the best harness with the improved eval
- Show the score difference (e.g., "Current eval: 1.0. Improved eval: 0.45")
- **AUTO-ADOPT the improved eval**: copy `eval_improved.py` to `eval/eval.py`
- Re-run baseline with new eval and update `summary.json`
- Print: "Eval upgraded. Resuming evolution with stricter eval."
- **Continue the loop** with the new eval

If critic did NOT write `eval_improved.py` (eval is fine):
- Print the critic's assessment
- Continue the loop normally

### 7. Auto-trigger Architect (on stagnation or regression)

Check if the architect should be auto-spawned:
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

Dispatch architect subagent using the **Agent tool** with `subagent_type: "harness-evolver-architect"`:

```
Agent(
  subagent_type: "harness-evolver-architect",
  description: "Architect: analyze topology after {stagnation/regression}",
  prompt: |
    <objective>
    The evolution loop has {stagnated/regressed} after {iterations} iterations (best: {best_score}).
    Analyze the harness architecture and recommend a topology change.
    </objective>

    <files_to_read>
    - .harness-evolver/architecture_signals.json
    - .harness-evolver/summary.json
    - .harness-evolver/PROPOSER_HISTORY.md
    - .harness-evolver/config.json
    - .harness-evolver/harnesses/{best_version}/harness.py
    - .harness-evolver/harnesses/{best_version}/scores.json
    - .harness-evolver/context7_docs.md (if exists)
    </files_to_read>

    <output>
    Write:
    - .harness-evolver/architecture.json (structured recommendation)
    - .harness-evolver/architecture.md (human-readable analysis)
    </output>

    <success_criteria>
    - Recommendation includes concrete migration steps
    - Each step is implementable in one proposer iteration
    - Considers detected stack and available API keys
    </success_criteria>
)
```

Wait for `## ARCHITECTURE ANALYSIS COMPLETE`.

Report: `Architect recommends: {current} → {recommended} ({confidence} confidence)`

Then **continue the loop** — the proposer reads `architecture.json` in the next iteration.

### 8. Check Stop Conditions

- **Target**: `combined_score >= target_score` → stop
- **N reached**: done
- **Stagnation post-architect**: 3 more iterations without improvement AFTER architect ran → stop

## When Loop Ends — Final Report

- Best version and score
- Improvement over baseline (absolute and %)
- Total iterations run
- Whether critic was triggered and eval was upgraded
- Whether architect was triggered and what it recommended
- Suggest: "The best harness is at `.harness-evolver/harnesses/{best}/harness.py`. Copy it to your project."
