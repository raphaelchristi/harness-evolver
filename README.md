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

Tested on a RAG agent (Agno framework, Gemini 3.1 Flash Lite, light mode):

```mermaid
xychart-beta
    title "agno-deepknowledge: 0.575 → 1.000 (+74%)"
    x-axis ["base", "v001", "v002", "v003", "v004", "v005", "v006", "v007"]
    y-axis "Correctness" 0 --> 1
    line [0.575, 0.575, 0.950, 0.950, 0.950, 0.950, 0.950, 1.0]
    bar [0.575, 0.333, 0.950, 0.720, 0.875, 0.680, 0.880, 1.0]
```

| Iter | Score | Merged? | What the proposer did |
|---|---|---|---|
| baseline | 0.575 | — | Original agent — hallucinations, broken tool calls, no retry logic |
| v001 | 0.333 | Yes | Anti-hallucination prompt (100% correct when API responded, but 60% hit rate limits) |
| v002 | 0.950 | Yes | **Breakthrough**: inlined 17-line KB into prompt, eliminated vector search entirely. 5.7x faster, zero rate limits |
| v003 | 0.720 | **No** | Attempted hybrid retrieval — regressed, rejected by constraint gate |
| v004 | 0.875 | **No** | Response completeness fix — improved one case but regressed others |
| v005 | 0.680 | **No** | Reduced tool calls — broke edge cases, rejected |
| v006 | 0.880 | Yes | Evolution memory insight: combined v001's anti-hallucination with one-shot example from archive |
| v007 | 1.000 | Yes | One-shot example injection + rubric-aligned responses — perfect on held-out |

The line shows best score (only goes up — regressions aren't merged). The bars show each candidate's raw score. 4 merged, 3 rejected by gate checks. Not every iteration improves — that's the point.

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

## Companion: LangSmith Tracing

For full observability into what each proposer does during evolution (every file read, edit, and commit), install the [LangSmith tracing plugin](https://github.com/langchain-ai/langsmith-claude-code-plugins):

```
/plugin marketplace add langchain-ai/langsmith-claude-code-plugins
/plugin install langsmith-tracing@langsmith-claude-code-plugins
```

With both plugins installed, the evolution loop traces to LangSmith as a hierarchy: iteration → proposers → tool calls.

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
