# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Claude Code plugin for LangSmith-native autonomous agent optimization. Uses LangSmith Datasets, Experiments, and Evaluators as the backend. Proposers modify the user's real code in isolated git worktrees. Distributed via npm (`npx harness-evolver@latest`) and the Claude Code plugin marketplace.

## Dependencies

```bash
pip install langsmith                    # Python SDK — used by all tools
uv tool install langsmith-cli            # CLI — used by evaluator agent for reading runs and writing feedback
```

The SessionStart hook (`hooks/session-start.sh`) auto-creates a venv and installs both on each session.

## Running tools locally

All Python tools live in `tools/` and require the langsmith SDK. They auto-load the API key from the langsmith-cli credentials file if `LANGSMITH_API_KEY` is not in the environment.

```bash
# Setup — creates dataset, evaluators, baseline, writes .evolver.json
python tools/setup.py --project-name my-agent --entry-point "python main.py" --framework langgraph --goals accuracy

# Run evaluation for a candidate in a worktree
python tools/run_eval.py --config .evolver.json --worktree-path /tmp/wt --experiment-prefix v001a

# Compare experiment results
python tools/read_results.py --experiments v001a,v001b --config .evolver.json --output comparison.json

# Trace analysis from an existing experiment
python tools/trace_insights.py --from-experiment "v003-2026-04-01" --output trace_insights.json

# Import production traces as test data
python tools/seed_from_traces.py --project my-prod-project --output-md production_seed.md --output-json production_seed.json

# AST-based architecture analysis (stdlib-only, no langsmith needed)
python tools/analyze_architecture.py --harness path/to/agent -o output.json

# Validate state before evolution
python tools/validate_state.py --config .evolver.json --output validation.json

# Check iteration gates
python tools/iteration_gate.py --config .evolver.json --output gate_result.json

# Track regressions between iterations
python tools/regression_tracker.py --config .evolver.json --previous-experiment v001a --current-experiment v002c --output regression_report.json

# Consolidate cross-iteration memory
python tools/consolidate.py --config .evolver.json --output evolution_memory.md

# Synthesize evolution strategy document
python tools/synthesize_strategy.py --config .evolver.json --output strategy.md

# Add evaluator to config
python tools/add_evaluator.py --config .evolver.json --evaluator factual_accuracy --type llm

# Inject adversarial examples
python tools/adversarial_inject.py --config .evolver.json --experiment v003a --inject
```

## Testing

No test framework is configured. The `tests/` directory contains only `__pycache__`. Python tools can be tested by running them directly with the flags above.

## Architecture

Three layers, each in its own directory:

1. **Skills** (`skills/*/SKILL.md`) — Claude Code slash commands that orchestrate the workflow. Each skill is a markdown file with frontmatter (`name`, `description`, `allowed-tools`). The four skills are `setup`, `evolve`, `status`, `deploy`.

2. **Agents** (`agents/*.md`) — Markdown agent definitions spawned by skills via `Agent()`. Five agent types: `evolver-proposer` (green, runs in worktree with `acceptEdits`), `evolver-evaluator` (yellow, LLM-as-judge via langsmith-cli), `evolver-critic` (red), `evolver-architect` (blue), `evolver-testgen` (cyan). Each has a frontmatter block defining `name`, `tools`, `color`, and `permissionMode`.

3. **Tools** (`tools/*.py`) — Python scripts that interface with LangSmith SDK. All tools share a common `ensure_langsmith_api_key()` pattern that loads the key from the credentials file if not in env. `seed_from_traces.py` and `analyze_architecture.py` are stdlib-only (no langsmith dependency). `validate_state.py`, `iteration_gate.py`, `regression_tracker.py`, `consolidate.py`, `synthesize_strategy.py`, and `add_evaluator.py` are new v4.0 tools. `consolidate.py` and `synthesize_strategy.py` are stdlib-only (no langsmith dependency for core logic).

Supporting infrastructure:
- **Plugin manifest** (`.claude-plugin/plugin.json`) — registers as a Claude Code plugin
- **Hooks** (`hooks/hooks.json` + `hooks/session-start.sh`) — SessionStart hook creates venv, installs deps, exports `EVOLVER_TOOLS` and `EVOLVER_PY` env vars via `$CLAUDE_ENV_FILE`
- **Installer** (`bin/install.js`) — Node.js interactive installer invoked via `npx harness-evolver@latest`, copies files to `~/.claude/` and `~/.evolver/`

## The evolution loop (how skills and agents connect)

`/evolver:setup` → explores project, asks user questions via `AskUserQuestion`, runs `setup.py` → writes `.evolver.json`

`/evolver:evolve` → reads `.evolver.json`, then per iteration:
1. `trace_insights.py` gathers failure data from best experiment
2. `read_results.py` analyzes per-task failures for adaptive briefings
3. Spawns 5 `evolver-proposer` agents in parallel (each in `isolation: "worktree"`, `run_in_background: true`) with strategies: exploit, explore, crossover, 2x failure-targeted
4. `run_eval.py` evaluates each candidate (code-based evaluators only)
5. Spawns 1 `evolver-evaluator` agent to score ALL candidates via langsmith-cli (LLM-as-judge)
6. `read_results.py` compares experiments, picks winner + per-task champion
7. Merges winning worktree branch into main, updates `.evolver.json`
8. Auto-triggers `evolver-critic` if score jumped >0.3, `evolver-architect` if stagnated 3 iterations

## Dev skills (`.claude/`)

Development tools for working on the plugin itself (not for end users):

- `/dev:validate` — checks plugin integrity: skill/agent frontmatter, cross-references between skills and agents, Python tool syntax, version sync between `package.json` and `plugin.json`, hook script executability
- `/dev:dry-run` — smoke-tests the full evolve pipeline with a mock Python agent. **Online mode** (with `LANGSMITH_API_KEY`) runs setup → eval → read_results → trace_insights end-to-end. **Offline mode** validates tool syntax and argparse flag consistency against the evolve skill
- `/dev:release` — interactive release: runs validation, bumps version in both `package.json` and `.claude-plugin/plugin.json`, generates changelog from commits, creates git tag, optionally publishes to npm

Run `/dev:validate` before any release. Run `/dev:dry-run` after changing Python tools or skill orchestration logic.

## Key conventions

- Skills resolve tool paths via env vars: `$EVOLVER_TOOLS` (tool directory) and `$EVOLVER_PY` (venv python), with fallbacks to `~/.evolver/` for npx installs
- State is split: `.evolver.json` (local config with best score, iteration count, history) + LangSmith (datasets, experiments, feedback)
- The evaluator agent IS the LLM judge — no external LLM API keys needed, no openevals dependency
- Proposers write `proposal.md` explaining their changes alongside code modifications
- `read_results.py` outputs both single-experiment and multi-experiment comparison modes (controlled by `--experiment` vs `--experiments`)
- `trace_insights.py` supports two modes: SDK mode (`--from-experiment`) and legacy file mode (`--langsmith-runs` + `--scores`)
- The installer (`bin/install.js`) handles both plugin and npx distribution paths
