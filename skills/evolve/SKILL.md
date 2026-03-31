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

**Step 2: Gather raw traces from the discovered project**

```bash
if [ -n "$LS_PROJECT" ]; then
  langsmith-cli --json runs list --project "$LS_PROJECT" --recent --fields id,name,inputs,outputs,error,total_tokens --limit 30 > /tmp/langsmith_raw.json 2>/dev/null || echo "[]" > /tmp/langsmith_raw.json
  langsmith-cli --json runs stats --project "$LS_PROJECT" > .harness-evolver/langsmith_stats.json 2>/dev/null || echo "{}" > .harness-evolver/langsmith_stats.json
  echo "$LS_PROJECT" > .harness-evolver/langsmith_project.txt
else
  echo "[]" > /tmp/langsmith_raw.json
  echo "{}" > .harness-evolver/langsmith_stats.json
fi
```

**Step 3: Process raw LangSmith data into a readable format for proposers**

The raw langsmith data has LangChain-serialized messages that are hard to read. Process it into a clean summary:

```bash
python3 -c "
import json, sys

raw = json.load(open('/tmp/langsmith_raw.json'))
if not raw:
    json.dump([], open('.harness-evolver/langsmith_runs.json', 'w'))
    sys.exit(0)

clean = []
for r in raw:
    entry = {'name': r.get('name', '?'), 'tokens': r.get('total_tokens', 0), 'error': r.get('error')}

    # Extract readable prompt from LangChain serialized inputs
    inputs = r.get('inputs', {})
    if isinstance(inputs, dict) and 'messages' in inputs:
        msgs = inputs['messages']
        for msg_group in (msgs if isinstance(msgs, list) else [msgs]):
            for msg in (msg_group if isinstance(msg_group, list) else [msg_group]):
                if isinstance(msg, dict):
                    kwargs = msg.get('kwargs', msg)
                    content = kwargs.get('content', '')
                    msg_type = msg.get('id', ['','','',''])[3] if isinstance(msg.get('id'), list) else 'unknown'
                    if 'Human' in str(msg_type) or 'user' in str(msg_type).lower():
                        entry['user_message'] = str(content)[:300]
                    elif 'System' in str(msg_type):
                        entry['system_prompt_preview'] = str(content)[:200]

    # Extract readable output
    outputs = r.get('outputs', {})
    if isinstance(outputs, dict) and 'generations' in outputs:
        gens = outputs['generations']
        if gens and isinstance(gens, list) and gens[0]:
            gen = gens[0][0] if isinstance(gens[0], list) else gens[0]
            if isinstance(gen, dict):
                msg = gen.get('message', gen)
                if isinstance(msg, dict):
                    kwargs = msg.get('kwargs', msg)
                    entry['llm_response'] = str(kwargs.get('content', ''))[:300]

    clean.append(entry)

json.dump(clean, open('.harness-evolver/langsmith_runs.json', 'w'), indent=2, ensure_ascii=False)
print(f'Processed {len(clean)} LangSmith runs into readable format')
" 2>/dev/null || echo "[]" > .harness-evolver/langsmith_runs.json
```

The resulting `langsmith_runs.json` has clean, readable entries:
```json
[
  {
    "name": "ChatGoogleGenerativeAI",
    "tokens": 1332,
    "error": null,
    "user_message": "Analise este texto: Bom dia pessoal...",
    "system_prompt_preview": "Você é um moderador de conteúdo...",
    "llm_response": "{\"categories\": [\"safe\"], \"severity\": \"safe\"...}"
  }
]
```

These files are included in the proposer's `<files_to_read>` so it has readable trace data for diagnosis.

### 1.6. Generate Trace Insights (systematic analysis)

If LangSmith traces were gathered, run systematic analysis to cluster errors, analyze token usage, and cross-reference with scores:

```bash
if [ -f ".harness-evolver/langsmith_runs.json" ]; then
    BEST=$(python3 -c "import json; s=json.load(open('.harness-evolver/summary.json')); print(s['best']['version'])")
    SCORES_PATH=".harness-evolver/harnesses/$BEST/scores.json"
    [ ! -f "$SCORES_PATH" ] && SCORES_PATH=".harness-evolver/baseline/scores.json"
    python3 $TOOLS/trace_insights.py \
        --langsmith-runs .harness-evolver/langsmith_runs.json \
        --langsmith-stats .harness-evolver/langsmith_stats.json \
        --scores "$SCORES_PATH" \
        --tasks-dir .harness-evolver/eval/tasks/ \
        --output .harness-evolver/trace_insights.json 2>/dev/null
fi
```

The resulting `trace_insights.json` contains:
- `error_clusters`: grouped error patterns with counts
- `token_analysis`: score distribution by token usage bucket (low/medium/high)
- `hypotheses`: data-driven theories about failure causes
- `top_issues`: highest-impact problems sorted by severity

