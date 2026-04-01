# Harness Evolver v3 — LangSmith-Native Design Spec

## Overview

v3 is a ground-up redesign that replaces all custom evaluation infrastructure with the LangSmith ecosystem. No more `harness.py` contract, no more `eval.py`, no more `tasks/*.json` files. Everything runs through LangSmith Datasets, Experiments, and Evaluators.

The multi-agent evolution logic (5 proposers, critic, architect, quality-diversity selection) remains. The change is in the *plumbing* — what runs the code, what scores it, and where data lives.

### Requirements

- **LangSmith account + API key** (mandatory)
- **Python with `langsmith` and `openevals` packages** (installed by setup)
- **Git** (for worktree-based isolation)
- **Claude Code** (runtime for skills and agents)

### Core Principles

1. **LangSmith is the backend** — datasets, experiments, evaluators, traces all live there
2. **Proposer modifies real code** — no wrapper harness, changes go to the user's actual files
3. **Git worktrees for isolation** — each proposer gets an isolated copy of the repo
4. **Merge winners automatically** — winning changes are merged into the main branch
5. **Hybrid state** — LangSmith holds data (experiments, traces), local `.evolver.json` holds config

---

## Architecture

```
User's Project (Git repo)
    │
    ├── .evolver.json          ← Local config (project, dataset, evaluators, history)
    │
    ├── [user's code]          ← What proposers modify directly
    │
    └── (worktrees created     ← Temporary isolated copies per proposer
         at runtime)

LangSmith (remote backend)
    │
    ├── Project: evolver-{name}     ← All evolution traces
    ├── Dataset: {name}-eval-v1     ← Test inputs + optional expected outputs
    ├── Experiments: v001a, v001b…  ← Results per candidate per iteration
    ├── Evaluators: configured      ← LLM-as-judge, code-based, pairwise
    └── Production project (opt)    ← Existing production traces
```

---

## Skills

### `/evolver:setup` — Interactive Project Setup

Replaces `/harness-evolver:init`. Explores the project, configures LangSmith, runs baseline.

**allowed-tools**: Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion

**Phase 1 — Explore (automatic)**:
- Scan Python files, detect framework (LangGraph, CrewAI, OpenAI SDK, Anthropic SDK, etc.)
- Identify entry point (command to run the agent)
- Detect existing LangSmith tracing (env vars, .env)
- Detect dependencies (requirements.txt, pyproject.toml, uv.lock)

**Phase 2 — Interactive questions**:

1. **Confirm detection** (simple single-select):
   - Shows detected entry point, framework, LangSmith status
   - Options: "Looks good" / "Let me adjust" / "Wrong directory"

2. **What to optimize** (multi-select):
   - Options: Accuracy / Latency / Token efficiency / Routing / Error handling
   - Determines which evaluators to configure

3. **Test data source** (preview single-select):
   - "Import from LangSmith production traces" (preview: shows project stats)
   - "Generate from code analysis" (preview: shows what testgen does)
   - "I have test inputs" (preview: shows expected format)

**Phase 3 — Configure LangSmith (automatic)**:

```python
from langsmith import Client
from openevals.llm import create_llm_as_judge
from openevals.prompts import CORRECTNESS_PROMPT, CONCISENESS_PROMPT

client = Client()

# 1. Create project
# (LangSmith creates projects implicitly when traces arrive)

# 2. Create dataset
dataset = client.create_dataset(
    dataset_name=f"{project_name}-eval-v1",
    description=f"Evaluation dataset for {project_name}",
)

# 3. Add examples (from production traces, testgen, or user files)
client.create_examples(dataset_id=dataset.id, examples=examples)

# 4. Configure evaluators based on optimization goals
evaluators = []
if "accuracy" in goals:
    evaluators.append(create_llm_as_judge(
        prompt=CORRECTNESS_PROMPT,
        feedback_key="correctness",
        model="openai:gpt-4.1-mini",
    ))
if "conciseness" in goals:
    evaluators.append(create_llm_as_judge(
        prompt=CONCISENESS_PROMPT,
        feedback_key="conciseness",
        model="openai:gpt-4.1-mini",
    ))
# Code-based evaluators for latency, token count, etc.
```

