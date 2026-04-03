---
name: evolver:evolve
description: "Use when the user wants to run the optimization loop, improve agent performance, evolve the agent, or iterate on quality. Requires .evolver.json to exist (run evolver:setup first)."
argument-hint: "[--iterations N]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion]
---

# /evolver:evolve

Run the propose-evaluate-iterate loop. LangSmith is the evaluation backend, git worktrees provide isolation.

## Setup

`.evolver.json` must exist. If not, tell user to run `evolver:setup`.

```bash
TOOLS="${EVOLVER_TOOLS:-$([ -d ".evolver/tools" ] && echo ".evolver/tools" || echo "$HOME/.evolver/tools")}"
EVOLVER_PY="${EVOLVER_PY:-$([ -f "$HOME/.evolver/venv/bin/python" ] && echo "$HOME/.evolver/venv/bin/python" || echo "python3")}"
```

**Never pass `LANGSMITH_API_KEY` inline.** Tools resolve it automatically via `_common.ensure_langsmith_api_key()`.

## Arguments

- `--iterations N` (default: ask or 5)
- `--no-interactive` — skip prompts, use defaults (for cron/background runs)

If interactive, ask iterations (3/5/10), target score (0.8/0.9/0.95/none), and mode (interactive/background).

## Pre-Loop

### Preflight

```bash
$EVOLVER_PY $TOOLS/preflight.py --config .evolver.json
```

Validates API key, config schema, LangSmith state, dataset health, and canary in one pass. If it fails, ask user: fix and retry, continue anyway, or abort. If health issues are auto-correctable, run `/evolver:health` first.

### Baseline LLM-Judge

If LLM evaluators (correctness, conciseness) are configured but baseline only has code-based scores, spawn the evaluator agent on the baseline experiment. Re-read and update `best_score` in `.evolver.json` after scoring.

### Resolve Project Directory

Read `project_dir` from config. If non-empty, all worktree paths include it: `{worktree}/{project_dir}/`.

## The Loop (per iteration)

### 0. Read State

```bash
BEST=$(python3 -c "import json; b=json.load(open('.evolver.json')).get('best_experiment'); print(b if b else '')")
PROJECT_DIR=$(python3 -c "import json; print(json.load(open('.evolver.json')).get('project_dir', ''))")
```

If `$BEST` is empty (no baseline ran), skip data gathering — proposers work from code analysis only.

### 1. Gather Data (parallel)

```bash
if [ -n "$BEST" ]; then
    $EVOLVER_PY $TOOLS/trace_insights.py --from-experiment "$BEST" --format summary --output trace_insights.json &
    $EVOLVER_PY $TOOLS/read_results.py --experiment "$BEST" --config .evolver.json --split train --format summary --output best_results.json &
    wait
fi
```

Use `--format summary` to keep context compact (~200 tokens vs ~5K). Full data stays on disk for proposers to read on demand.

### 2. Generate Strategy + Lenses

From trace_insights.json, best_results.json, evolution_memory.md, production_seed.json:

**strategy.md** — Current iteration data ONLY. No stale info. Contents: target files, failure clusters (latest experiment), top 3 promoted memory insights (rec >= 2), approaches to avoid, top 3 failing examples with judge feedback. **Cap at 1500 tokens.**

**lenses.json** — Investigation questions for proposers:
- One per failure cluster (max 3), one architecture, one production, one evolution_memory, one open
- If `evolution_archive/` has 3+ iterations, one `archive_branch` lens that suggests revisiting a losing candidate's approach
- Sort by severity, cap at 5 lenses

### 3. Spawn Proposers (two-wave, parallel worktrees)

Build IDENTICAL shared prefix (objective + files_to_read + context) for KV-cache sharing. Only the `<lens>` block differs — place it LAST. Include `evolution_archive/` in `<files_to_read>` so proposers can grep prior candidates.

**Wave 1** — critical + high severity lenses, run independently in parallel:

```
Agent(
  subagent_type: "evolver-proposer",
  isolation: "worktree",
  run_in_background: true,
  prompt: "{SHARED_PREFIX}\n\n<lens>\n{lens.question}\nSource: {lens.source}\n</lens>"
)
```

Wait for wave 1 to complete. Report each completion as it happens.

**Wave 2** — medium + open lenses, see wave 1 results before starting:

