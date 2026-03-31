---
name: harness-evolve-init
description: "Initialize harness evolution in the current project. Auto-detects harness.py, eval.py, and tasks/ in the working directory."
argument-hint: "[directory] [--harness <path>] [--eval <path>] [--tasks <path>]"
allowed-tools: [Read, Write, Bash, Glob]
---

# /harness-evolve-init

Initialize the Harness Evolver for this project.

## Usage

```
/harness-evolve-init                    # auto-detect everything in CWD
/harness-evolve-init ./my-project       # auto-detect in a specific directory
/harness-evolve-init --harness run.py   # override one path, auto-detect the rest
```

## How Auto-Detection Works

The tool scans the directory for:
1. **Exact names:** `harness.py`, `eval.py`, `tasks/`, `config.json`
2. **Fuzzy fallback:** `*harness*`, `*agent*`, `*run*` for harness; `*eval*`, `*score*` for eval; any dir with JSON files containing `id`/`input` fields for tasks

If all 3 are found, init proceeds immediately. If something is missing, it reports what's needed.

## What To Do

Run the init tool:

```bash
python3 ~/.harness-evolver/tools/init.py {directory if provided} \
    --tools-dir ~/.harness-evolver/tools
```

Add explicit flags only if the user provided them:
- `--harness PATH` — override harness auto-detection
- `--eval PATH` — override eval auto-detection
- `--tasks PATH` — override tasks auto-detection
- `--harness-config PATH` — optional config for the harness

If `~/.harness-evolver/tools/init.py` does not exist, check `.harness-evolver/tools/init.py` (local override).

After init completes, report:
- What was detected (harness, eval, tasks)
- Baseline score
- Number of tasks
- Integrations detected (LangSmith, Context7, stack)
- Next step: run `/harness-evolve` to start the optimization loop
