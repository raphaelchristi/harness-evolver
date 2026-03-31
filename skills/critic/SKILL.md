---
name: harness-evolver:critic
description: "Use when scores converge suspiciously fast, eval quality is questionable, the harness reaches 1.0 in few iterations, or the user wants to validate that improvements are genuine. Also triggers automatically when score jumps >0.3 in one iteration."
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent]
---

# /harness-evolver:critic

Analyze eval quality and detect eval gaming.

## Resolve Tool Path

```bash
TOOLS=$([ -d ".harness-evolver/tools" ] && echo ".harness-evolver/tools" || echo "$HOME/.harness-evolver/tools")
```

## Prerequisites

`.harness-evolver/` must exist with at least one evaluated version (v001+).

## What To Do

1. Read `summary.json` and identify the suspicious pattern (score jump, premature convergence).

2. Read the critic agent definition:
```bash
cat ~/.claude/agents/harness-evolver-critic.md
```

3. Dispatch using the Agent tool — include the agent definition in the prompt:

```
Agent(
  description: "Critic: analyze eval quality",
  prompt: |
    <agent_instructions>
    {paste the FULL content of harness-evolver-critic.md here}
    </agent_instructions>

    <objective>
    Analyze eval quality for this harness evolution project.
    The best version is {version} with score {score} achieved in {iterations} iteration(s).
    {Specific concern: "Score jumped from X to Y in one iteration" or "Perfect score in N iterations"}
    </objective>

    <files_to_read>
    - .harness-evolver/eval/eval.py
    - .harness-evolver/summary.json
    - .harness-evolver/harnesses/{best_version}/scores.json
    - .harness-evolver/harnesses/{best_version}/harness.py
    - .harness-evolver/harnesses/{best_version}/proposal.md
    - .harness-evolver/config.json
    - .harness-evolver/langsmith_stats.json (if exists)
    </files_to_read>

    <output>
    Write:
    - .harness-evolver/critic_report.md (human-readable analysis)
    - .harness-evolver/eval/eval_improved.py (if weaknesses found)
    </output>

    <success_criteria>
    - Identifies specific weaknesses in eval.py with examples
    - If gaming detected, shows exact tasks/outputs that expose the weakness
    - Improved eval preserves the --results-dir/--tasks-dir/--scores interface
    - Re-scores the best version with improved eval to quantify the difference
    </success_criteria>
)
```

3. Wait for `## CRITIC REPORT COMPLETE`.

4. Report findings to user. If `eval_improved.py` was written:
   - Show score comparison (current eval vs improved eval)
   - Ask: "Adopt the improved eval? This will affect future iterations."