**Phase 4 — Ensure tracing is active**:
- If framework is LangChain/LangGraph: verify `LANGSMITH_TRACING=true` in env
- If OpenAI SDK: instruct user to add `wrap_openai()` or verify it exists
- If Anthropic SDK: instruct user to add `wrap_anthropic()`
- If other: instruct to add `@traceable` decorator or OTEL config

**Phase 5 — Run baseline**:
```python
results = client.evaluate(
    target=run_agent,  # Function that runs the user's agent
    data=dataset_name,
    evaluators=evaluators,
    experiment_prefix="baseline",
)
baseline_score = results.aggregate_metrics["correctness"]["mean"]
```

**Phase 6 — Save .evolver.json**:
```json
{
  "version": "3.0.0",
  "project": "evolver-my-agent",
  "dataset": "my-agent-eval-v1",
  "entry_point": "python main.py",
  "run_command": "python -c \"from my_agent import run; run('{input}')\"",
  "evaluators": ["correctness", "conciseness"],
  "optimization_goals": ["accuracy", "latency"],
  "production_project": "my-production-project",
  "baseline_experiment": "baseline-2026-04-01-abc123",
  "best_experiment": "baseline-2026-04-01-abc123",
  "best_score": 0.45,
  "iterations": 0,
  "framework": "langgraph",
  "history": [
    {"version": "baseline", "experiment": "baseline-2026-04-01-abc123", "score": 0.45}
  ]
}
```

---

### `/evolver:evolve` — Evolution Loop

**allowed-tools**: Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion

**Pre-loop** (interactive, if no --iterations argument):
- AskUserQuestion: iterations (3/5/10) + target score (0.8/0.9/0.95/none)
- Two questions in one call, simple single-select

**Per iteration:**

#### Step 1: Read State
```python
config = json.load(open(".evolver.json"))
best = config["best_experiment"]
```

Read best experiment results from LangSmith:
```python
from langsmith import Client
client = Client()
# Read experiment metrics
project = client.read_project(project_name=best, include_stats=True)
```

#### Step 1.5: Gather Traces + Insights
- Query LangSmith for recent traces (evolution project + production project)
- Run `trace_insights.py` (adapted to read from SDK instead of JSON files)
- Output: `trace_insights.json` (same format as v2, proposers already know how to use it)

#### Step 1.8: Failure Analysis
- Read per-example results from best experiment via SDK
- Cluster failing examples by category
- Generate adaptive briefings for Candidates D and E

#### Step 2: Spawn 5 Proposers in Parallel

Each proposer runs in an **isolated git worktree**:

```
Agent(
  subagent_type: "evolver-proposer",
  description: "Proposer A: exploit best",
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
    </strategy>

    <files_to_read>
    - .evolver.json
    - trace_insights.json (if exists)
    - {entry point file}
    - {other relevant source files}
    </files_to_read>

    <context>
    Best experiment: {best_experiment} (score: {best_score})
    Failing examples: {failing_example_ids}
    Framework: {framework}
    Entry point: {entry_point}
    </context>

    <output>
    Modify the code to improve performance.
    Commit your changes with a descriptive message.
    Write a proposal.md explaining what you changed and why.
    </output>
)
```

The `isolation: "worktree"` parameter is native to Claude Code's Agent tool — it creates a temporary git worktree automatically.

#### Step 3: Evaluate Each Candidate

For each proposer that produced changes (has a worktree with commits):

```python
# tools/run_eval.py
import subprocess
import json
from langsmith import Client

client = Client()
config = json.load(open(".evolver.json"))

# Run evaluate() from within the worktree
# The target function executes the agent using the worktree's modified code
results = client.evaluate(
    target=make_target(worktree_path, config["run_command"]),
    data=config["dataset"],
    evaluators=load_evaluators(config["evaluators"]),
    experiment_prefix=f"v{iteration:03d}{suffix}",
    max_concurrency=1,
)
```

#### Step 4: Select Winner + Per-Task Champions

Read all candidate experiment results:
```python
# tools/read_results.py
experiments = [f"v{iteration:03d}{s}" for s in "abcde"]
scores = {}
per_task = {}
for exp in experiments:
    try:
        project = client.read_project(project_name=exp, include_stats=True)
        # ... extract scores
    except:
        continue
```

Selection logic (same as v2):
- Overall winner = highest mean evaluator score
- Per-task champion = candidate that beats winner on most individual examples
- Champion saved for next iteration's crossover parent

