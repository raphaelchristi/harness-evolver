---
name: harness:evolve
description: "Use when the user wants to run the optimization loop, improve agent performance, evolve the agent, or iterate on quality. Requires .evolver.json to exist (run harness:setup first)."
argument-hint: "[--iterations N]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion]
---

# /harness:evolve

Run the propose-evaluate-iterate loop. LangSmith is the evaluation backend, git worktrees provide isolation.

## Setup

`.evolver.json` must exist. If not, tell user to run `harness:setup`.

```bash
TOOLS="${EVOLVER_TOOLS:-$([ -d ".evolver/tools" ] && echo ".evolver/tools" || echo "$HOME/.evolver/tools")}"
EVOLVER_PY="${EVOLVER_PY:-$([ -f "$HOME/.evolver/venv/bin/python" ] && echo "$HOME/.evolver/venv/bin/python" || echo "python3")}"
```

**Never pass `LANGSMITH_API_KEY` inline.** Tools resolve it automatically via `_common.ensure_langsmith_api_key()`.

## Arguments

- `--iterations N` (default: ask or 5)
- `--mode light|balanced|heavy` — override mode from config
- `--no-interactive` — skip prompts, use defaults (for cron/background runs)

If interactive, ask iterations (3/5/10), target score (0.8/0.9/0.95/none), and execution mode (interactive/background).

## Mode Parameters

```
MODES = {
  "light":    {"proposers": 2, "waves": 1, "concurrency": 5, "timeout": 60, "sample": 10, "analysis": "summary", "pairwise": False, "archive": "winner"},
  "balanced": {"proposers": 3, "waves": 2, "concurrency": 3, "timeout": 120, "sample": None, "analysis": "summary", "pairwise": "if_close", "archive": "all"},
  "heavy":    {"proposers": 5, "waves": 2, "concurrency": 3, "timeout": 300, "sample": None, "analysis": "full", "pairwise": True, "archive": "all"},
}
```

Read mode from config, allow `--mode` override:
```bash
MODE=$(python3 -c "import json; print(json.load(open('.evolver.json')).get('mode', 'balanced'))")
```

If not `--no-interactive`, confirm or switch:
```json
{
  "question": "Mode: {MODE}. Continue?",
  "header": "Mode",
  "options": [
    {"label": "Yes, continue with {MODE}"},
    {"label": "Switch to light (~2 min/iter)"},
    {"label": "Switch to balanced (~8 min/iter)"},
    {"label": "Switch to heavy (~25 min/iter)"}
  ]
}
```

If changed, update config and re-read MODE.

## Pre-Loop

### Preflight

```bash
$EVOLVER_PY $TOOLS/preflight.py --config .evolver.json
```

Validates API key, config schema, LangSmith state, dataset health, and canary in one pass. If it fails, ask user: fix and retry, continue anyway, or abort. If health issues are auto-correctable, run `/harness:health` first.

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

Analysis format depends on mode (`MODES[MODE]["analysis"]`):

```bash
if [ -n "$BEST" ]; then
    ANALYSIS_FMT=$(python3 -c "m={'light':'summary','balanced':'summary','heavy':'full'}; print(m.get('$MODE','summary'))")
    $EVOLVER_PY $TOOLS/trace_insights.py --from-experiment "$BEST" --format $ANALYSIS_FMT --output trace_insights.json &
    $EVOLVER_PY $TOOLS/read_results.py --experiment "$BEST" --config .evolver.json --split train --format $ANALYSIS_FMT --output best_results.json &
    wait
fi
```

### 2. Generate Strategy + Lenses

From trace_insights.json, best_results.json, evolution_memory.md, production_seed.json:

**strategy.md** — Current iteration data ONLY. No stale info. Contents: target files, failure clusters (latest experiment), top 3 promoted memory insights (rec >= 2), approaches to avoid, top 3 failing examples with judge feedback. **Cap at 1500 tokens.**

**lenses.json** — Investigation questions for proposers:
- One per failure cluster (max 3), one architecture, one production, one evolution_memory, one open
- If `evolution_archive/` has 3+ iterations, one `archive_branch` lens that suggests revisiting a losing candidate's approach
- Sort by severity, cap at 5 lenses

### 3. Spawn Proposers (mode-dependent)

Proposer count: `MODES[MODE]["proposers"]` (light=2, balanced=3, heavy=5). Cap lenses at this number.
Waves: `MODES[MODE]["waves"]` (light=1 single wave, balanced/heavy=2 two-wave).

Build IDENTICAL shared prefix (objective + files_to_read + context) for KV-cache sharing. Only the `<lens>` block differs — place it LAST. Include `evolution_archive/` in `<files_to_read>` so proposers can grep prior candidates.

**IMPORTANT**: After each proposer worktree is created, copy untracked files BEFORE the agent starts reading. Always use **absolute paths** (relative paths fail when Bash CWD differs from project root):
```bash
SRC="$(pwd)"
# For each worktree (after Agent creates it, before agent reads files):
cp "$SRC/.evolver.json" "$WT_PROJECT/.evolver.json"
[ -f "$SRC/.env" ] && cp "$SRC/.env" "$WT_PROJECT/.env"
[ -d "$SRC/evolution_archive" ] && cp -r "$SRC/evolution_archive" "$WT_PROJECT/evolution_archive"
```
Do NOT suppress stderr with `2>/dev/null` — if the copy fails, you need to see the error.

**Wave 1** — critical + high severity lenses, run independently in parallel:

```
Agent(
  subagent_type: "harness-proposer",
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

Run evaluations with mode parameters. `run_eval.py` auto-copies config files to worktrees:

```bash
CONCURRENCY=$(python3 -c "m={'light':5,'balanced':3,'heavy':3}; print(m.get('$MODE',3))")
TIMEOUT=$(python3 -c "m={'light':60,'balanced':120,'heavy':300}; print(m.get('$MODE',120))")
SAMPLE=$(python3 -c "m={'light':'10','balanced':'','heavy':''}; s=m.get('$MODE',''); print(f'--sample {s}' if s else '')")

for WT in {worktree_paths_with_commits}; do
    WT_PROJECT="$WT"
    [ -n "$PROJECT_DIR" ] && WT_PROJECT="$WT/$PROJECT_DIR"
    $EVOLVER_PY $TOOLS/run_eval.py --config "$(pwd)/.evolver.json" --worktree-path "$WT_PROJECT" --experiment-prefix v{NNN}-{id} --concurrency $CONCURRENCY --timeout $TIMEOUT $SAMPLE &
done
wait  # CRITICAL: wait for ALL evals before judge
```

Note: always pass `--config` with **absolute path** (`$(pwd)/.evolver.json`). The Bash tool's CWD may differ from the project root, causing relative paths to fail silently.

**Auto-spawn LLM-as-judge** — check if LLM evaluators are configured and automatically spawn the evaluator agent. Do NOT leave this as a manual step for the user:

```bash
LLM_EVALS=$(python3 -c "import json; c=json.load(open('.evolver.json')); llm=[k for k in c['evaluators'] if k in ('correctness','conciseness')]; print(','.join(llm) if llm else '')")
```

If `LLM_EVALS` is non-empty, spawn the evaluator agent immediately after evals complete:

```
Agent(
  subagent_type: "harness-evaluator",
  prompt: "Experiments: {names}. Evaluators: {LLM_EVALS}. Dataset: {dataset_name}. Use rubrics from example metadata when available."
)
```

Wait for evaluator to complete before comparing. This is NOT optional — the combined score is meaningless without LLM-judge scores.

### 5. Compare + Constraint Gate + Merge

```bash
$EVOLVER_PY $TOOLS/read_results.py --experiments "{names}" --config .evolver.json --split held_out --output comparison.json
```

Winner = highest score on held-out data. Report Pareto front and diversity grid if multiple non-dominated candidates.

Pairwise comparison (mode-dependent: light=never, balanced=if top 2 within 5%, heavy=always):
```bash
$EVOLVER_PY $TOOLS/read_results.py --pairwise "{winner},{runner_up}" --config .evolver.json --split held_out
```
If pairwise disagrees with independent scoring, flag for user review.

Resolve `project_dir` for constraint worktree path. Baseline stays `.` because CWD is already the project directory:
```bash
WINNER_PROJECT="{winner_wt}"
[ -n "$PROJECT_DIR" ] && WINNER_PROJECT="{winner_wt}/$PROJECT_DIR"
$EVOLVER_PY $TOOLS/constraint_check.py --config .evolver.json --worktree-path "$WINNER_PROJECT" --baseline-path "."
```

If constraints fail, try next-best. If none pass, skip merge.

**Efficiency gate** (before merge): Check if winner's tokens or latency regressed significantly:
- If tokens increased >2x AND score improved <2%: reject this candidate, try next-best
- If latency increased >50% AND score improved <5%: reject this candidate, try next-best
- In interactive mode: ask user to override if desired. In background mode: auto-reject.

If winner beats current best AND passes efficiency gate: `git merge`, update `.evolver.json` with enriched history (score, tokens, latency, errors, passing, total, per_evaluator, approach, lens, code_loc). Then git-tag for rollback:

```bash
git tag "evo-iter-v{NNN}" -m "harness: v{NNN} score={score}"
```

Note: uses `evo-iter-` prefix to avoid conflicts with `/harness:deploy` tags.

### 6. Post-Iteration

**Archive candidates** (light=winner only, balanced/heavy=all) for future proposer reference:
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
Agent(subagent_type: "harness-consolidator", run_in_background: true, prompt: "Update evolution_memory.md...")
```

**Proactive evaluator evolution**: After reading all proposal.md files, check for `## Suggested Evaluators` sections. If any proposer suggested new evaluators or rubrics, surface them:
```
Proposer v{NNN}-{id} suggested new evaluator: "{name}" — {description}
```
If multiple proposers suggest the same evaluator, prioritize it. **Do NOT add evaluators that have no implementation** — `add_evaluator.py` only supports code evaluators with templates (see `CODE_EVALUATOR_TEMPLATES` in the tool) and LLM evaluators (correctness, conciseness). If a suggestion doesn't match a known template, log it for the architect/critic to implement manually rather than silently adding a no-op entry.

**Auto-trigger critic** if score jumped >0.3 or hit target in <3 iterations.

**Auto-trigger architect** (opus model) if 3 consecutive iterations within 1% or score dropped.

### 7. Gate Check

- **Score plateau**: 3 scores within 2% → consider architect or stop
- **Target reached**: `best_score >= target_score` → stop
- **Diminishing returns**: avg improvement <0.5% over 5 iterations → stop

(Cost/latency regressions are now checked pre-merge in step 5, not post-merge.)

## Final Report

```bash
$EVOLVER_PY $TOOLS/evolution_chart.py --config .evolver.json
```

Plus: LangSmith URL, `git log --oneline` summary, suggest `/harness:deploy`.
