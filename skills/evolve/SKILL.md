---
name: evolver:evolve
description: "Use when the user wants to run the optimization loop, improve agent performance, evolve the agent, or iterate on quality. Requires .evolver.json to exist (run evolver:setup first)."
argument-hint: "[--iterations N]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion]
---

# /evolver:evolve

Run the autonomous propose-evaluate-iterate loop using LangSmith as the evaluation backend and git worktrees for isolation.

## Prerequisites

`.evolver.json` must exist. If not, tell user to run `evolver:setup`.

## Resolve Tool Path and Python

```bash
# Prefer env vars set by plugin hook; fallback to legacy npx paths
TOOLS="${EVOLVER_TOOLS:-$([ -d ".evolver/tools" ] && echo ".evolver/tools" || echo "$HOME/.evolver/tools")}"
EVOLVER_PY="${EVOLVER_PY:-$([ -f "$HOME/.evolver/venv/bin/python" ] && echo "$HOME/.evolver/venv/bin/python" || echo "python3")}"
```

Use `$EVOLVER_PY` instead of `python3` for ALL tool invocations.

**IMPORTANT: Never pass `LANGSMITH_API_KEY` inline in Bash commands.** The key is loaded automatically by the SessionStart hook and by each tool's `ensure_langsmith_api_key()`. Passing it inline exposes it in the output.

## Parse Arguments

- `--iterations N` (default: from interactive question or 5)
- `--no-interactive` — skip all AskUserQuestion prompts, use defaults (iterations=5, target=none, mode=interactive). Required for cron/background scheduled runs.

## Pre-Loop: Interactive Configuration

If `--no-interactive` is set, skip all questions and use defaults:
- Iterations: value from `--iterations` or 5
- Target: value from `.evolver.json` `target_score` if set, otherwise no limit
- Mode: interactive (the cron itself handles scheduling)

Otherwise, if no `--iterations` argument was provided, ask the user:

```json
{
  "questions": [
    {
      "question": "How many evolution iterations?",
      "header": "Iterations",
      "multiSelect": false,
      "options": [
        {"label": "3 (quick)", "description": "Fast exploration, good for testing. ~15 min."},
        {"label": "5 (balanced)", "description": "Good trade-off between speed and quality. ~30 min."},
        {"label": "10 (thorough)", "description": "Deep optimization with adaptive strategies. ~1 hour."}
      ]
    },
    {
      "question": "Stop early if score reaches?",
      "header": "Target",
      "multiSelect": false,
      "options": [
        {"label": "0.8 (good enough)", "description": "Stop when the agent is reasonably good"},
        {"label": "0.9 (high quality)", "description": "Stop when quality is high"},
        {"label": "0.95 (near perfect)", "description": "Push for near-perfect scores"},
        {"label": "No limit", "description": "Run all iterations regardless of score"}
      ]
    }
  ]
}
```

Write the target to `.evolver.json` for gate checks:

```bash
python3 -c "
import json
c = json.load(open('.evolver.json'))
c['target_score'] = {target_score_float}  # parsed from user selection, or None for 'No limit'
json.dump(c, open('.evolver.json', 'w'), indent=2)
"
```

If iterations > 3, offer execution mode:

```json
{
  "questions": [
    {
      "question": "Run mode?",
      "header": "Execution",
      "multiSelect": false,
      "options": [
        {"label": "Interactive", "description": "I'll watch. Show results after each iteration."},
        {"label": "Background", "description": "Run all iterations in background. Notify on completion or significant improvement."}
      ]
    }
  ]
}
```

**If "Background" selected:**
Run the evolution loop as a background task. Use the `run_in_background` parameter on the main loop execution.

## The Loop

Read config:
```bash
python3 -c "import json; c=json.load(open('.evolver.json')); print(f'Best: {c[\"best_experiment\"]} ({c[\"best_score\"]:.3f}), Iterations: {c[\"iterations\"]}')"
```

### 0.5. Preflight Check

Run the integrated preflight that validates everything in one pass (API key, config schema, LangSmith state, dataset health, canary):

```bash
$EVOLVER_PY $TOOLS/preflight.py --config .evolver.json
```

This replaces the previous separate validate_state + health check steps. If preflight fails, it reports ALL issues at once. Ask the user via AskUserQuestion:
- "Fix and retry" — address the issues, then rerun preflight
- "Continue anyway" — proceed with warnings (not recommended if critical)
- "Abort" — stop the evolution loop

