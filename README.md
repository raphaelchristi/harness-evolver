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

```bash
npx harness-evolver@latest
```

> Works with Claude Code, Cursor, Codex, and Windsurf. Requires LangSmith account + API key.

---

## Quick Start

```bash
cd my-llm-project
export LANGSMITH_API_KEY="lsv2_pt_..."
claude

/evolver:setup      # explores project, configures LangSmith
/evolver:evolve     # runs the optimization loop
/evolver:status     # check progress
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
<td>Proposers modify your actual agent code — not a wrapper. Each candidate works in an isolated git worktree. Winners are merged automatically.</td>
</tr>
<tr>
<td><b>5 Adaptive Proposers</b></td>
<td>Each iteration spawns 5 parallel agents: exploit, explore, crossover, and 2 failure-targeted. Strategies adapt based on per-task analysis. Quality-diversity selection preserves per-task champions.</td>
</tr>
<tr>
<td><b>Production Traces</b></td>
<td>Auto-discovers existing LangSmith production projects. Uses real user inputs for test generation and real error patterns for targeted optimization.</td>
</tr>
<tr>
<td><b>Critic</b></td>
<td>Auto-triggers when scores jump suspiciously fast. Checks if evaluators are being gamed.</td>
</tr>
<tr>
<td><b>Architect</b></td>
<td>Auto-triggers on stagnation. Recommends topology changes (single-call to RAG, chain to ReAct, etc.).</td>
</tr>
</table>

---

## Commands

| Command | What it does |
|---|---|
| `/evolver:setup` | Explore project, configure LangSmith (dataset, evaluators), run baseline |
| `/evolver:evolve` | Run the optimization loop (5 parallel proposers in worktrees) |
| `/evolver:status` | Show progress, scores, history |
| `/evolver:deploy` | Tag, push, clean up temporary files |

---

## Agents

| Agent | Role | Color |
|---|---|---|
| **Proposer** | Modifies agent code in isolated worktrees based on trace analysis | Green |
| **Architect** | Recommends multi-agent topology changes | Blue |
| **Critic** | Validates evaluator quality, detects gaming | Red |
| **TestGen** | Generates test inputs for LangSmith datasets | Cyan |
| **Evaluator** | LLM-as-judge — reads outputs via langsmith-cli, scores correctness | Yellow |

---

## Evolution Loop

```
/evolver:evolve
  |
  +- 1.  Read state (.evolver.json + LangSmith experiments)
  +- 1.5 Gather trace insights (cluster errors, tokens, latency)
  +- 1.8 Analyze per-task failures (adaptive briefings)
  +- 2.  Spawn 5 proposers in parallel (each in a git worktree)
  +- 3.  Run target for each candidate (client.evaluate() -> code-based evaluators)
  +- 3.5 Spawn evaluator agent (reads outputs via langsmith-cli, judges, writes scores)
  +- 4.  Compare experiments -> select winner + per-task champion
  +- 5.  Merge winning worktree into main branch
  +- 5.5 Test suite growth (add regression examples to dataset)
  +- 6.  Report results
  +- 6.5 Auto-trigger Critic (if score jumped >0.3)
  +- 7.  Auto-trigger Architect (if stagnation or regression)
  +- 8.  Check stop conditions
```

---

## Requirements

- **LangSmith account** + `LANGSMITH_API_KEY`
- **Python 3.10+** with `langsmith` package
- **langsmith-cli** (`uv tool install langsmith-cli`) — required for evaluator agent
- **Git** (for worktree-based isolation)
- **Claude Code** (or Cursor/Codex/Windsurf)

```bash
export LANGSMITH_API_KEY="lsv2_pt_..."
pip install langsmith
uv tool install langsmith-cli
```

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
- [Darwin Godel Machine](https://sakana.ai/dgm/) — Sakana AI
- [AlphaEvolve](https://deepmind.google/blog/alphaevolve/) — DeepMind
- [LangSmith Evaluation](https://docs.smith.langchain.com/evaluation) — LangChain
- [Traces Start the Agent Improvement Loop](https://www.langchain.com/conceptual-guides/traces-start-agent-improvement-loop) — LangChain

---

## License

MIT
