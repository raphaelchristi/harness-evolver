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

# Run evaluation for a candidate in a worktree (canary preflight runs 1 example first)
python tools/run_eval.py --config .evolver.json --worktree-path /tmp/wt --experiment-prefix v001a
# Default concurrency is 3. Use --concurrency 1 for agents that can't run in parallel (shared files, fixed ports, etc)
# Use --sample 10 to evaluate a random subset (used by light mode)
# Use --no-canary to skip preflight check

# Compare experiment results
python tools/read_results.py --experiments v001a,v001b --config .evolver.json --output comparison.json

# Trace analysis from an existing experiment
python tools/trace_insights.py --from-experiment "v003-2026-04-01" --output trace_insights.json

# Import production traces as test data
python tools/seed_from_traces.py --project my-prod-project --output-md production_seed.md --output-json production_seed.json

# AST-based architecture analysis (stdlib-only, no langsmith needed)
python tools/analyze_architecture.py --harness path/to/agent -o output.json

# Evolution progress chart (stdlib-only, no langsmith needed)
python tools/evolution_chart.py --config .evolver.json

# Integrated preflight check (API key + schema + state + health + canary)
python tools/preflight.py --config .evolver.json

# Archive evolution candidate (stdlib-only, no langsmith needed)
python tools/archive.py --config .evolver.json --version v001 --experiment v001-abc --worktree-path /tmp/wt --score 0.85 --won
python tools/archive.py --config .evolver.json --list

# Constraint validation for proposals (stdlib-only, no langsmith needed)
python tools/constraint_check.py --config .evolver.json --worktree-path /tmp/wt --baseline-path .

# Secret detection in text (stdlib-only, pipe text to stdin)
echo "text with API keys" | python tools/secret_filter.py

# Mine Claude Code sessions for eval data (stdlib-only)
python tools/mine_sessions.py --agent-description "my agent" --output mined.json

# Dataset health diagnostic (size, difficulty, coverage, splits)
python tools/dataset_health.py --config .evolver.json --output health_report.json

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

1. **Skills** (`skills/*/SKILL.md`) — Claude Code slash commands that orchestrate the workflow. Each skill is a markdown file with frontmatter (`name`, `description`, `allowed-tools`). The five skills are `setup`, `evolve`, `health`, `status`, `deploy`.

2. **Agents** (`agents/*.md`) — Markdown agent definitions spawned by skills via `Agent()`. Six agent types: `harness-proposer` (green, self-organizing with lens protocol, runs in worktree with `acceptEdits`), `harness-evaluator` (yellow, LLM-as-judge via langsmith-cli), `harness-critic` (red, active — detects + fixes gaming), `harness-architect` (blue, ULTRAPLAN mode with opus), `harness-consolidator` (cyan, cross-iteration memory), `harness-testgen` (cyan). Each has a frontmatter block defining `name`, `tools`, `color`, and `permissionMode`.

3. **Tools** (`tools/*.py`) — Python scripts that interface with LangSmith SDK. All tools share a common `ensure_langsmith_api_key()` pattern that loads the key from the credentials file if not in env. `analyze_architecture.py`, `evolution_chart.py`, `constraint_check.py`, `secret_filter.py`, and `mine_sessions.py` are stdlib-only (no langsmith dependency). `validate_state.py`, `iteration_gate.py`, `regression_tracker.py`, `consolidate.py`, `synthesize_strategy.py`, `add_evaluator.py`, and `dataset_health.py` are new v4.0+ tools. `evolution_chart.py` renders a rich ASCII evolution chart with score progression, per-evaluator breakdown, change narrative, and bar chart. `dataset_health.py` checks dataset quality (size, difficulty distribution, coverage, splits) and outputs actionable corrections. `consolidate.py` and `synthesize_strategy.py` are stdlib-only (no langsmith dependency for core logic).

Supporting infrastructure:
- **Plugin manifest** (`.claude-plugin/plugin.json`) — registers as a Claude Code plugin
- **Hooks** (`hooks/hooks.json` + `hooks/session-start.sh`) — SessionStart hook creates venv, installs deps, exports `EVOLVER_TOOLS` and `EVOLVER_PY` env vars via `$CLAUDE_ENV_FILE`
- **Installer** (`bin/install.js`) — Node.js interactive installer invoked via `npx harness-evolver@latest`, copies files to `~/.claude/` and `~/.evolver/`

## The evolution loop (how skills and agents connect)

`/harness:setup` → explores project, asks user questions via `AskUserQuestion`, runs `setup.py` → writes `.evolver.json`

`/harness:health` → checks dataset quality (size, difficulty, coverage, splits), auto-corrects issues

`/harness:evolve` → reads `.evolver.json`, invokes `/harness:health`, then per iteration:
1. `trace_insights.py` gathers failure data from best experiment
2. Claude generates `strategy.md` + `lenses.json` directly from analysis data (no intermediate Python tool)
3. Spawns N `harness-proposer` agents in parallel (each in `isolation: "worktree"`, `run_in_background: true`) with dynamic investigation lenses — each proposer self-organizes its approach and may self-abstain
4. `run_eval.py` evaluates each candidate (code-based evaluators only)
5. Spawns 1 `harness-evaluator` agent to score ALL candidates via langsmith-cli (LLM-as-judge)
6. `read_results.py` compares experiments, picks winner + per-task champion
7. Merges winning worktree branch into main, updates `.evolver.json`
8. Claude assesses gate conditions (plateau, target, diminishing returns) — no intermediate Python tool
9. Auto-triggers `harness-critic` if score jumped >0.3, `harness-architect` if stagnated

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
- Evolution modes: `light` (20 examples, 2 proposers, ~2 min/iter), `balanced` (30, 3, ~8 min), `heavy` (50, 5, ~25 min). Set in `.evolver.json` `mode` field or via `--mode` flag.
- Entry points support three input placeholders: `{input}` (JSON file path), `{input_text}` (extracted plain text, shell-escaped), `{input_json}` (inline JSON string). Use `{input_text}` for agents that take `--query "text"` or positional text arguments.
- `run_eval.py` runs a canary (1 example preflight) before full evaluation to catch broken agents early. Disable with `--no-canary`.
- `read_results.py` outputs both single-experiment and multi-experiment comparison modes (controlled by `--experiment` vs `--experiments`)
- `trace_insights.py` supports two modes: SDK mode (`--from-experiment`) and legacy file mode (`--langsmith-runs` + `--scores`)
- The installer (`bin/install.js`) handles both plugin and npx distribution paths
