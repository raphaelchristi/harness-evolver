---
name: harness-evolve-init
description: "Initialize harness evolution in the current project. Sets up .harness-evolver/ with baseline harness, eval script, and tasks."
argument-hint: "--harness <path> --eval <path> --tasks <path>"
allowed-tools: [Read, Write, Bash, Glob]
---

# /harness-evolve-init

Initialize the Harness Evolver for this project.

## Arguments

- `--harness <path>` — path to the harness script (any executable, typically Python)
- `--eval <path>` — path to the evaluation script
- `--tasks <path>` — path to the tasks directory (JSON files with id, input, expected)

## What To Do

Run the init tool:

```bash
python3 ~/.harness-evolver/tools/init.py \
    --harness {harness} \
    --eval {eval} \
    --tasks {tasks} \
    --base-dir .harness-evolver \
    --harness-config {config if provided, else omit} \
    --tools-dir ~/.harness-evolver/tools
```

If `~/.harness-evolver/tools/init.py` does not exist, check `.harness-evolver/tools/init.py` (local override).

After init completes, report:
- Baseline score
- Number of tasks
- Next step: run `/harness-evolve` to start the optimization loop

## LangSmith Dataset (optional)

If the user provides `--langsmith-dataset <dataset_id>`:

```bash
python3 ~/.harness-evolver/tools/init.py \
    --harness {harness} \
    --eval {eval} \
    --tasks {tasks} \
    --base-dir .harness-evolver \
    --langsmith-dataset {dataset_id}
```

This pulls examples from a LangSmith dataset to use as tasks.
Requires `LANGSMITH_API_KEY` in the environment.
