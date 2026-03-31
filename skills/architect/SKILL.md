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

## Step 1: Run Architecture Analysis

Build the command based on what exists:

```bash
CMD="python3 $TOOLS/analyze_architecture.py --harness .harness-evolver/baseline/harness.py"

# Add traces from best version if evolution has run
if [ -f ".harness-evolver/summary.json" ]; then
  BEST=$(python3 -c "import json; s=json.load(open('.harness-evolver/summary.json')); print(s.get('best',{}).get('version',''))")
  if [ -n "$BEST" ] && [ -d ".harness-evolver/harnesses/$BEST/traces" ]; then
    CMD="$CMD --traces-dir .harness-evolver/harnesses/$BEST/traces"
  fi
  CMD="$CMD --summary .harness-evolver/summary.json"
fi

CMD="$CMD -o .harness-evolver/architecture_signals.json"

eval $CMD
```

Check exit code. If it fails, report the error and stop.

## Step 2: Spawn Architect Agent

Spawn the `harness-evolver-architect` agent with:

> Analyze the harness and recommend the optimal multi-agent topology.
> Raw signals are at `.harness-evolver/architecture_signals.json`.
> Write `.harness-evolver/architecture.json` and `.harness-evolver/architecture.md`.

The architect agent will:
1. Read the signals JSON
2. Read the harness code and config
3. Classify the current topology
4. Assess if it matches task complexity
5. Recommend the optimal topology with migration steps
6. Write `architecture.json` and `architecture.md`

## Step 3: Report

After the architect agent completes, read the outputs and print a summary:

```
Architecture Analysis Complete
==============================
Current topology:     {current_topology}
Recommended topology: {recommended_topology}
Confidence:           {confidence}

Reasoning: {reasoning}

Migration Path:
  1. {step 1 description}
  2. {step 2 description}
  ...

Risks:
  - {risk 1}
  - {risk 2}

Next: Run /harness-evolver:evolve — the proposer will follow the migration path.
```

If the architect recommends no change (current = recommended), report:

```
Architecture Analysis Complete
==============================
Current topology: {topology} — looks optimal for these tasks.
No architecture change recommended. Score: {score}

The proposer can continue evolving within the current topology.
```

## Arguments

- `--force` — re-run analysis even if `architecture.json` already exists. Without this flag, if `architecture.json` exists, just display the existing recommendation.
