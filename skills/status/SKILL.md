---
name: status
description: "Use when the user asks about evolution progress, current scores, best harness version, how many iterations ran, or whether the loop is stagnating. Also use when the user says 'status', 'progress', or 'how is it going'."
allowed-tools: [Read, Bash]
---

# /harness-evolve-status

Show evolution progress.

## Resolve Tool Path

```bash
TOOLS=$([ -d ".harness-evolver/tools" ] && echo ".harness-evolver/tools" || echo "$HOME/.harness-evolver/tools")
```

## What To Do

If `.harness-evolver/` does not exist, tell user to run `harness-evolver:init` first.

Otherwise:

```bash
python3 $TOOLS/state.py show --base-dir .harness-evolver
```

Then read and display `.harness-evolver/STATE.md` for the full history table.

## If User Wants More Detail

- Scores per task: `cat .harness-evolver/harnesses/{version}/scores.json`
- What changed: `cat .harness-evolver/harnesses/{version}/proposal.md`
- Compare two versions: `diff .harness-evolver/harnesses/{vA}/harness.py .harness-evolver/harnesses/{vB}/harness.py`
- Full history: `cat .harness-evolver/PROPOSER_HISTORY.md`
