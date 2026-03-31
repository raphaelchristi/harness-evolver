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

### 1.5. Gather LangSmith Traces (MANDATORY after every evaluation)

**Run these commands unconditionally after EVERY evaluation** (including baseline). Do NOT guess project names — discover them.

**Step 1: Find the actual LangSmith project name**

```bash
langsmith-cli --json projects list --name-pattern "harness-evolver*" --limit 10 2>/dev/null
```

This returns all projects matching the prefix. Pick the most recently updated one, or the one matching the current version. Save the project name:

```bash
LS_PROJECT=$(langsmith-cli --json projects list --name-pattern "harness-evolver*" --limit 1 2>/dev/null | python3 -c "import sys,json; data=json.load(sys.stdin); print(data[0]['name'] if data else '')" 2>/dev/null || echo "")
```

If `LS_PROJECT` is empty, langsmith-cli is not available or no projects exist — skip to step 2.

**Step 2: Gather traces from the discovered project**

```bash
if [ -n "$LS_PROJECT" ]; then
  langsmith-cli --json runs list --project "$LS_PROJECT" --failed --fields id,name,error,inputs --limit 10 > .harness-evolver/langsmith_diagnosis.json 2>/dev/null || echo "[]" > .harness-evolver/langsmith_diagnosis.json
  langsmith-cli --json runs stats --project "$LS_PROJECT" > .harness-evolver/langsmith_stats.json 2>/dev/null || echo "{}" > .harness-evolver/langsmith_stats.json
  echo "$LS_PROJECT" > .harness-evolver/langsmith_project.txt
else
  echo "[]" > .harness-evolver/langsmith_diagnosis.json
  echo "{}" > .harness-evolver/langsmith_stats.json
fi
```

These files are included in the proposer's `<files_to_read>` so it has real trace data for diagnosis.

### 2. Propose (3 parallel candidates)

Spawn 3 proposer agents IN PARALLEL, each with a different evolutionary strategy.
This follows the DGM/AlphaEvolve pattern: exploit + explore + crossover.

First, read the proposer agent definition:
```bash
cat ~/.claude/agents/harness-evolver-proposer.md
```

Then determine parents for each strategy:
- **Exploiter parent**: current best version (from summary.json `best.version`)
- **Explorer parent**: a non-best version with low offspring count (read summary.json history, pick one that scored >0 but is NOT the best and has NOT been parent to many children)
- **Crossover parents**: best version + a different high-scorer from a different lineage

Spawn all 3 using the Agent tool. The first 2 use `run_in_background: true`, the 3rd blocks:

**Candidate A (Exploiter)** — `run_in_background: true`:
```
Agent(
  description: "Proposer A (exploit): targeted fix for {version}",
  run_in_background: true,
  prompt: |
    <agent_instructions>
    {FULL content of harness-evolver-proposer.md}
    </agent_instructions>

    <strategy>
    APPROACH: exploitation
    You are the EXPLOITER. Make the SMALLEST, most targeted change that fixes
    the highest-impact failing tasks. Base your work on the current best version.
    Do NOT restructure the code. Do NOT change the architecture.
    Focus on: prompt tweaks, parameter tuning, fixing specific failure modes.
    </strategy>

    <objective>
    Propose harness version {version}a that improves on {best_score}.
    </objective>

    <files_to_read>
    - .harness-evolver/summary.json
    - .harness-evolver/PROPOSER_HISTORY.md
    - .harness-evolver/config.json
    - .harness-evolver/harnesses/{best_version}/harness.py
    - .harness-evolver/harnesses/{best_version}/scores.json
    - .harness-evolver/harnesses/{best_version}/proposal.md
    - .harness-evolver/langsmith_diagnosis.json (if exists)
    - .harness-evolver/langsmith_stats.json (if exists)
    - .harness-evolver/architecture.json (if exists)
    </files_to_read>

    <output>
    Create directory .harness-evolver/harnesses/{version}a/ containing:
    - harness.py, config.json, proposal.md
    </output>
)
```

**Candidate B (Explorer)** — `run_in_background: true`:
```
Agent(
  description: "Proposer B (explore): bold change from {explorer_parent}",
  run_in_background: true,
  prompt: |
    <agent_instructions>
    {FULL content of harness-evolver-proposer.md}
    </agent_instructions>

    <strategy>
    APPROACH: exploration
    You are the EXPLORER. Try a FUNDAMENTALLY DIFFERENT approach.
    Base your work on {explorer_parent} (NOT the current best — intentionally diverging).
    Consider: different retrieval strategy, different prompt structure,
    different output parsing, different error handling philosophy.
    Be bold. A creative failure teaches more than a timid success.
    </strategy>

    <objective>
    Propose harness version {version}b that takes a different approach.
    </objective>

    <files_to_read>
    - .harness-evolver/summary.json
    - .harness-evolver/PROPOSER_HISTORY.md
    - .harness-evolver/config.json
    - .harness-evolver/baseline/harness.py
    - .harness-evolver/harnesses/{explorer_parent}/harness.py
    - .harness-evolver/harnesses/{explorer_parent}/scores.json
    - .harness-evolver/langsmith_diagnosis.json (if exists)
    - .harness-evolver/architecture.json (if exists)
    </files_to_read>

    <output>
    Create directory .harness-evolver/harnesses/{version}b/ containing:
    - harness.py, config.json, proposal.md
    </output>
)
```