If dataset health has auto-correctable issues (missing splits, low difficulty distribution), invoke `/evolver:health` to fix them, then rerun preflight.

### 0.7. Ensure Baseline Has LLM-Judge Scores

The baseline experiment (from setup) only runs code-based evaluators (has_output, token_efficiency). Without LLM-judge scores, the baseline score is inflated — any agent that produces text gets 1.0, making gate checks stop evolution prematurely.

Check if LLM evaluators are configured and the baseline needs scoring:

```bash
LLM_EVALS=$(python3 -c "import json; c=json.load(open('.evolver.json')); llm=[k for k in c['evaluators'] if k in ('correctness','conciseness')]; print(','.join(llm) if llm else '')")
BASELINE=$(python3 -c "import json; print(json.load(open('.evolver.json')).get('baseline_experiment', ''))")
```

If `LLM_EVALS` is non-empty and `BASELINE` exists, check if LLM scores already exist:

```bash
HAS_LLM_SCORES=$($EVOLVER_PY $TOOLS/read_results.py --experiment "$BASELINE" --config .evolver.json 2>/dev/null | python3 -c "
import sys, json
try:
    r = json.load(sys.stdin)
    scored_keys = set()
    for ex in r.get('per_example', {}).values():
        scored_keys.update(ex.get('scores', {}).keys())
    llm_keys = set('correctness,conciseness'.split(','))
    configured = set(k for k in llm_keys if k in '$LLM_EVALS'.split(','))
    print('yes' if configured.issubset(scored_keys) else 'no')
except: print('no')
")
```

If `HAS_LLM_SCORES` is "no", trigger the evaluator agent on the baseline:

```
Agent(
  subagent_type: "evolver-evaluator",
  description: "Score baseline with LLM-judge",
  prompt: "Experiments to evaluate: {baseline_experiment}. Evaluators: {llm_evaluator_list}. Framework: {framework}. Entry point: {entry_point}. Dataset: {dataset_name}. NOTE: This is the baseline — score it fairly so evolution has a meaningful starting point. Some examples have expected_behavior rubrics in their metadata — fetch example metadata and use rubrics for scoring when available."
)
```

After the evaluator completes, re-read the baseline score and update `.evolver.json`:

```bash
$EVOLVER_PY $TOOLS/read_results.py --experiment "$BASELINE" --config .evolver.json --output best_results.json 2>/dev/null
python3 -c "
import json
br = json.load(open('best_results.json'))
c = json.load(open('.evolver.json'))
new_score = br.get('combined_score', c['best_score'])
c['best_score'] = new_score
if c.get('history'):
    c['history'][0]['score'] = new_score
json.dump(c, open('.evolver.json', 'w'), indent=2)
print(f'Baseline re-scored with LLM-judge: {new_score:.3f}')
"
```

### 0.8. Resolve Project Directory

If the project is in a subdirectory of the git repo (e.g., `playground/react-agent/`), worktrees replicate the full repo structure. Read `project_dir` from `.evolver.json` to resolve paths correctly:

```bash
PROJECT_DIR=$(python3 -c "import json; print(json.load(open('.evolver.json')).get('project_dir', ''))")
```

If `PROJECT_DIR` is non-empty, all worktree paths must include it:
- Config in worktree: `{worktree_path}/{PROJECT_DIR}/.evolver.json`
- CWD in worktree: `{worktree_path}/{PROJECT_DIR}`
- proposal.md in worktree: `{worktree_path}/{PROJECT_DIR}/proposal.md`

If `PROJECT_DIR` is empty (project at git root), paths are unchanged: `{worktree_path}/.evolver.json`, etc.

For each iteration:

### 1. Get Next Version

```bash
python3 -c "import json; c=json.load(open('.evolver.json')); print(f'v{c[\"iterations\"]+1:03d}')"
```

### 1.5. Gather Analysis Data (Parallel)

Read the best experiment from config. If null (no baseline was run), skip data gathering — proposers will work from code analysis only:

