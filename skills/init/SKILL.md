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

**Eval** (`eval.py`): Ask the user what "correct" means for their domain. Generate the simplest eval that gives signal. Even rough scoring works — the evolver iterates.

**Tasks** (`tasks/`): If no test data exists, ask the user for 5-10 example input/output pairs. Each task is `{"id": "task_001", "input": "...", "expected": "...", "metadata": {}}`.

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