This file is included in all proposers' `<files_to_read>` so they have structured diagnostic data.

### 1.8. Analyze Per-Task Failures (adaptive briefings for Candidates D and E)

Before spawning proposers, analyze which tasks are failing and cluster them:

```bash
python3 -c "
import json, os, sys

# Find best version scores
summary = json.load(open('.harness-evolver/summary.json'))
best = summary['best']['version']
scores_path = f'.harness-evolver/harnesses/{best}/scores.json'
if not os.path.exists(scores_path):
    scores_path = '.harness-evolver/baseline/scores.json' if os.path.exists('.harness-evolver/baseline/scores.json') else None

if not scores_path or not os.path.exists(scores_path):
    print('NO_SCORES')
    sys.exit(0)

scores = json.load(open(scores_path))
tasks_dir = '.harness-evolver/eval/tasks/'
failures = {}

for tid, tdata in scores.get('per_task', {}).items():
    score = tdata.get('score', 0)
    if score < 0.7:
        tfile = os.path.join(tasks_dir, tid + '.json')
        cat = 'unknown'
        if os.path.exists(tfile):
            task = json.load(open(tfile))
            meta = task.get('metadata', {})
            cat = meta.get('category', meta.get('type', meta.get('difficulty', 'unknown')))
        failures.setdefault(cat, []).append({'id': tid, 'score': score})

if not failures:
    print('ALL_PASSING')
else:
    sorted_clusters = sorted(failures.items(), key=lambda x: -len(x[1]))
    for i, (cat, tasks) in enumerate(sorted_clusters[:2]):
        task_ids = [t['id'] for t in tasks]
        avg_score = sum(t['score'] for t in tasks) / len(tasks)
        print(f'CLUSTER_{i+1}|{cat}|{json.dumps(task_ids)}|{avg_score:.2f}')
" 2>/dev/null
```

Parse the output:
- If `NO_SCORES` or `ALL_PASSING`: D gets "creative" brief, E gets "efficiency" brief
- If clusters found: D targets cluster 1, E targets cluster 2
- If only 1 cluster: D targets it, E gets "creative" brief

Save clusters for use in step 2.

### 2. Propose (3 parallel candidates)

Spawn 3 proposer agents IN PARALLEL, each with a different evolutionary strategy.
This follows the DGM/AlphaEvolve pattern: exploit + explore + crossover.

Determine parents for each strategy:
- **Exploiter parent**: current best version (from summary.json `best.version`)
- **Explorer parent**: a non-best version with low offspring count (read summary.json history, pick one that scored >0 but is NOT the best and has NOT been parent to many children)
- **Crossover parents**: 
  - Parent A = current best version
  - Parent B = per-task champion from previous iteration (read `.harness-evolver/per_task_champion.json`). 
    If no champion file exists, fall back to a non-best version from the archive.

Spawn all 3 using the Agent tool with `subagent_type: "harness-evolver-proposer"`. The first 2 use `run_in_background: true`, the 3rd blocks:

**Candidate A (Exploiter)** — `run_in_background: true`:
```
Agent(
  subagent_type: "harness-evolver-proposer",
  description: "Proposer A (exploit): targeted fix for {version}",
  run_in_background: true,
  prompt: |
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
    - .harness-evolver/langsmith_runs.json (if exists)
    - .harness-evolver/trace_insights.json (if exists)
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
  subagent_type: "harness-evolver-proposer",
  description: "Proposer B (explore): bold change from {explorer_parent}",
  run_in_background: true,
  prompt: |
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
    - .harness-evolver/langsmith_runs.json (if exists)
    - .harness-evolver/trace_insights.json (if exists)
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
  subagent_type: "harness-evolver-proposer",
  description: "Proposer C (crossover): combine {parent_a} + {parent_b}",
  prompt: |
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
    - .harness-evolver/langsmith_runs.json (if exists)
    - .harness-evolver/trace_insights.json (if exists)
    - .harness-evolver/architecture.json (if exists)
    </files_to_read>

    <output>
    Create directory .harness-evolver/harnesses/{version}c/ containing:
    - harness.py, config.json, proposal.md
    </output>
)
```

**Also spawn these additional candidates:**

**Candidate D (Failure-Targeted or Creative)** — `run_in_background: true`:

