# Harness Evolver v3 — Development Guide

## What this is

Claude Code plugin for LangSmith-native autonomous agent optimization. Uses LangSmith Datasets, Experiments, and Evaluators as the backend. Proposers modify the user's real code in isolated git worktrees.

## Project structure

```
tools/           Python tools (requires langsmith)
skills/          Claude Code slash commands (/evolver:setup, /evolver:evolve, etc.)
agents/          Agent definitions (proposer, critic, architect, testgen, evaluator)
bin/             Node.js installer (npx harness-evolver@latest)
docs/            Design specs and plans
```

## Dependencies

```bash
pip install langsmith
```

All tools require the `langsmith` Python SDK. The evaluator agent uses `langsmith-cli` (installed separately via `uv tool install langsmith-cli`). No openevals or external LLM API keys needed.

## Key conventions

- Tools use the LangSmith Python SDK for datasets, experiments, running targets
- The evaluator agent uses `langsmith-cli` to read outputs and write scores (LLM-as-judge)
- Proposer agents work in git worktrees (isolated copies of the repo)
- Winning worktrees are merged automatically into the main branch
- State is hybrid: `.evolver.json` (local config) + LangSmith (data)
- LangSmith API key is mandatory (`LANGSMITH_API_KEY`)
- No external LLM API keys needed (the evaluator agent IS the LLM judge)

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
  4. Run each candidate via client.evaluate() (code-based evaluators only)
  5. Spawn evaluator agent → reads outputs via langsmith-cli, judges correctness,
     writes scores back via langsmith-cli feedback create
  6. Compare LangSmith experiments → select winner
  7. Merge winning worktree into main branch
  8. Auto-trigger critic/architect if needed
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
