<p align="center">
  <img src="assets/banner.jpg" alt="Harness Evolver" width="100%">
</p>

# Harness Evolver

<p align="center">
  <a href="https://www.npmjs.com/package/harness-evolver"><img src="https://img.shields.io/npm/v/harness-evolver?style=for-the-badge&color=blueviolet" alt="npm"></a>
  <a href="https://github.com/raphaelchristi/harness-evolver/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://arxiv.org/abs/2603.28052"><img src="https://img.shields.io/badge/Paper-Meta--Harness-FFD700?style=for-the-badge" alt="Paper"></a>
  <a href="https://github.com/raphaelchristi/harness-evolver"><img src="https://img.shields.io/badge/Built%20by-Raphael%20Valdetaro-ff69b4?style=for-the-badge" alt="Built by Raphael Valdetaro"></a>
</p>

**LangSmith-native autonomous agent optimization.** Point at any LLM agent codebase, and Harness Evolver will evolve it — prompts, routing, tools, architecture — using multi-agent evolution with LangSmith as the evaluation backend.

Inspired by [Meta-Harness](https://yoonholee.com/meta-harness/) (Lee et al., 2026). The scaffolding around your LLM produces a [6x performance gap](https://arxiv.org/abs/2603.28052) on the same benchmark. This plugin automates the search for better scaffolding.

---

## Install

### Claude Code Plugin (recommended)

```
/plugin marketplace add raphaelchristi/harness-evolver-marketplace
/plugin install harness-evolver
```

Updates are automatic. Python dependencies (langsmith, langsmith-cli) are installed on first session start via hook.

### npx (first-time setup or non-Claude Code runtimes)

```bash
npx harness-evolver@latest
```

Interactive installer that configures LangSmith API key, creates Python venv, and installs all dependencies. Works with Claude Code, Cursor, Codex, and Windsurf.

> **Both install paths work together.** Use npx for initial setup (API key, venv), then the plugin marketplace handles updates automatically.

---

## Quick Start

```bash
cd my-llm-project
export LANGSMITH_API_KEY="lsv2_pt_..."
claude

/evolver:setup      # explores project, configures LangSmith
/evolver:health     # check dataset quality (auto-corrects issues)
/evolver:evolve     # runs the optimization loop
/evolver:status     # check progress (rich ASCII chart)
/evolver:deploy     # tag, push, finalize
```

---

## How It Works

<table>
<tr>
<td><b>LangSmith-Native</b></td>
<td>No custom eval scripts or task files. Uses LangSmith Datasets for test inputs, Experiments for results, and an agent-based LLM-as-judge for scoring via langsmith-cli. No external API keys needed. Everything is visible in the LangSmith UI.</td>
</tr>
<tr>
<td><b>Real Code Evolution</b></td>
<td>Proposers modify your actual agent code — not a wrapper. Each candidate works in an isolated git worktree. Winners are merged automatically. Config files (.evolver.json, .env) are auto-propagated to worktrees.</td>
</tr>
<tr>
<td><b>Self-Organizing Proposers</b></td>
<td>Each iteration generates dynamic investigation lenses from failure data, architecture analysis, production traces, and evolution memory. Proposers self-organize their approach — no fixed strategies. They can self-abstain when their contribution would be redundant. Inspired by <a href="https://arxiv.org/abs/2603.28990">Dochkina (2026)</a>.</td>
</tr>
<tr>
<td><b>Rubric-Based Evaluation</b></td>
<td>Dataset examples support <code>expected_behavior</code> rubrics — specific criteria the judge evaluates against ("should mention null safety and Android development"), not just generic correctness. Partial scoring (0.5) for partially-met rubrics. Inspired by <a href="https://github.com/NousResearch/hermes-agent-self-evolution">Hermes Agent Self-Evolution</a>.</td>
</tr>
<tr>
<td><b>Constraint Gates</b></td>
<td>Proposals must pass hard constraints before merge: code growth ≤30%, entry point syntax valid, test suite passes. Candidates that fail are rejected and the next-best is tried. Prevents code bloat and broken merges.</td>
</tr>
<tr>
<td><b>Weighted Evaluators + Pareto</b></td>
<td>Configure <code>evaluator_weights</code> to prioritize what matters (e.g., correctness 50%, latency 30%). When candidates offer genuinely different tradeoffs, the Pareto front is reported instead of forcing a single winner.</td>
</tr>
<tr>
<td><b>Agent-Based Evaluation</b></td>
<td>The evaluator agent reasons through justification BEFORE assigning scores (15-25% reliability improvement). Reads experiment outputs via langsmith-cli, judges correctness using rubrics when available, writes scores back. Judge feedback surfaced to proposers for targeted mutations. Position bias mitigation built-in.</td>
</tr>
<tr>
<td><b>Canary Preflight</b></td>
<td>Before running the full evaluation, 1 example is tested as a canary. If the agent produces no output, evaluation stops immediately — no API quota wasted on broken agents.</td>
</tr>
<tr>
<td><b>Secret Detection</b></td>
<td>Detects 15+ secret patterns (API keys, tokens, PEM keys) in production traces and dataset examples. Secrets are filtered from <code>seed_from_traces</code> and flagged as critical issues in dataset health checks.</td>
</tr>
<tr>
<td><b>Evolution Chart</b></td>
<td>Rich ASCII visualization with ANSI colors: sparkline trend, score progression table (per-evaluator breakdown), what-changed narrative, horizontal bar chart, and code growth tracking with warnings.</td>
</tr>
<tr>
<td><b>Production Traces</b></td>
<td>Auto-discovers existing LangSmith production projects. Uses real user inputs for test generation and real error patterns for targeted optimization. Can also mine Claude Code session history for eval data.</td>
</tr>
<tr>
<td><b>Active Critic</b></td>
<td>Auto-triggers when scores jump suspiciously fast. Detects evaluator gaming AND implements stricter evaluators to close loopholes.</td>
</tr>
<tr>
<td><b>ULTRAPLAN Architect</b></td>
<td>Auto-triggers on stagnation. Runs with Opus model for deep architectural analysis. Recommends topology changes (single-call to RAG, chain to ReAct, etc.).</td>
</tr>
<tr>
<td><b>Evolution Memory</b></td>
<td>Anchored iterative summarization — promoted insights (rec >= 3) are immutable anchors never re-summarized. New observations use literal text from proposals. Garbage collection removes stale observations. Inspired by Claude Code's autoDream and <a href="https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering">Context Engineering</a> research.</td>
</tr>
<tr>
<td><b>Dataset Health</b></td>
<td>Integrated preflight runs 5 checks in one pass: API key, config schema, LangSmith state, dataset health (size, difficulty, splits, secrets), and entry point canary. Reports all issues at once.</td>
</tr>
<tr>
<td><b>Smart Gating</b></td>
<td>Claude assesses gate conditions directly — score plateau, target reached, diminishing returns. Holdout enforcement ensures final comparison uses unseen data. Baseline is re-scored with LLM-judge before the loop to prevent inflated starting scores.</td>
</tr>
<tr>
<td><b>Background Mode</b></td>
<td>Run all iterations in background while you continue working. Get notified on completion or significant improvements.</td>
</tr>
</table>

---

## Commands

| Command | What it does |
|---|---|
| `/evolver:setup` | Explore project, configure LangSmith (dataset, evaluators), run baseline |
| `/evolver:health` | Check dataset quality (size, difficulty, coverage, splits, secrets), auto-correct |
| `/evolver:evolve` | Run the optimization loop (dynamic self-organizing proposers in worktrees) |
| `/evolver:status` | Show progress with rich ASCII evolution chart |
| `/evolver:deploy` | Tag, push, clean up temporary files |

---

## Agents

| Agent | Role | Color |
|---|---|---|
| **Proposer** | Self-organizing — investigates a data-driven lens, decides own approach, may abstain | Green |
| **Evaluator** | LLM-as-judge — rubric-aware scoring via langsmith-cli, textual feedback | Yellow |
| **Architect** | ULTRAPLAN mode — deep topology analysis with Opus model | Blue |
| **Critic** | Active — detects gaming AND implements stricter evaluators | Red |
| **Consolidator** | Cross-iteration memory consolidation (autoDream-inspired) | Cyan |
| **TestGen** | Generates test inputs with rubrics + adversarial injection mode | Cyan |

---

## Evolution Loop

```
/evolver:evolve
  |
  +- 0.5  Validate state (check .evolver.json vs LangSmith)
  +- 0.6  /evolver:health — dataset quality + secret scan + auto-correct
  +- 0.7  Baseline LLM-judge — re-score baseline with correctness if only has_output exists
  +- 1.   Read state (.evolver.json + LangSmith experiments)
  +- 1.5  Gather trace insights + judge feedback (cluster errors, tokens, latency)
  +- 1.8  Analyze per-task failures with judge comments (train split only)
  +- 1.8a Claude generates strategy.md + lenses.json from analysis data
  +- 1.9  Prepare shared proposer context (KV cache-optimized prefix)
  +- 2.   Spawn N self-organizing proposers in parallel (each in a git worktree)
  +- 3.   Copy .evolver.json + .env to worktrees, run canary, evaluate candidates
  +- 3.5  Spawn evaluator agent (rubric-aware LLM-as-judge via langsmith-cli)
  +- 4.   Compare experiments on held-out split -> winner + Pareto front
  +- 4.5  Constraint gate — reject candidates that break size/tests/entry-point
  +- 5.   Merge winning worktree into main branch
  +- 5.5  Regression tracking (auto-add guard examples to dataset)
  +- 6.   Report results + evolution chart
  +- 6.2  Consolidator agent updates evolution memory (runs in background)
  +- 6.5  Auto-trigger Active Critic (detect + fix evaluator gaming)
  +- 7.   Auto-trigger ULTRAPLAN Architect (opus model, deep analysis)
  +- 8.   Claude assesses gate conditions (plateau, target, diminishing returns)
```

---

## Architecture

```
Plugin hook (SessionStart)
  └→ Creates venv, installs langsmith + langsmith-cli, exports env vars

Skills (markdown)
  ├── /evolver:setup    → explores project, smart defaults, runs setup.py
  ├── /evolver:health   → dataset quality + secret scan + auto-correct
  ├── /evolver:evolve   → orchestrates the evolution loop
  ├── /evolver:status   → rich ASCII evolution chart + stagnation detection
  └── /evolver:deploy   → tags and pushes

Agents (markdown)
  ├── Proposer (xN)     → self-organizing, lens-driven, isolated git worktrees
  ├── Evaluator          → rubric-aware LLM-as-judge via langsmith-cli
  ├── Critic             → detects gaming + implements stricter evaluators
  ├── Architect          → ULTRAPLAN deep analysis (opus model)
  ├── Consolidator       → cross-iteration memory (autoDream-inspired)
  └── TestGen            → generates test inputs with rubrics + adversarial injection

Tools (Python)
  ├── setup.py              → creates datasets, configures evaluators + weights
  ├── run_eval.py           → runs target against dataset (canary preflight, {input_text})
  ├── read_results.py       → weighted scoring, Pareto front, judge feedback
  ├── trace_insights.py     → clusters errors from traces
  ├── seed_from_traces.py   → imports production traces (secret-filtered)
  ├── evolution_chart.py    → rich ASCII chart (stdlib-only)
  ├── constraint_check.py   → validates proposals (growth, syntax, tests) (stdlib-only)
  ├── secret_filter.py      → detects 15+ secret patterns (stdlib-only)
  ├── mine_sessions.py      → extracts eval data from Claude Code history (stdlib-only)
  ├── dataset_health.py     → dataset quality diagnostic + secret scanning
  ├── validate_state.py     → validates config vs LangSmith state
  ├── regression_tracker.py → tracks regressions, adds guard examples
  ├── add_evaluator.py      → programmatically adds evaluators
  └── adversarial_inject.py → detects memorization, injects adversarial tests
```

---

## Entry Point Placeholders

When configuring your agent's entry point during setup, use the placeholder that matches how your agent takes input:

| Placeholder | Behavior | Use when |
|---|---|---|
| `{input_text}` | Extracts plain text, shell-escapes it | Agent takes `--query "text"` or positional args |
| `{input}` | Passes path to a JSON file | Agent reads structured JSON from file |
| `{input_json}` | Passes raw JSON string inline | Agent parses JSON from command line |

**Example:**
```bash
# Agent that takes a query as text:
python agent.py --query {input_text}

# Agent that reads a JSON file:
python agent.py {input}
```

---

## Requirements

- **LangSmith account** + `LANGSMITH_API_KEY`
- **Python 3.10+**
- **Git** (for worktree-based isolation)
- **Claude Code** (or Cursor/Codex/Windsurf)

Dependencies (`langsmith`, `langsmith-cli`) are installed automatically by the plugin hook or the npx installer.

---

## Framework Support

LangSmith traces **any** AI framework. The evolver works with all of them:

| Framework | LangSmith Tracing |
|---|---|
| LangChain / LangGraph | Auto (env vars only) |
| OpenAI SDK | `wrap_openai()` (2 lines) |
| Anthropic SDK | `wrap_anthropic()` (2 lines) |
| CrewAI / AutoGen | OpenTelemetry (~10 lines) |
| Any Python code | `@traceable` decorator |

---

## References

- [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052) — Lee et al., 2026
- [Drop the Hierarchy and Roles: How Self-Organizing LLM Agents Outperform Designed Structures](https://arxiv.org/abs/2603.28990) — Dochkina, 2026
- [Hermes Agent Self-Evolution](https://github.com/NousResearch/hermes-agent-self-evolution) — NousResearch (rubric-based eval, constraint gates)
- [Agent Skills for Context Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering) — Koylan (justification-before-score, observation masking, anchored summarization)
- [Darwin Godel Machine](https://sakana.ai/dgm/) — Sakana AI
- [AlphaEvolve](https://deepmind.google/blog/alphaevolve/) — DeepMind
- [LangSmith Evaluation](https://docs.smith.langchain.com/evaluation) — LangChain
- [Harnessing Claude's Intelligence](https://claude.com/blog/harnessing-claudes-intelligence) — Martin, Anthropic, 2026
- [Traces Start the Agent Improvement Loop](https://www.langchain.com/conceptual-guides/traces-start-agent-improvement-loop) — LangChain

---

## License

MIT
