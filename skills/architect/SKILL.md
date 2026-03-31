---
name: harness-evolver:architect
description: "Use when the user wants to analyze harness architecture, get a topology recommendation, understand if their agent pattern is optimal, or after stagnation in the evolution loop."
argument-hint: "[--force]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent]
---

# /harness-evolver:architect

Analyze the current harness architecture and recommend the optimal multi-agent topology.

## Prerequisites

`.harness-evolver/` must exist. If not, tell user to run `harness-evolver:init` first.

```bash
if [ ! -d ".harness-evolver" ]; then
  echo "ERROR: .harness-evolver/ not found. Run /harness-evolver:init first."
  exit 1
fi
```

## Resolve Tool Path

```bash
TOOLS=$([ -d ".harness-evolver/tools" ] && echo ".harness-evolver/tools" || echo "$HOME/.harness-evolver/tools")
```

Use `$TOOLS` prefix for all tool calls below.

## What To Do

1. Check `.harness-evolver/` exists.

2. Run architecture analysis tool:
```bash
python3 $TOOLS/analyze_architecture.py \
    --harness .harness-evolver/baseline/harness.py \
    -o .harness-evolver/architecture_signals.json
```

If evolution has run, add trace and score data:
```bash
python3 $TOOLS/analyze_architecture.py \
    --harness .harness-evolver/harnesses/{best}/harness.py \
    --traces-dir .harness-evolver/harnesses/{best}/traces \
    --summary .harness-evolver/summary.json \
    -o .harness-evolver/architecture_signals.json
```

3. Dispatch subagent using the **Agent tool** with `subagent_type: "harness-evolver-architect"`:

```
Agent(
  subagent_type: "harness-evolver-architect",
  description: "Architect: topology analysis",
  prompt: |
    <objective>
    Analyze the harness architecture and recommend the optimal multi-agent topology.
    {If called from evolve: "The evolution loop stagnated/regressed after N iterations."}
    {If called by user: "The user requested an architecture analysis."}
    </objective>

    <files_to_read>
    - .harness-evolver/architecture_signals.json
    - .harness-evolver/config.json
    - .harness-evolver/baseline/harness.py
    - .harness-evolver/summary.json (if exists)
    - .harness-evolver/PROPOSER_HISTORY.md (if exists)
    </files_to_read>

    <output>
    Write:
    - .harness-evolver/architecture.json
    - .harness-evolver/architecture.md
    </output>

    <success_criteria>
    - Classifies current topology correctly
    - Recommendation includes migration path with concrete steps
    - Considers detected stack and API key availability
    - Confidence rating is honest (low/medium/high)
    </success_criteria>
)
```

4. Wait for `## ARCHITECTURE ANALYSIS COMPLETE`.

5. Print summary: current -> recommended, confidence, migration steps.

## Arguments

- `--force` — re-run analysis even if `architecture.json` already exists. Without this flag, if `architecture.json` exists, just display the existing recommendation.