```bash
BEST=$(python3 -c "import json; b=json.load(open('.evolver.json')).get('best_experiment'); print(b if b else '')")
PROD=$(python3 -c "import json; c=json.load(open('.evolver.json')); print(c.get('production_project',''))")

if [ -n "$BEST" ]; then
    # Run all data gathering in parallel — these are independent API calls
    $EVOLVER_PY $TOOLS/trace_insights.py \
        --from-experiment "$BEST" \
        --output trace_insights.json 2>/dev/null &

    $EVOLVER_PY $TOOLS/read_results.py \
        --experiment "$BEST" \
        --config .evolver.json \
        --split train \
        --output best_results.json 2>/dev/null &
fi

if [ -n "$PROD" ] && [ ! -f "production_seed.json" ]; then
    $EVOLVER_PY $TOOLS/seed_from_traces.py \
        --project "$PROD" \
        --output-md production_seed.md \
        --output-json production_seed.json \
        --limit 100 2>/dev/null &
fi

wait  # Wait for all data gathering to complete
```

If `best_results.json` exists, parse it to find failing examples (score < 0.7). Group by metadata or error pattern.
**For each failing example, include the judge's feedback comment** (from the `feedback` field) in the strategy. This gives proposers specific, actionable information about WHY examples fail:

```
## Failing Examples (with judge feedback)
- "What is Kotlin?" (score: 0.3) — Judge: "Response was factually correct but missed null safety and Android development use cases"
- "Calculate 2^32" (score: 0.0) — Judge: "Run failed with timeout error"
```

This failure data feeds into the strategy and lens generation step (1.8a).
If no best_results.json (first iteration without baseline), all proposers work from code analysis only — no failure data available.

### 1.8a. Generate Strategy and Lenses

Read the available analysis files:
- `trace_insights.json` (error clusters, token analysis)
- `best_results.json` (per-task scores and failures)
- `evolution_memory.json` / `evolution_memory.md` (cross-iteration insights)
- `production_seed.json` (real-world traffic patterns, if exists)

Based on this data, generate two files:

**`strategy.md`** — A concise strategy document. **CRITICAL: only include data from the CURRENT iteration's analysis. Do not carry over stale info from prior strategy.md files — stale context is an active distractor that degrades proposer performance.** Contents:
- Target files (from current trace analysis)
- Failure clusters from the LATEST experiment only (not historical)
- Top 3 insights from evolution_memory.md (only promoted insights with rec >= 2, not all observations)
- Approaches to avoid (only still-relevant ones)
- Top 3 failing examples with judge feedback
- Production insights (if new data exists)

**Keep strategy.md under 1500 tokens.** Longer strategies dilute proposer attention. Full data stays in trace_insights.json and best_results.json for proposers to read on demand.

**`lenses.json`** — Investigation questions for proposers, format:
```json
{
  "generated_at": "ISO timestamp",
  "lens_count": N,
  "lenses": [
    {"id": 1, "question": "...", "source": "failure_cluster|architecture|production|evolution_memory|uniform_failure|open", "severity": "critical|high|medium", "context": {}},
    ...
  ]
}
```

Lens generation rules:
- One lens per distinct failure cluster (max 3)
- One architecture lens if high-severity structural issues exist
- One production lens if production data shows problems
- One evolution memory lens if a pattern won 2+ times
- One persistent failure lens if a pattern recurred 3+ iterations
- If all examples fail with same error, one "uniform_failure" lens
- Always include one "open" lens
- Sort by severity (critical > high > medium), cap at max_proposers from config (default 5)

### 1.9. Prepare Shared Proposer Context

Build the shared context that ALL proposers will receive as an identical prefix. This enables KV cache sharing — spawning N proposers costs barely more than 1.

```bash
# Build shared context block (identical for all proposers)
SHARED_FILES_BLOCK="<files_to_read>
- .evolver.json
- strategy.md (if exists)
- evolution_memory.md (if exists)
- production_seed.json (if exists)
- {entry_point_file}
</files_to_read>"

SHARED_CONTEXT_BLOCK="<context>
Best experiment: {best_experiment} (score: {best_score})
Framework: {framework}
Entry point: {entry_point}
Evaluators: {evaluators}
Iteration: {iteration_number} of {total_iterations}
Score history: {score_history_summary}
</context>"

SHARED_OBJECTIVE="<objective>
Improve the agent code to score higher on the evaluation dataset.
You are working in an isolated git worktree — modify any file freely.
</objective>"
```

