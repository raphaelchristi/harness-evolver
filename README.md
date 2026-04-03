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

Point at any LLM agent codebase. Harness Evolver will autonomously improve it — prompts, routing, tools, architecture — using multi-agent evolution with LangSmith as the evaluation backend.

---

## Install

### Claude Code Plugin (recommended)

```
/plugin marketplace add raphaelchristi/harness-evolver-marketplace
/plugin install harness-evolver
```

### npx (first-time setup or non-Claude Code runtimes)

```bash
npx harness-evolver@latest
```

Works with Claude Code, Cursor, Codex, and Windsurf.

---

## Quick Start

```bash
cd my-llm-project
export LANGSMITH_API_KEY="lsv2_pt_..."
claude

/harness:setup      # explores project, configures LangSmith
/harness:health     # check dataset quality (auto-corrects issues)
/harness:evolve     # runs the optimization loop
/harness:status     # check progress (rich ASCII chart)
/harness:deploy     # tag, push, finalize
```

---

## What It Looks Like

```mermaid
xychart-beta
    title "Best Score Over Evolution Iterations"
    x-axis ["base", "v001", "v002", "v003", "v004", "v005", "v006", "v007", "v008", "v009"]
    y-axis "Correctness" 0 --> 1
    line [0.31, 0.48, 0.52, 0.52, 0.67, 0.71, 0.71, 0.71, 0.79, 0.84]
```

| Iter | Score | Merged? | What happened |
|---|---|---|---|
| baseline | 0.31 | — | Broken tool calls, hallucinations, no error handling |
| v001 | 0.48 | Yes | Fixed input parsing, added retry logic (+0.17) |
| v002 | 0.52 | Yes | Prompt rewrite to reduce hallucinations (+0.04) |
| v003 | 0.49 | **No** | Attempted retrieval change — regressed, rejected by gate |
| v004 | 0.67 | Yes | Architect triggered: chain → ReAct restructure (+0.15) |
| v005 | 0.71 | Yes | Output validation + citation grounding (+0.04) |
| v006 | 0.68 | **No** | Tried fewer tool calls — broke edge cases, rejected |
| v007 | 0.70 | **No** | Prompt tweak — within noise margin, not merged |
| v008 | 0.79 | Yes | Evolution memory insight: combined v003's retrieval with v005's validation (+0.08) |
| v009 | 0.84 | Yes | Fine-tuned rubric alignment from judge feedback (+0.05) |

Real pattern: initial jump → plateau → architectural breakthrough → small gains → stagnation → memory-driven recovery. Regressions rejected automatically. Not every iteration improves — that's the point of gate checks.

---

## How It Works

| | |
|---|---|
| **LangSmith-Native** | No custom scripts. Uses LangSmith Datasets, Experiments, and LLM-as-judge. Everything visible in the LangSmith UI. |
| **Real Code Evolution** | Proposers modify actual code in isolated git worktrees. Winners merge automatically. |
| **Self-Organizing Proposers** | Two-wave spawning, dynamic lenses from failure data, archive branching from losing candidates. Self-abstention when redundant. |
| **Rubric-Based Evaluation** | LLM-as-judge with justification-before-score, rubrics, few-shot calibration, pairwise comparison. |
| **Smart Gating** | Constraint gates, efficiency gate (cost/latency pre-merge), regression guards, Pareto selection, holdout enforcement, rate-limit early abort, stagnation detection. |

[Full feature list](docs/FEATURES.md)

---

## Evolution Loop

```
/harness:evolve
  |
  +- 1. Preflight  (validate state + dataset health + baseline scoring)
  +- 2. Analyze    (trace insights + failure clusters + strategy synthesis)
  +- 3. Propose    (spawn N proposers in git worktrees, two-wave)
  +- 4. Evaluate   (canary → run target → auto-spawn LLM-as-judge → rate-limit abort)
  +- 5. Select     (held-out comparison → Pareto front → efficiency gate → constraint gate → merge)
  +- 6. Learn      (archive candidates + regression guards + evolution memory)
  +- 7. Gate       (plateau → target check → critic/architect → continue or stop)
```

[Detailed loop with all sub-steps](docs/ARCHITECTURE.md)

---

## Agents

| Agent | Role |
|---|---|
| **Proposer** | Self-organizing — investigates a data-driven lens, decides own approach, may abstain |
| **Evaluator** | LLM-as-judge — rubric-aware scoring via langsmith-cli, few-shot calibration |
| **Architect** | ULTRAPLAN mode — deep topology analysis with Opus model |
| **Critic** | Active — detects evaluator gaming, implements stricter evaluators |
| **Consolidator** | Cross-iteration memory — anchored summarization, garbage collection |
| **TestGen** | Generates test inputs with rubrics + adversarial injection |

---

## Requirements

- **LangSmith account** + `LANGSMITH_API_KEY`
- **Python 3.10+** · **Git** · **Claude Code** (or Cursor/Codex/Windsurf)

Dependencies installed automatically by the plugin hook or npx installer.

LangSmith traces any AI framework: LangChain/LangGraph (auto), OpenAI/Anthropic SDK (`wrap_*`, 2 lines), CrewAI/AutoGen (OpenTelemetry), any Python (`@traceable`).

---

## References

- [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052) — Lee et al., 2026
- [Self-Organizing LLM Agents Outperform Designed Structures](https://arxiv.org/abs/2603.28990) — Dochkina, 2026
- [Hermes Agent Self-Evolution](https://github.com/NousResearch/hermes-agent-self-evolution) — NousResearch
- [Agent Skills for Context Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering) — Koylan
- [A-Evolve: Automated Agent Evolution](https://github.com/A-EVO-Lab/a-evolve) — Amazon (5-stage evolution loop, git-tagged mutations)
- [Meta Context Engineering via Agentic Skill Evolution](https://arxiv.org/abs/2601.21557) — Ye et al., Peking University, 2026
- [EvoAgentX: Evolving Agentic Workflows](https://github.com/EvoAgentX/EvoAgentX) — Wang et al., 2026
- [Darwin Godel Machine](https://sakana.ai/dgm/) — Sakana AI
- [AlphaEvolve](https://deepmind.google/blog/alphaevolve/) — DeepMind
- [LangSmith Evaluation](https://docs.smith.langchain.com/evaluation) — LangChain
- [Harnessing Claude's Intelligence](https://claude.com/blog/harnessing-claudes-intelligence) — Martin, Anthropic, 2026
- [Traces Start the Agent Improvement Loop](https://www.langchain.com/conceptual-guides/traces-start-agent-improvement-loop) — LangChain

---

## License

MIT
