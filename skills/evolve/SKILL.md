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

### 0.5. Validate State

Before starting the loop, verify `.evolver.json` matches LangSmith reality:

```bash
VALIDATION=$($EVOLVER_PY $TOOLS/validate_state.py --config .evolver.json 2>/dev/null)
VALID=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin).get('valid', False))")
if [ "$VALID" = "False" ]; then
    echo "WARNING: State validation found issues:"
    echo "$VALIDATION" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for issue in data.get('issues', []):
    print(f'  [{issue[\"severity\"]}] {issue[\"message\"]}')
"
fi
```

If critical issues found, ask user whether to continue or fix first via AskUserQuestion:
- "Continue anyway" — proceed with warnings
- "Fix and retry" — attempt auto-fix with `--fix` flag
- "Abort" — stop the evolution loop

### 0.6. Dataset Health Check

Run the dataset health diagnostic:

```bash
$EVOLVER_PY $TOOLS/dataset_health.py \
    --config .evolver.json \
    --production-seed production_seed.json \
    --output health_report.json 2>/dev/null
```

Read `health_report.json`. Print summary:
```bash
python3 -c "
import json, os
if os.path.exists('health_report.json'):
    r = json.load(open('health_report.json'))
    print(f'Dataset Health: {r[\"health_score\"]}/10 ({r[\"example_count\"]} examples)')
    for issue in r.get('issues', []):
        print(f'  [{issue[\"severity\"]}] {issue[\"message\"]}')
"
```

### 0.7. Auto-Correct Dataset Issues

If `health_report.json` has corrections, apply them automatically:

```bash
CORRECTIONS=$(python3 -c "
import json, os
if os.path.exists('health_report.json'):
    r = json.load(open('health_report.json'))
    for c in r.get('corrections', []):
        print(c['action'])
" 2>/dev/null)
```

For each correction:

**If `create_splits`**: Run inline Python to assign 70/30 splits:
```bash
$EVOLVER_PY -c "
from langsmith import Client
import json, random
client = Client()
config = json.load(open('.evolver.json'))
examples = list(client.list_examples(dataset_name=config['dataset']))
random.shuffle(examples)
sp = int(len(examples) * 0.7)
for ex in examples[:sp]:
    client.update_example(ex.id, split='train')
for ex in examples[sp:]:
    client.update_example(ex.id, split='held_out')
print(f'Assigned splits: {sp} train, {len(examples)-sp} held_out')
"
```

**If `generate_hard`**: Spawn testgen agent with hard-mode instruction:
```
Agent(
  subagent_type: "evolver-testgen",
  description: "Generate hard examples to rebalance dataset",
  prompt: |
    <objective>
    The dataset is skewed toward easy examples. Generate {count} HARD examples
    that the current agent is likely to fail on.
    Focus on: edge cases, adversarial inputs, complex multi-step queries,
    ambiguous questions, and inputs that require deep reasoning.
    </objective>
    <files_to_read>
    - .evolver.json
    - strategy.md (if exists)
    - production_seed.json (if exists)
    </files_to_read>
)
```

**If `fill_coverage`**: Spawn testgen agent with coverage-fill instruction:
```
Agent(
  subagent_type: "evolver-testgen",
  description: "Generate examples for missing categories",
  prompt: |
    <objective>
    The dataset is missing these production categories: {categories}.
    Generate 5 examples per missing category.
    Use production_seed.json for real-world patterns in these categories.
    </objective>
    <files_to_read>
    - .evolver.json
    - production_seed.json (if exists)
    </files_to_read>
)
```

**If `retire_dead`**: Move dead examples to retired split:
```bash
$EVOLVER_PY -c "
from langsmith import Client
import json
client = Client()
report = json.load(open('health_report.json'))
dead_ids = report.get('dead_examples', {}).get('ids', [])
config = json.load(open('.evolver.json'))
examples = {str(e.id): e for e in client.list_examples(dataset_name=config['dataset'])}
retired = 0
for eid in dead_ids:
    if eid in examples:
        client.update_example(examples[eid].id, split='retired')
        retired += 1
print(f'Retired {retired} dead examples')
"
```

After corrections, log what was done. Do NOT re-run health check (corrections may need an experiment cycle to show effect).

For each iteration:

### 1. Get Next Version

```bash
python3 -c "import json; c=json.load(open('.evolver.json')); print(f'v{c[\"iterations\"]+1:03d}')"
```

### 1.5. Gather Trace Insights

Read the best experiment from config. If null (no baseline was run), skip trace insights for this iteration — proposers will work blind on the first pass:

```bash
BEST=$(python3 -c "import json; b=json.load(open('.evolver.json')).get('best_experiment'); print(b if b else '')")
if [ -n "$BEST" ]; then
    $EVOLVER_PY $TOOLS/trace_insights.py \
        --from-experiment "$BEST" \
        --output trace_insights.json 2>/dev/null
fi
```

If a production project is configured, also gather production insights:

```bash
PROD=$(python3 -c "import json; c=json.load(open('.evolver.json')); print(c.get('production_project',''))")
if [ -n "$PROD" ] && [ ! -f "production_seed.json" ]; then
    $EVOLVER_PY $TOOLS/seed_from_traces.py \
        --project "$PROD" --use-sdk \
        --output-md production_seed.md \
        --output-json production_seed.json \
        --limit 100 2>/dev/null
fi
```

### 1.8. Analyze Per-Task Failures

If `$BEST` is set (not the first iteration without baseline), read results and cluster failures:

```bash
if [ -n "$BEST" ]; then
    $EVOLVER_PY $TOOLS/read_results.py \
        --experiment "$BEST" \
        --config .evolver.json \
        --split train \
        --output best_results.json 2>/dev/null
fi
```

If `best_results.json` exists, parse it to find failing examples (score < 0.7). Group by metadata or error pattern.
This failure data feeds into `synthesize_strategy.py` which generates targeted lenses for proposers.
If no best_results.json (first iteration without baseline), all proposers work from code analysis only — no failure data available.

### 1.8a. Synthesize Strategy

Generate a targeted strategy document from all available analysis:

```bash
$EVOLVER_PY $TOOLS/synthesize_strategy.py \
    --config .evolver.json \
    --trace-insights trace_insights.json \
    --best-results best_results.json \
    --evolution-memory evolution_memory.json \
    --production-seed production_seed.json \
    --output strategy.md \
    --lenses lenses.json 2>/dev/null
```

The `strategy.md` file is included in the proposer `<files_to_read>` block via the shared context (Step 1.9). The `lenses.json` file contains dynamically generated investigation questions — one per proposer. Each lens directs a proposer's attention to a different aspect of the problem (failure cluster, architecture, production data, evolution memory, or open investigation).

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

Wait for all proposers to complete.

**Stuck proposer detection**: If any proposer hasn't completed after 10 minutes, it may be stuck in a loop. The Claude Code runtime handles this via the agent's turn limit. If a proposer returns without committing changes, skip it — don't retry.

After all proposers complete, check which ones committed and which abstained:

```bash
for WORKTREE in {worktree_paths}; do
    if [ -f "$WORKTREE/proposal.md" ] && grep -q "## ABSTAIN" "$WORKTREE/proposal.md" 2>/dev/null; then
        echo "Proposer in $WORKTREE abstained — skipping evaluation"
    elif [ $(cd "$WORKTREE" && git log --oneline -1 --since="10 minutes ago" 2>/dev/null | wc -l) -eq 0 ]; then
        echo "Proposer in $WORKTREE made no commits — skipping"
    fi
done
```

Only run evaluation (Step 3) for proposers that committed changes (not abstained, not stuck).

### 3. Run Target for Each Candidate

For each worktree that has changes (proposer committed something):

```bash
$EVOLVER_PY $TOOLS/run_eval.py \
    --config .evolver.json \
    --worktree-path {worktree_path} \
    --experiment-prefix v{NNN}-{lens_id} \
    --timeout 120
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
  prompt: |
    <experiment>
    Evaluate the following experiments (one per candidate):
    {list all experiment names from proposers that committed changes — skip abstained}
    </experiment>

    <evaluators>
    Apply these evaluators to each run in each experiment:
    - {llm_evaluator_list, e.g. "correctness", "conciseness"}
    </evaluators>

    <context>
    Agent type: {framework} agent
    Domain: {description from .evolver.json or entry point context}
    Entry point: {entry_point}

    For each experiment:
    1. Read all runs via: langsmith-cli --json runs list --project "{experiment_name}" --fields id,inputs,outputs,error --is-root true --limit 200
    2. Judge each run's output against the input
    3. Write scores via: langsmith-cli --json feedback create {run_id} --key {evaluator} --score {0.0|1.0} --comment "{reason}" --source model
    </context>
)
```

Wait for the evaluator agent to complete before proceeding.

### 4. Compare All Candidates

```bash
$EVOLVER_PY $TOOLS/read_results.py \
    --experiments "{comma-separated list of experiment names from non-abstained proposers}" \
    --config .evolver.json \
    --output comparison.json
```