If failure clusters were found in step 1.8:
```
Agent(
  subagent_type: "harness-evolver-proposer",
  description: "Proposer D: fix {cluster_1_category} failures",
  run_in_background: true,
  prompt: |
    <strategy>
    APPROACH: failure-targeted
    Focus on fixing these SPECIFIC failing tasks: {cluster_1_task_ids}
    They share the pattern: {cluster_1_category} (avg score: {cluster_1_avg})
    Read the traces of these specific tasks to understand WHY they fail.
    Your changes should improve these tasks WITHOUT regressing others.
    You are free to change anything — prompts, code, retrieval, architecture — 
    whatever is needed to fix THIS specific failure mode.
    </strategy>

    <objective>
    Propose harness version {version}d targeting {cluster_1_category} failures.
    </objective>

    <files_to_read>
    - .harness-evolver/summary.json
    - .harness-evolver/PROPOSER_HISTORY.md
    - .harness-evolver/config.json
    - .harness-evolver/harnesses/{best_version}/harness.py
    - .harness-evolver/harnesses/{best_version}/scores.json
    - .harness-evolver/langsmith_runs.json (if exists)
    - .harness-evolver/trace_insights.json (if exists)
    - .harness-evolver/architecture.json (if exists)
    </files_to_read>

    <output>
    Create directory .harness-evolver/harnesses/{version}d/ containing:
    - harness.py, config.json, proposal.md
    </output>
)
```

If ALL_PASSING (no failures):
```
Agent(
  subagent_type: "harness-evolver-proposer",
  description: "Proposer D: creative approach",
  run_in_background: true,
  prompt: |
    <strategy>
    APPROACH: creative
    All tasks are scoring well. Try something UNEXPECTED:
    - Different algorithm or library
    - Completely different prompt architecture
    - Novel error handling or output validation
    - Something no one would think of
    The goal is to discover improvements that incremental fixes would miss.
    </strategy>
    ...same files_to_read and output as above...
)
```

**Candidate E (Failure-Targeted or Efficiency)** — `run_in_background: true`:

If a second failure cluster exists:
```
Agent(
  subagent_type: "harness-evolver-proposer",
  description: "Proposer E: fix {cluster_2_category} failures",
  run_in_background: true,
  prompt: |
    <strategy>
    APPROACH: failure-targeted
    Focus on fixing these SPECIFIC failing tasks: {cluster_2_task_ids}
    They share the pattern: {cluster_2_category} (avg score: {cluster_2_avg})
    Read the traces of these specific tasks to understand WHY they fail.
    Your changes should improve these tasks WITHOUT regressing others.
    You are free to change anything — prompts, code, retrieval, architecture — 
    whatever is needed to fix THIS specific failure mode.
    </strategy>

    <objective>
    Propose harness version {version}e targeting {cluster_2_category} failures.
    </objective>

    <files_to_read>
    - .harness-evolver/summary.json
    - .harness-evolver/PROPOSER_HISTORY.md
    - .harness-evolver/config.json
    - .harness-evolver/harnesses/{best_version}/harness.py
    - .harness-evolver/harnesses/{best_version}/scores.json
    - .harness-evolver/langsmith_runs.json (if exists)
    - .harness-evolver/trace_insights.json (if exists)
    - .harness-evolver/architecture.json (if exists)
    </files_to_read>

    <output>
    Create directory .harness-evolver/harnesses/{version}e/ containing:
    - harness.py, config.json, proposal.md
    </output>
)
```

If no second cluster (or ALL_PASSING):
```
Agent(
  subagent_type: "harness-evolver-proposer",
  description: "Proposer E: efficiency optimization",
  run_in_background: true,
  prompt: |
    <strategy>
    APPROACH: efficiency
    Maintain the current quality but optimize for:
    - Fewer LLM tokens (shorter prompts, less context)
    - Faster execution (reduce unnecessary steps)
    - Simpler code (remove redundant logic)
    - Better error handling (graceful degradation)
    Do NOT sacrifice accuracy for speed — same quality, less cost.
    </strategy>
    ...same files_to_read and output as above...
)
```

Wait for all 5 to complete. The background agents will notify when done.

**Minimum 3 candidates ALWAYS, even on iteration 1.** On iteration 1, the crossover agent uses baseline as both parents but with instruction to "combine the best retrieval strategy with the best prompt strategy from your analysis of the baseline." On iteration 2+, crossover uses two genuinely different parents.

**On iteration 3+**: If scores are improving, keep all 5 strategies. If stagnating, step 1.8 will naturally shift D and E toward failure-targeted or creative strategies based on actual task performance.

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

### 4.5. Judge (if eval returned pending scores)

For each evaluated candidate, read its scores.json. If `eval_type` is `"pending-judge"` (combined_score == -1), the eval was a passthrough and needs judge scoring.

Spawn judge subagent with `subagent_type: "harness-evolver-judge"` for EACH candidate that needs judging:

```
Agent(
  subagent_type: "harness-evolver-judge",
  description: "Judge: score {version}{suffix} outputs",
  prompt: |
    <objective>
    Score the outputs of harness version {version}{suffix} across all {N} tasks.
    </objective>

    <files_to_read>
    - .harness-evolver/harnesses/{version}{suffix}/scores.json
    - .harness-evolver/eval/tasks/ (read all task files)
    </files_to_read>

    <output>
    Overwrite .harness-evolver/harnesses/{version}{suffix}/scores.json with real scores.
    </output>
)
```