**Candidate C (Crossover)** — blocks (last one):
```
Agent(
  description: "Proposer C (crossover): combine {parent_a} + {parent_b}",
  prompt: |
    <agent_instructions>
    {FULL content of harness-evolver-proposer.md}
    </agent_instructions>

    <strategy>
    APPROACH: crossover
    You are the CROSSOVER agent. Combine the STRENGTHS of two different versions:
    - {parent_a} (score: {score_a}): {summary of what it does well}
    - {parent_b} (score: {score_b}): {summary of what it does well}
    Take the best elements from each and merge them into a single harness.
    </strategy>

    <objective>
    Propose harness version {version}c that combines the best of {parent_a} and {parent_b}.
    </objective>

    <files_to_read>
    - .harness-evolver/summary.json
    - .harness-evolver/PROPOSER_HISTORY.md
    - .harness-evolver/config.json
    - .harness-evolver/harnesses/{parent_a}/harness.py
    - .harness-evolver/harnesses/{parent_a}/scores.json
    - .harness-evolver/harnesses/{parent_b}/harness.py
    - .harness-evolver/harnesses/{parent_b}/scores.json
    - .harness-evolver/langsmith_diagnosis.json (if exists)
    - .harness-evolver/architecture.json (if exists)
    </files_to_read>

    <output>
    Create directory .harness-evolver/harnesses/{version}c/ containing:
    - harness.py, config.json, proposal.md
    </output>
)
```

**Also spawn these additional candidates:**

**Candidate D (Prompt Specialist)** — `run_in_background: true`:
Same as Exploiter but with a different focus:
```
<strategy>
APPROACH: prompt-engineering
You are the PROMPT SPECIALIST. Focus ONLY on improving the system prompt,
few-shot examples, output format instructions, and prompt structure.
Do NOT change the retrieval logic, pipeline structure, or code architecture.
</strategy>
```
Output to: `.harness-evolver/harnesses/{version}d/`

**Candidate E (Data/Retrieval Specialist)** — `run_in_background: true`:
```
<strategy>
APPROACH: retrieval-optimization  
You are the RETRIEVAL SPECIALIST. Focus ONLY on improving how data is
retrieved, filtered, ranked, and presented to the LLM. 
Do NOT change the system prompt text or output formatting.
Improve: search logic, relevance scoring, cross-domain retrieval, chunking.
</strategy>
```
Output to: `.harness-evolver/harnesses/{version}e/`

Wait for all 5 to complete. The background agents will notify when done.

**Minimum 3 candidates ALWAYS, even on iteration 1.** On iteration 1, the crossover agent uses baseline as both parents but with instruction to "combine the best retrieval strategy with the best prompt strategy from your analysis of the baseline." On iteration 2+, crossover uses two genuinely different parents.

**On iteration 3+**: If scores are improving, keep all 5 strategies. If stagnating, replace Candidate D with a "Radical" strategy that rewrites the harness from scratch.

### 3. Validate All Candidates

For each candidate (a, b, c, d, e):
```bash
python3 $TOOLS/evaluate.py validate --harness .harness-evolver/harnesses/{version}{suffix}/harness.py --config .harness-evolver/harnesses/{version}{suffix}/config.json
```

Remove any that fail validation.

### 4. Evaluate All Candidates

For each valid candidate:
```bash
python3 $TOOLS/evaluate.py run \
    --harness .harness-evolver/harnesses/{version}{suffix}/harness.py \
    --config .harness-evolver/harnesses/{version}{suffix}/config.json \
    --tasks-dir .harness-evolver/eval/tasks/ \
    --eval .harness-evolver/eval/eval.py \
    --traces-dir .harness-evolver/harnesses/{version}{suffix}/traces/ \
    --scores .harness-evolver/harnesses/{version}{suffix}/scores.json \
    --timeout 60
```

### 5. Select Winner + Update State

Compare scores of all evaluated candidates. The winner is the one with highest combined_score.

Rename the winner directory to the official version name:
```bash
mv .harness-evolver/harnesses/{version}{winning_suffix} .harness-evolver/harnesses/{version}
```

Update state with the winner:
```bash
python3 $TOOLS/state.py update \
    --base-dir .harness-evolver \
    --version {version} \
    --scores .harness-evolver/harnesses/{version}/scores.json \
    --proposal .harness-evolver/harnesses/{version}/proposal.md
```

Report ALL candidates:
```
Iteration {i}/{N} — 3 candidates evaluated:
  {version}a (exploit): {score_a} — {1-line summary from proposal.md}
  {version}b (explore): {score_b} — {1-line summary}
  {version}c (cross):   {score_c} — {1-line summary}
  Winner: {version}{suffix} ({score}) ← promoted to {version}
```

Keep losing candidates in their directories (they're part of the archive — never discard, per DGM).

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

First read the critic agent definition:
```bash
cat ~/.claude/agents/harness-evolver-critic.md
```

Then dispatch:

```
Agent(
  description: "Critic: analyze eval quality",
  prompt: |
    <agent_instructions>
    {paste the FULL content of harness-evolver-critic.md here}
    </agent_instructions>

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

First read the architect agent definition:
```bash
cat ~/.claude/agents/harness-evolver-architect.md
```

Then dispatch:

```
Agent(
  description: "Architect: analyze topology after {stagnation/regression}",
  prompt: |
    <agent_instructions>
    {paste the FULL content of harness-evolver-architect.md here}
    </agent_instructions>

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