#### Step 5: Merge Winner

```bash
# The winning worktree's branch gets merged
cd {main_repo}
git merge {winning_worktree_branch} --no-edit
```

Update `.evolver.json` with new best experiment.

Cleanup losing worktrees (Claude Code cleans up worktrees with no changes automatically; losing worktrees that have changes need explicit cleanup).

#### Step 5.5: Test Suite Growth (via LangSmith)

Instead of generating regression JSON files, use LangSmith Automation Rules or SDK:
```python
# If a previously-failing example now passes, add variations to the dataset
for example in fixed_examples:
    variations = generate_variations(example["inputs"])
    client.create_examples(
        dataset_id=dataset_id,
        examples=[{"inputs": v} for v in variations],
    )
```

#### Steps 6-8: Report, Critic, Architect, Stop Conditions
Same logic as v2, adapted to read from LangSmith experiments instead of local files.

---

### `/evolver:status` — Show Progress

Reads `.evolver.json` history + LangSmith experiment metrics.
Shows: iterations, best score, improvement trend, stagnation detection.

### `/evolver:deploy` — Promote Best Version

In v3, the best version is **already in the main branch** (merge automático). Deploy skill becomes simpler:
- Show what changed since baseline (git diff)
- Suggest: commit with descriptive message, push to remote
- Optional: tag the version

---

## Agents

### `evolver-proposer.md`

Adapted from v2. Key changes:
- Works in a worktree (isolated copy of the repo)
- Modifies any file (not just harness.py)
- Reads trace insights from LangSmith (same format)
- Reads production seed (same format)
- Context7 for documentation (same)
- Must commit changes before finishing

### `evolver-critic.md`

Adapted from v2. Now checks:
- Are LangSmith evaluators being gamed? (e.g., output matches evaluator prompt phrasing)
- Proposes stricter evaluators or additional evaluation dimensions

### `evolver-architect.md`

Unchanged conceptually. Still recommends topology changes.

### `evolver-testgen.md`

Simplified. Generates inputs for a LangSmith dataset instead of JSON files:
```python
client.create_examples(
    dataset_id=dataset_id,
    examples=[{"inputs": {"question": "..."}} for q in generated_questions],
)
```

---

## Tools (Python, requires `langsmith` + `openevals`)

| Tool | Purpose |
|------|---------|
| `setup.py` | Interactive LangSmith setup (create project, dataset, evaluators) |
| `run_eval.py` | Run `client.evaluate()` for a candidate in a worktree. Creates a target function by: `cd worktree && subprocess.run(entry_point, input=example_json)` → captures stdout as output. The target function wraps the user's entry point command. |
| `read_results.py` | Read experiment results, format for agents |
| `detect_stack.py` | Detect framework from imports (unchanged) |
| `analyze_architecture.py` | Classify topology (unchanged) |
| `trace_insights.py` | Cluster traces + generate insights (adapted to use SDK) |
| `seed_from_traces.py` | Fetch production traces for testgen (adapted to use SDK) |

**Eliminated**: evaluate.py, eval_passthrough.py, eval_llm_judge.py, state.py, init.py, test_growth.py, import_traces.py, trace_logger.py, llm_api.py

---

## Dependencies

**Python** (installed by setup skill):
```
langsmith>=0.3
openevals>=0.1
```

**System**:
- Git (for worktrees)
- Python 3.10+
- Claude Code (runtime)

**Optional**:
- `langsmith-cli` (for quick project listing, but SDK covers everything)
- Context7 MCP (for documentation lookup)

---

## Migration from v2

Users upgrading from v2:
1. Run `/evolver:setup` — it creates LangSmith config from scratch
2. Existing `.harness-evolver/` directory is ignored (can be deleted)
3. Test tasks from v2 can be imported: setup skill detects `tasks/*.json` and offers to import to LangSmith dataset

---

## What's NOT in v3 (deferred)

- **LangSmith Prompt Hub integration** — versioning prompts in LangSmith (future v3.x)
- **Feedback loop** — publishing eval results back as annotations (future v3.x)
- **Online evaluators** — auto-evaluating production traces (future v3.x)
- **Pairwise experiments** — comparing candidates via LLM pairwise evaluation (future v3.x)
- **Multi-repo support** — evolving agents across multiple repos (out of scope)