**CRITICAL for cache sharing**: The `<objective>`, `<files_to_read>`, and `<context>` blocks MUST be byte-identical across all proposer prompts. Only the `<lens>` block differs. Place the lens block LAST in the prompt so the shared prefix is maximized.

### 2. Spawn Proposers in Parallel (Dynamic Lenses)

Read `lenses.json` to get the list of investigation lenses:

```bash
LENS_COUNT=$(python3 -c "import json; print(json.load(open('lenses.json'))['lens_count'])")
```

Each proposer receives the IDENTICAL prefix (objective + files + context) followed by its unique lens.

**For each lens** — `run_in_background: true, isolation: "worktree"`:

The prompt for EACH proposer follows this structure:
```
{SHARED_OBJECTIVE}

{SHARED_FILES_BLOCK}

{SHARED_CONTEXT_BLOCK}

<lens>
Investigation question: {lens.question}

This is your STARTING POINT, not your mandate. Investigate, form your
own hypothesis, and implement whatever you conclude will help most.
You may solve something entirely different — that's fine.
If you cannot add meaningful value, ABSTAIN.

Source: {lens.source}
</lens>

<output>
1. Investigate the lens question
2. Decide your approach (or abstain)
3. If proceeding: modify code, commit, write proposal.md
4. proposal.md must include: what you chose to do, why, how it relates to the lens
</output>
```

For each lens in `lenses.json`, spawn one proposer agent:

```
Agent(
  subagent_type: "evolver-proposer",
  description: "Proposer {lens.id}: {lens.source} lens",
  isolation: "worktree",
  run_in_background: true,
  prompt: {SHARED_PREFIX + LENS_BLOCK above, with lens fields filled in}
)
```