Wait for `## JUDGE COMPLETE`.

If eval_type is NOT "pending-judge", the eval.py already produced real scores — skip this step.

### 5. Select Winner + Track Per-Task Champions

**5a. Find overall winner (highest combined_score):**

Compare all evaluated candidates. The winner is the one with highest combined_score.

**5b. Find per-task champion (candidate that beats the winner on most individual tasks):**

```bash
python3 -c "
import json, os

version = '{version}'
candidates = {}
for suffix in ['a', 'b', 'c', 'd', 'e']:
    path = f'.harness-evolver/harnesses/{version}{suffix}/scores.json'
    if os.path.exists(path):
        candidates[suffix] = json.load(open(path))

if not candidates:
    print('NO_CANDIDATES')
    exit()

# Overall winner
winner_suffix = max(candidates, key=lambda s: candidates[s].get('combined_score', 0))
winner_score = candidates[winner_suffix]['combined_score']
print(f'WINNER: {winner_suffix} (score: {winner_score:.3f})')

# Per-task champion: which NON-WINNER candidate beats the winner on the most tasks?
task_wins = {}
winner_tasks = candidates[winner_suffix].get('per_task', {})
for suffix, data in candidates.items():
    if suffix == winner_suffix:
        continue
    wins = 0
    for tid, tdata in data.get('per_task', {}).items():
        winner_task_score = winner_tasks.get(tid, {}).get('score', 0)
        if tdata.get('score', 0) > winner_task_score:
            wins += 1
    if wins > 0:
        task_wins[suffix] = wins

if task_wins:
    champion_suffix = max(task_wins, key=task_wins.get)
    print(f'PER_TASK_CHAMPION: {champion_suffix} (beats winner on {task_wins[champion_suffix]} tasks)')
    # Save champion info for next iteration's crossover parent
    with open('.harness-evolver/per_task_champion.json', 'w') as f:
        json.dump({'suffix': champion_suffix, 'version': f'{version}{champion_suffix}', 'task_wins': task_wins[champion_suffix]}, f)
else:
    print('NO_CHAMPION: winner dominates all tasks')
" 2>/dev/null
```

**5c. Promote winner and report ALL candidates:**

Rename winner directory to official version:
```bash
mv .harness-evolver/harnesses/{version}{winning_suffix} .harness-evolver/harnesses/{version}
```

Update state:
```bash
python3 $TOOLS/state.py update \
    --base-dir .harness-evolver \
    --version {version} \
    --scores .harness-evolver/harnesses/{version}/scores.json \
    --proposal .harness-evolver/harnesses/{version}/proposal.md
```

Report ALL candidates with their scores and strategies:
```
Iteration {i}/{N} — {num_candidates} candidates evaluated:
  {version}a (exploit):          {score_a} — {summary}
  {version}b (explore):          {score_b} — {summary}
  {version}c (crossover):        {score_c} — {summary}
  {version}d ({strategy_d}):     {score_d} — {summary}
  {version}e ({strategy_e}):     {score_e} — {summary}
  
  Winner: {version}{suffix} ({score})
  Per-task champion: {champion_suffix} (beats winner on {N} tasks) — saved for next crossover
```

Keep losing candidates in their directories (they're part of the archive — never discard, per DGM).

### 5.5. Test Suite Growth (Durable Regression Gates)

After the winner is promoted, check if any previously-failing tasks are now passing.
Generate regression tasks to lock in improvements and prevent future regressions:

```bash
PREV_BEST=$(python3 -c "
import json
s = json.load(open('.harness-evolver/summary.json'))
versions = s.get('versions', [])
print(versions[-2]['version'] if len(versions) >= 2 else '')
" 2>/dev/null)
if [ -n "$PREV_BEST" ] && [ -f ".harness-evolver/harnesses/$PREV_BEST/scores.json" ]; then
    python3 $TOOLS/test_growth.py \
        --current-scores .harness-evolver/harnesses/{version}/scores.json \
        --previous-scores ".harness-evolver/harnesses/$PREV_BEST/scores.json" \
        --tasks-dir .harness-evolver/eval/tasks/ \
        --output-dir .harness-evolver/eval/tasks/ \
        --max-total-tasks 60 2>/dev/null
fi
```

If new tasks were added, print: "Added {N} regression tasks to lock in improvements on: {task_ids}"

This is the "durable test gates" pattern: every fixed failure becomes a permanent regression test.
New tasks are tagged with `metadata.type: "regression"` and `metadata.source: "regression"` so they
can be distinguished from original tasks. The test suite only grows — regression tasks are never removed.

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

Dispatch the critic agent:

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

Dispatch the architect agent:

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
