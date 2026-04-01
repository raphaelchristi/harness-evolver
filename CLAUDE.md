# Harness Evolver v3 — Development Guide

## What this is

Claude Code plugin for LangSmith-native autonomous agent optimization. Uses LangSmith Datasets, Experiments, and Evaluators as the backend. Proposers modify the user's real code in isolated git worktrees.

## Project structure

```
tools/           Python tools (requires langsmith + openevals)
skills/          Claude Code slash commands (/evolver:setup, /evolver:evolve, etc.)
agents/          Agent definitions (proposer, critic, architect, testgen)
bin/             Node.js installer (npx harness-evolver@latest)
docs/            Design specs and plans
```

## Dependencies

```bash
pip install langsmith openevals
```

All tools require the `langsmith` Python SDK. No stdlib-only constraint in v3.

## Key conventions

- Tools use the LangSmith Python SDK for datasets, experiments, evaluators
- Proposer agents work in git worktrees (isolated copies of the repo)
- Winning worktrees are merged automatically into the main branch
- State is hybrid: `.evolver.json` (local config) + LangSmith (data)
- LangSmith API key is mandatory (`LANGSMITH_API_KEY`)

## Architecture (3 layers)

1. **Skills/Agents (markdown)** — orchestrate the AI (proposer, evolve loop, setup)
2. **Tools (Python + langsmith SDK)** — evaluation, trace analysis, setup
3. **Installer (Node.js)** — distribution via npx, copies files to ~/.claude/ and ~/.evolver/

## The evolution loop

```
/evolver:evolve → for each iteration:
  1. Gather trace insights from LangSmith
  2. Spawn 5 proposers in parallel (each in a git worktree)
  3. Each proposer modifies real code, commits changes
  4. Evaluate each candidate via client.evaluate() against LangSmith dataset
  5. Compare LangSmith experiments → select winner
  6. Merge winning worktree into main branch
  7. Auto-trigger critic/architect if needed
```

## Local config (.evolver.json)

```json
{
  "version": "3.0.0",
  "project": "evolver-my-agent",
  "dataset": "my-agent-eval-v1",
  "entry_point": "python main.py",
  "evaluators": ["correctness", "conciseness"],
  "best_experiment": "v003-...",
  "best_score": 0.85,
  "iterations": 3
}
```
