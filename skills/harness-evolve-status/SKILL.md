---
name: harness-evolve-status
description: "Show the current status of harness evolution: best score, iteration count, progress history."
allowed-tools: [Read, Bash]
---

# /harness-evolve-status

Show the current evolution status.

## What To Do

```bash
python3 ~/.harness-evolver/tools/state.py show --base-dir .harness-evolver
```

If that doesn't exist, try:

```bash
python3 .harness-evolver/tools/state.py show --base-dir .harness-evolver
```

Also read and display the contents of `.harness-evolver/STATE.md` for the full status table.

If `.harness-evolver/` doesn't exist, tell the user to run `/harness-evolve-init` first.
