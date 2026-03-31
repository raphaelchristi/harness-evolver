---
name: harness-evolver:init
description: "Use when the user wants to set up harness optimization in their project, optimize an LLM agent, improve a harness, or mentions harness-evolver for the first time in a project without .harness-evolver/ directory."
argument-hint: "[directory]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent]
---

# /harness-evolve-init

Set up the Harness Evolver in a project. Scans the codebase, identifies the entry point, creates missing artifacts, runs baseline evaluation.

## Resolve Tool Path

```bash
TOOLS=$([ -d ".harness-evolver/tools" ] && echo ".harness-evolver/tools" || echo "$HOME/.harness-evolver/tools")
```

Use `$TOOLS` prefix for all tool calls below.

## Phase 1: Scan

```bash
find . -maxdepth 3 -type f -name "*.py" | head -30
python3 $TOOLS/detect_stack.py .
```

Look for:
- Entry points: files with `if __name__`, or named `main.py`, `app.py`, `agent.py`, `graph.py`, `pipeline.py`, `bot.py`
- Existing eval: `eval.py`, `score.py`, `judge.py`
- Existing tasks: directories with JSON files containing `id` + `input` fields
- Config: `config.json`, `config.yaml`, `.env`

## Phase 2: Create What's Missing

Three artifacts needed. For each — use existing if found, create if not.

**Harness** (`harness.py`): If user's entry point doesn't match our CLI interface (`--input`, `--output`, `--traces-dir`, `--config`), create a thin wrapper that imports their code. Read their entry point first to understand the I/O format. Ask if unsure.

**Eval** (`eval.py`): If an eval script exists, use it.

If NO eval exists:
- Copy `eval_passthrough.py` from `$TOOLS/eval_passthrough.py` as the project's eval.py:
  ```bash
  cp $TOOLS/eval_passthrough.py eval.py
  ```
- This passthrough eval collects outputs for the judge subagent to score during evolve.
- Print: "No eval found. Using LLM-as-judge (Claude Code scores outputs directly)."

**Tasks** (`tasks/`): If test tasks exist, use them.

If NO tasks exist, generate them. First, identify all relevant source files:

```bash
find . -name "*.py" -not -path "./.venv/*" -not -path "./.harness-evolver/*" | head -10
find . -name "*.json" -o -name "*.md" -o -name "*.txt" -o -name "*.yaml" -o -name "*.yml" | grep -v .venv | grep -v .harness-evolver | head -10
```

Then spawn testgen subagent with CONCRETE file paths (not placeholders):

```
Agent(
  subagent_type: "harness-evolver-testgen",
  description: "TestGen: generate 30 test cases",
  prompt: |
    <objective>
    Generate 30 diverse test cases for this project. Write them to the tasks/ directory
    in the current working directory.
    </objective>

    <project_context>
    This project is at: {absolute path to project root}
    Entry point: {the harness/agent file you identified, e.g., crew.py or pipeline/moderator.py}
    Framework: {what you detected — CrewAI, LangGraph, etc.}
    </project_context>

    <files_to_read>
    {LIST EVERY .py file and data file you found above — use ABSOLUTE PATHS}
    Example:
    - /home/rp/Desktop/test-crewai/crew.py
    - /home/rp/Desktop/test-crewai/README.md
    </files_to_read>

    <output>
    Create directory tasks/ (at project root) with 30 files: task_001.json through task_030.json.
    Format: {"id": "task_001", "input": "...", "metadata": {"difficulty": "easy|medium|hard", "type": "standard|edge|cross_domain|adversarial"}}
    No "expected" field needed — the judge subagent will score outputs.
    Distribution: 40% standard, 20% edge, 20% cross-domain, 20% adversarial.
    </output>
)
```

Wait for `## TESTGEN COMPLETE`. If the subagent fails or returns with no tasks, generate them yourself inline (fallback).

Print: "Generated {N} test cases from code analysis."

## Phase 3: Run Init

```bash
python3 $TOOLS/init.py [directory] \
    --harness harness.py --eval eval.py --tasks tasks/ \
    --tools-dir $TOOLS
```

Add `--harness-config config.json` if a config exists.

## After Init — Report

- What was detected vs created
- Stack + integrations (LangSmith, Context7)
- Baseline score
- Next: `harness-evolver:evolve` to start

## Architecture Hint

After init completes, run a quick architecture analysis:

```bash
python3 $TOOLS/analyze_architecture.py --harness .harness-evolver/baseline/harness.py
```

If the analysis suggests the current topology may not be optimal for the task complexity, mention it:

> Architecture note: Current topology is "{topology}". For tasks with {characteristics},
> consider running `/harness-evolver:architect` for a detailed recommendation.

This is advisory only — do not spawn the architect agent.

## Gotchas

- The harness must write valid JSON to `--output`. If the user's code returns non-JSON, the wrapper must serialize it.
- Tasks must have unique `id` fields. Duplicate IDs cause silent eval errors.
- The `expected` field is never shown to the harness — only the eval script sees it.
- If `.harness-evolver/` already exists, warn before overwriting.
- If no Python files exist in CWD, the user is probably in the wrong directory.
