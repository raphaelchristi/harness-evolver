# Harness Evolver — Development Guide

## What this is

Claude Code plugin for Meta-Harness-style autonomous harness optimization. Proposes, evaluates, and iterates on LLM harness designs using full execution traces as feedback.

## Project structure

```
tools/           Python stdlib-only CLI tools (evaluate.py, state.py, init.py, detect_stack.py, trace_logger.py)
skills/          Markdown slash commands for Claude Code (/harness-evolve-init, /harness-evolve, /harness-evolve-status)
agents/          Proposer agent definition (the core of the optimization loop)
bin/             Node.js installer (npx harness-evolver@latest)
examples/        Classifier example with mock mode for testing
tests/           Python unittest tests (run with: python3 -m unittest discover -s tests -v)
docs/specs/      Design specs (harness-evolver, langsmith integration, context7 integration)
docs/plans/      Implementation plans
```

## Running tests

```bash
python3 -m unittest discover -s tests -v
```

All tools are stdlib-only Python. No pip install needed. Tests use the examples/classifier/ as a fixture.

## Key conventions

- Tools are standalone CLI scripts callable via subprocess (argparse-based)
- All Python code is stdlib-only (no external dependencies)
- The proposer agent navigates a .harness-evolver/ filesystem with grep/cat/diff
- LangSmith integration uses langsmith-cli (not a custom API client)
- Context7 integration uses MCP tools (resolve-library-id, get-library-docs)
- Both integrations are optional — the core loop works without them

## Architecture (3 layers)

1. **Skills/Agents (markdown)** — orchestrate the AI (proposer, evolve loop, init, status)
2. **Tools (Python)** — deterministic operations (evaluate, state, init, detect_stack)
3. **Installer (Node.js)** — distribution via npx, copies files to ~/.claude/ and ~/.harness-evolver/

## The evolution loop

```
/harness-evolve → for each iteration:
  1. Spawn proposer agent → reads filesystem, proposes new harness
  2. Validate → evaluate.py validate
  3. Evaluate → evaluate.py run (captures traces per task)
  4. Update state → state.py update (summary.json, STATE.md, PROPOSER_HISTORY.md)
  5. Report → score delta, regression detection, stagnation check
```

## Config files (in .harness-evolver/)

- `config.json` — project config (harness command, eval command, evolution params, stack, langsmith)
- `summary.json` — source of truth (all versions, scores, parents)
- `STATE.md` — human-readable view (generated from summary.json)
- `PROPOSER_HISTORY.md` — consolidated log of all proposals and outcomes
