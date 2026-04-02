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

## Pre-Loop: Interactive Configuration

If no `--iterations` argument was provided, ask the user:

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
        --output best_results.json 2>/dev/null
fi
```

If `best_results.json` exists, parse it to find failing examples (score < 0.7). Group by metadata or error pattern.
Generate adaptive briefings for Candidates D and E (same logic as v2).
If no best_results.json (first iteration without baseline), all proposers work from code analysis only — no failure data available.

### 2. Spawn 5 Proposers in Parallel

Each proposer runs in a **git worktree** via Claude Code's native `isolation: "worktree"` parameter.

**Candidate A (Exploit)** — `run_in_background: true`:

```
Agent(
  subagent_type: "evolver-proposer",
  description: "Proposer A: exploit best version",
  isolation: "worktree",
  run_in_background: true,
  prompt: |
    <objective>
    Improve the agent code to score higher on the evaluation dataset.
    You are working in an isolated git worktree — modify any file freely.
    </objective>

    <strategy>
    APPROACH: exploitation
    Make targeted improvements to the current best version.
    Focus on the specific failures identified in the results.
    </strategy>

    <files_to_read>
    - .evolver.json
    - trace_insights.json (if exists)
    - production_seed.json (if exists)
    - best_results.json (if exists)
    - {entry point file from .evolver.json}
    </files_to_read>

    <context>
    Best experiment: {best_experiment} (score: {best_score})
    Framework: {framework}
    Entry point: {entry_point}
    Evaluators: {evaluators}
    Failing examples: {failing_example_summary}
    </context>

    <output>
    1. Modify the code to improve performance
    2. Commit your changes with a descriptive message
    3. Write proposal.md explaining what you changed and why
    </output>
)
```

**Candidate B (Explorer)** — `run_in_background: true`:
Same structure but `APPROACH: exploration` — bold, fundamentally different approach.

**Candidate C (Crossover)** — `run_in_background: true`:
Same structure but `APPROACH: crossover` — combine strengths from previous iterations.
Include git log of recent changes so it can see what was tried.

**Candidates D and E (Failure-Targeted)** — `run_in_background: true`:
Same structure but `APPROACH: failure-targeted` with specific failing example clusters.
If ALL_PASSING: D gets `creative`, E gets `efficiency`.

Wait for all 5 to complete.

### 3. Run Target for Each Candidate

For each worktree that has changes (proposer committed something):

```bash
$EVOLVER_PY $TOOLS/run_eval.py \
    --config .evolver.json \
    --worktree-path {worktree_path} \
    --experiment-prefix v{NNN}{suffix} \
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
    - {experiment_name_a}
    - {experiment_name_b}
    - {experiment_name_c}
    - {experiment_name_d}
    - {experiment_name_e}
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
    --experiments "v{NNN}a,v{NNN}b,v{NNN}c,v{NNN}d,v{NNN}e" \
    --config .evolver.json \
    --output comparison.json
```

Parse `comparison.json`:
- `comparison.winner` — highest combined score
- `comparison.champion` — per-task champion (for next crossover)
- `comparison.all_candidates` — all scores for reporting

### 5. Merge Winner

If the winner scored higher than the current best:

```bash
# Get the winning worktree's branch
WINNER_BRANCH={winning_worktree_branch}

# Merge into main
git merge $WINNER_BRANCH --no-edit -m "evolve: merge v{NNN}{suffix} (score: {score})"
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
Iteration {i}/{N} — 5 candidates evaluated:
  v{NNN}a (exploit):     {score_a} — {summary}
  v{NNN}b (explore):     {score_b} — {summary}
  v{NNN}c (crossover):   {score_c} — {summary}
  v{NNN}d ({strategy}):  {score_d} — {summary}
  v{NNN}e ({strategy}):  {score_e} — {summary}

  Winner: v{NNN}{suffix} ({score}) — merged into main
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

### 6.5. Auto-trigger Critic

If score jumped >0.3 from previous iteration OR reached target in <3 iterations:

Spawn the critic agent to analyze evaluator quality:

```
Agent(
  subagent_type: "evolver-critic",
  description: "Critic: check evaluator gaming",
  prompt: |
    <objective>
    EVAL GAMING DETECTED: Score jumped from {prev_score} to {score}.
    Check if the LangSmith evaluators are being gamed.
    </objective>

    <files_to_read>
    - .evolver.json
    - comparison.json
    - trace_insights.json
    </files_to_read>
)
```

### 7. Auto-trigger Architect

If 3 consecutive iterations within 1% OR score dropped:

```
Agent(
  subagent_type: "evolver-architect",
  description: "Architect: recommend topology change",
  prompt: |
    <objective>
    The evolution loop has stagnated after {iterations} iterations.
    Analyze the architecture and recommend changes.
    </objective>

    <files_to_read>
    - .evolver.json
    - trace_insights.json
    - {entry point and related source files}
    </files_to_read>
)
```

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