Add to the shared context for wave 2 proposers:
```
<prior_proposals>
Wave 1 proposers completed:
- Proposer {id} ({lens}): {approach from proposal.md} — {committed/abstained}
...
</prior_proposals>
```

Wave 2 proposers see what wave 1 tried and can build on it, avoid duplication, or take complementary approaches. Research shows +14% quality when agents observe prior outputs.

If only 1-2 lenses total, run as single wave.

### 4. Evaluate Candidates

Copy `.evolver.json` + `.env` to worktrees (run_eval.py also auto-copies if missing). Resolve `project_dir` for subdirectory projects:

```bash
for WT in {worktree_paths_with_commits}; do
    WT_PROJECT="$WT"
    [ -n "$PROJECT_DIR" ] && WT_PROJECT="$WT/$PROJECT_DIR"
    cp .evolver.json "$WT_PROJECT/.evolver.json" 2>/dev/null
    [ -f .env ] && cp .env "$WT_PROJECT/.env" 2>/dev/null
    $EVOLVER_PY $TOOLS/run_eval.py --config "$WT_PROJECT/.evolver.json" --worktree-path "$WT_PROJECT" --experiment-prefix v{NNN}-{id} &
done
wait  # CRITICAL: wait for ALL evals before judge
```

Then spawn evaluator agent for LLM-as-judge (if configured):

```
Agent(
  subagent_type: "evolver-evaluator",
  prompt: "Experiments: {names}. Evaluators: {list}. Dataset: {name}. Use rubrics from example metadata when available."
)
```

Wait for evaluator to complete before comparing.

### 5. Compare + Constraint Gate + Merge

```bash
$EVOLVER_PY $TOOLS/read_results.py --experiments "{names}" --config .evolver.json --split held_out --output comparison.json
```

Winner = highest score on held-out data. Report Pareto front and diversity grid if multiple non-dominated candidates.

If top 2 candidates are within 5% of each other, run pairwise comparison to confirm:
```bash
$EVOLVER_PY $TOOLS/read_results.py --pairwise "{winner},{runner_up}" --config .evolver.json
```
If pairwise disagrees with independent scoring, flag for user review.

Resolve `project_dir` for constraint worktree path. Baseline stays `.` because CWD is already the project directory:
```bash
WINNER_PROJECT="{winner_wt}"
[ -n "$PROJECT_DIR" ] && WINNER_PROJECT="{winner_wt}/$PROJECT_DIR"
$EVOLVER_PY $TOOLS/constraint_check.py --config .evolver.json --worktree-path "$WINNER_PROJECT" --baseline-path "."
```

If constraints fail, try next-best. If none pass, skip merge.

If winner beats current best: `git merge`, update `.evolver.json` with enriched history (score, tokens, latency, errors, passing, total, per_evaluator, approach, lens, code_loc).

### 6. Post-Iteration

**Archive ALL candidates** (winners and losers) for future proposer reference:
```bash
for CANDIDATE in {all_worktree_paths}; do
    $EVOLVER_PY $TOOLS/archive.py --config .evolver.json --version v{NNN}-{id} --experiment "{exp}" --worktree-path "$CANDIDATE" --score {score} --approach "{approach}" --lens "{lens}" $([ "{exp}" = "{winner}" ] && echo "--won")
done
```

**Regression tracking** (if not first iteration):
```bash
$EVOLVER_PY $TOOLS/regression_tracker.py --config .evolver.json --previous-experiment "$PREV" --current-experiment "$WINNER" --add-guards --auto-guard-failures --max-guards 5
```

**Report**: `Iteration {i}/{N}: v{NNN} scored {score} (best: {best_score})`

**Consolidate** (background):
```
Agent(subagent_type: "evolver-consolidator", run_in_background: true, prompt: "Update evolution_memory.md...")
```

**Auto-trigger critic** if score jumped >0.3 or hit target in <3 iterations.

**Auto-trigger architect** (opus model) if 3 consecutive iterations within 1% or score dropped.

### 7. Gate Check

- **Plateau**: 3 scores within 2% → consider architect or stop
- **Target reached**: `best_score >= target_score` → stop
- **Diminishing returns**: avg improvement <0.5% over 5 iterations → stop

## Final Report

```bash
$EVOLVER_PY $TOOLS/evolution_chart.py --config .evolver.json
```

Plus: LangSmith URL, `git log --oneline` summary, suggest `/evolver:deploy`.