Wait for all proposers to complete. **As each proposer completes**, report its status immediately (don't wait for all):

```
Proposer {id} ({lens.source}) completed — {committed N files / ABSTAINED}
  Approach: {first line from proposal.md, if exists}
Progress: {completed}/{total} proposers done
```

This gives the user visibility into progress while other proposers are still running.

**Stuck proposer detection**: If any proposer hasn't completed after 10 minutes, it may be stuck in a loop. The Claude Code runtime handles this via the agent's turn limit. If a proposer returns without committing changes, skip it — don't retry.

After all proposers complete, check which ones committed and which abstained:

```bash
for WORKTREE in {worktree_paths}; do
    # Resolve project path within worktree
    WT_PROJECT="$WORKTREE"
    [ -n "$PROJECT_DIR" ] && WT_PROJECT="$WORKTREE/$PROJECT_DIR"

    if [ -f "$WT_PROJECT/proposal.md" ] && grep -q "## ABSTAIN" "$WT_PROJECT/proposal.md" 2>/dev/null; then
        echo "Proposer in $WORKTREE abstained — skipping evaluation"
    elif [ $(cd "$WORKTREE" && git log --oneline -1 --since="10 minutes ago" 2>/dev/null | wc -l) -eq 0 ]; then
        echo "Proposer in $WORKTREE made no commits — skipping"
    fi
done
```

Only run evaluation (Step 3) for proposers that committed changes (not abstained, not stuck).

### 3. Run Target for Each Candidate (Parallel)

First, copy config files into each worktree (untracked files aren't replicated by git — this was the #1 bug in all real-world runs):

```bash
for WORKTREE in {worktree_paths_with_commits}; do
    WORKTREE_PROJECT="$WORKTREE"
    [ -n "$PROJECT_DIR" ] && WORKTREE_PROJECT="$WORKTREE/$PROJECT_DIR"

    # Copy untracked config files needed by run_eval.py and the agent
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

Each candidate becomes a separate LangSmith experiment. This step runs the agent and applies code-based evaluators (has_output, token_efficiency) only.

Collect all experiment names from the output (the `"experiment"` field in each JSON output).

### 3.5. LLM-as-Judge Evaluation (Evaluator Agent)

Check if the config has LLM-based evaluators (correctness, conciseness):

```bash
python3 -c "import json; c=json.load(open('.evolver.json')); llm=[k for k in c['evaluators'] if k in ('correctness','conciseness')]; print(','.join(llm) if llm else '')"
```

If LLM evaluators are configured, first verify langsmith-cli is available:

```bash
command -v langsmith-cli >/dev/null 2>&1 || { echo "ERROR: langsmith-cli not found. Install with: uv tool install langsmith-cli"; exit 1; }
```

Then spawn ONE evaluator agent that scores ALL candidates in a single pass. This is more efficient than spawning one agent per candidate:

```
Agent(
  subagent_type: "evolver-evaluator",
  description: "Evaluate all candidates for iteration v{NNN}",
  prompt: "Experiments to evaluate: {comma-separated experiment names from non-abstained proposers}. Evaluators: {llm_evaluator_list}. Framework: {framework}. Entry point: {entry_point}. Dataset: {dataset_name}. NOTE: Some examples have expected_behavior rubrics in their metadata — fetch example metadata and use rubrics for scoring when available."
)
```

Wait for the evaluator agent to complete before proceeding.

### 4. Compare All Candidates

```bash
$EVOLVER_PY $TOOLS/read_results.py \
    --experiments "{comma-separated list of experiment names from non-abstained proposers}" \
    --config .evolver.json \
    --split held_out \
    --output comparison.json
```

Parse `comparison.json`:
- `comparison.winner` — highest combined score **on held-out data** (never seen during optimization)
- `comparison.champion` — per-task champion (for next iteration's context)
- `comparison.pareto_front` — non-dominated candidates across evaluators (if >1, report tradeoffs)
- `comparison.all_candidates` — all scores for reporting

If `comparison.pareto_front` has more than 1 entry, report it:
```
Pareto front ({N} non-dominated candidates):
  v{NNN}-1: {evaluator_scores} (winner by combined score)
  v{NNN}-3: {evaluator_scores} (different tradeoff)
```

### 4.5. Constraint Gate

Before merging, validate the winner passes hard constraints:

```bash
$EVOLVER_PY $TOOLS/constraint_check.py \
    --config .evolver.json \
    --worktree-path "{winner_worktree_path}" \
    --baseline-path "." \
    --output constraint_result.json
```

If `all_pass` is false, skip this candidate and try the next-best from `comparison.all_candidates`. If NO candidates pass constraints, log a warning and proceed to next iteration without merging:

```
WARNING: No candidates passed constraint gates. Skipping merge.
  growth: {growth_pct}% (limit: 30%)
  entry_point: {pass/fail}
  tests: {pass/fail}
```

### 5. Merge Winner

If the winner scored higher than the current best AND passed constraint gates:

```bash
# Get the winning worktree's branch
WINNER_BRANCH={winning_worktree_branch}

# Merge into main
git merge $WINNER_BRANCH --no-edit -m "evolve: merge v{NNN}-{lens_id} (score: {score})"
```

Update `.evolver.json` with enriched history entry:

Extract winner metrics for the chart:
- `tokens`, `latency_ms`, `errors` → from `comparison.all_candidates` for the winner
- `passing`, `total` → count per_example scores ≥0.5 vs total from best_results.json (re-read for winner experiment)
- `per_evaluator` → average each evaluator's scores across per_example from best_results.json
- `approach` → first line of `## Approach` section from winner's proposal.md
- `lens` → the `source` field from the winning proposer's lens in lenses.json
- `code_loc` → count lines of code after merge for growth tracking:

```bash
CODE_LOC=$(find . -name "*.py" -not -path "./.venv/*" -not -path "./venv/*" -not -path "./__pycache__/*" | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}')
```

```python
import json
c = json.load(open('.evolver.json'))
c['best_experiment'] = '{winner_experiment}'
c['best_score'] = {winner_score}
c['iterations'] = c['iterations'] + 1
c['history'].append({
    'version': 'v{NNN}',
    'experiment': '{winner_experiment}',
    'score': {winner_score},
    'tokens': {winner_tokens},
    'latency_ms': {winner_latency_ms},
    'error_count': {winner_errors},
    'passing': {winner_passing},
    'total': {winner_total},
    'per_evaluator': {winner_per_evaluator_dict},
    'approach': '{approach_from_proposal_md}',
    'lens': '{lens_source}',
    'code_loc': {code_loc}
})
json.dump(c, open('.evolver.json', 'w'), indent=2)
```

Report ALL candidates:
```
Iteration {i}/{N} — {lens_count} lenses, {evaluated_count} candidates evaluated ({abstained_count} abstained):
  {For each proposer, read proposal.md and extract the Approach field}
  v{NNN}-1 ({approach from proposal.md}):  {score} — {summary}
  v{NNN}-2 ({approach from proposal.md}):  {score} — {summary}
  v{NNN}-3 (ABSTAINED):                    --    — {reason from proposal.md}
  ...

  Winner: v{NNN}-{id} ({score}) — merged into main
  Per-task champion: {champion} (beats winner on {N} tasks)
```

### 5.5. Regression Tracking & Test Suite Growth

If this is not the first iteration (previous experiment exists), track regressions and auto-add guards:

```bash
PREV_EXP=$(python3 -c "
import json
h = json.load(open('.evolver.json')).get('history', [])
print(h[-2]['experiment'] if len(h) >= 2 else '')
")
if [ -n "$PREV_EXP" ]; then
    $EVOLVER_PY $TOOLS/regression_tracker.py \
        --config .evolver.json \
        --previous-experiment "$PREV_EXP" \
        --current-experiment "{winner_experiment}" \
        --add-guards --max-guards 5 \
        --output regression_report.json 2>/dev/null
    
    # Report regressions
    python3 -c "
import json, os
if os.path.exists('regression_report.json'):
    r = json.load(open('regression_report.json'))
    if r['regression_count'] > 0:
        print(f'WARNING: {r[\"regression_count\"]} regressions detected')
    if r['guards_added'] > 0:
        print(f'  Added {r[\"guards_added\"]} regression guard examples to dataset')
    if r['fixed_count'] > 0:
        print(f'  {r[\"fixed_count\"]} previously-failing examples now pass')
" 2>/dev/null
fi
```

### 6. Report

Print: `Iteration {i}/{N}: v{NNN} scored {score} (best: {best} at {best_score})`

### 6.2. Consolidate Evolution Memory

Spawn the consolidator agent (runs in background — doesn't block the next iteration):

```
Agent(
  subagent_type: "evolver-consolidator",
  description: "Consolidate evolution memory after iteration v{NNN}",
  run_in_background: true,
  prompt: "Update evolution_memory.md with learnings from this iteration. Read .evolver.json, comparison.json, trace_insights.json, regression_report.json (if exists), and current evolution_memory.md (if exists). Track what worked, what failed, and promote insights that recur across iterations."
)
```

The `evolution_memory.md` file will be available for proposer briefings in subsequent iterations.

### 6.5. Auto-trigger Active Critic

If score jumped >0.3 from previous iteration OR reached target in <3 iterations:

```
Agent(
  subagent_type: "evolver-critic",
  description: "Check evaluator gaming after score jump",
  prompt: "Score jumped from {prev_score} to {score}. Check if LangSmith evaluators are being gamed. Read .evolver.json, comparison.json, trace_insights.json, evolution_memory.md. If gaming detected, add stricter evaluators using $EVOLVER_PY $TOOLS/add_evaluator.py."
)
```

If the critic added new evaluators, log it:
```
Critic added evaluators: {new_evaluators}. Next iteration will use stricter evaluation.
```

### 7. Auto-trigger Architect (ULTRAPLAN Mode)

If 3 consecutive iterations within 1% OR score dropped:

```
Agent(
  subagent_type: "evolver-architect",
  model: "opus",
  description: "Deep topology analysis after stagnation",
  prompt: "Evolution stagnated after {iterations} iterations. Scores: {last_3_scores}. Analyze architecture and recommend structural changes. Read .evolver.json, trace_insights.json, evolution_memory.md, strategy.md, and the entry point source files. Use $EVOLVER_PY $TOOLS/analyze_architecture.py for AST analysis if helpful."
)
```

After architect completes, include `architecture.md` in proposer `<files_to_read>` for next iteration.

### 8. Gate Check

Read `.evolver.json` history and assess whether to continue:

- **Score plateau**: If last 3 scores are within 2% of each other, evolution may have converged. Consider triggering architect (Step 7) or stopping.
- **Target reached**: If `best_score >= target_score`, stop and report success.
- **Diminishing returns**: If average improvement over last 5 iterations is less than 0.5%, consider stopping.

If stopping, skip to the final report. If continuing, proceed to next iteration.

## When Loop Ends — Final Report

Display the evolution chart:

```bash
$EVOLVER_PY $TOOLS/evolution_chart.py --config .evolver.json
```

Then add:
- LangSmith experiment URL for the best experiment (construct from project name)
- `git log --oneline` from baseline to current HEAD (key changes summary)
- Suggest: `/evolver:deploy` to finalize