Parse `comparison.json`:
- `comparison.winner` — highest combined score
- `comparison.champion` — per-task champion (for next iteration's context)
- `comparison.all_candidates` — all scores for reporting

### 5. Merge Winner

If the winner scored higher than the current best:

```bash
# Get the winning worktree's branch
WINNER_BRANCH={winning_worktree_branch}

# Merge into main
git merge $WINNER_BRANCH --no-edit -m "evolve: merge v{NNN}-{lens_id} (score: {score})"
```

Update `.evolver.json`:
```python
import json
c = json.load(open('.evolver.json'))
c['best_experiment'] = '{winner_experiment}'
c['best_score'] = {winner_score}
c['iterations'] = c['iterations'] + 1
c['history'].append({
    'version': 'v{NNN}',
    'experiment': '{winner_experiment}',
    'score': {winner_score}
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

Spawn the consolidator agent to analyze the iteration and update cross-iteration memory:

```
Agent(
  subagent_type: "evolver-consolidator",
  description: "Consolidate evolution memory after iteration v{NNN}",
  run_in_background: true,
  prompt: |
    <objective>
    Consolidate learnings from iteration v{NNN}.
    Run the consolidation tool and review its output.
    </objective>

    <tools_path>
    TOOLS={tools_path}
    EVOLVER_PY={evolver_py_path}
    </tools_path>

    <instructions>
    Run: $EVOLVER_PY $TOOLS/consolidate.py \
        --config .evolver.json \
        --comparison-files comparison.json \
        --output evolution_memory.md \
        --output-json evolution_memory.json

    Then read the output and verify insights are accurate.
    </instructions>

    <files_to_read>
    - .evolver.json
    - comparison.json
    - trace_insights.json (if exists)
    - regression_report.json (if exists)
    - evolution_memory.md (if exists)
    </files_to_read>
)
```

The `evolution_memory.md` file will be included in proposer briefings for subsequent iterations.

### 6.5. Auto-trigger Active Critic

If score jumped >0.3 from previous iteration OR reached target in <3 iterations:

```
Agent(
  subagent_type: "evolver-critic",
  description: "Active Critic: detect and fix evaluator gaming",
  prompt: |
    <objective>
    EVAL GAMING CHECK: Score jumped from {prev_score} to {score}.
    Check if the LangSmith evaluators are being gamed.
    If gaming detected, add stricter evaluators using $TOOLS/add_evaluator.py.
    </objective>

    <tools_path>
    TOOLS={tools_path}
    EVOLVER_PY={evolver_py_path}
    </tools_path>

    <files_to_read>
    - .evolver.json
    - comparison.json
    - trace_insights.json
    - evolution_memory.md (if exists)
    </files_to_read>
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
  description: "Architect ULTRAPLAN: deep topology analysis",
  prompt: |
    <objective>
    The evolution loop has stagnated after {iterations} iterations.
    Scores: {last_3_scores}.
    Perform deep architectural analysis and recommend structural changes.
    Use extended thinking — you have more compute budget than normal agents.
    </objective>

    <tools_path>
    TOOLS={tools_path}
    EVOLVER_PY={evolver_py_path}
    </tools_path>

    <files_to_read>
    - .evolver.json
    - trace_insights.json
    - evolution_memory.md (if exists)
    - evolution_memory.json (if exists)
    - strategy.md (if exists)
    - {entry point and all related source files}
    </files_to_read>
)
```

After architect completes, include `architecture.md` in proposer `<files_to_read>` for next iteration.

### 8. Gate Check (Three-Gate Trigger)

Before starting the next iteration, run the gate check:

```bash
GATE_RESULT=$($EVOLVER_PY $TOOLS/iteration_gate.py --config .evolver.json 2>/dev/null)
PROCEED=$(echo "$GATE_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('proceed', True))")
```

If `PROCEED` is `False`, check suggestions:

```bash
SUGGEST=$(echo "$GATE_RESULT" | python3 -c "import sys,json; s=json.load(sys.stdin).get('suggestions',[]); print(s[0] if s else '')")
```

- If `$SUGGEST` is `architect`: auto-trigger architect agent (Step 7)
- If `$SUGGEST` is `continue_cautious`: ask user via AskUserQuestion whether to continue
- Otherwise: stop the loop and report final results

Legacy stop conditions still apply:
- **Target**: `score >= target_score` → stop
- **N reached**: all requested iterations done → stop

## When Loop Ends — Final Report

- Best version and score
- Improvement over baseline (absolute and %)
- Total iterations run
- Key changes made (git log from baseline to current)
- LangSmith experiment URLs for comparison
- Suggest: `/evolver:deploy` to finalize
