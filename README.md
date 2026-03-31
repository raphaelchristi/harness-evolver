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

**Autonomous harness optimization for LLM agents.** Point at any codebase, and Harness Evolver will evolve the scaffolding around your LLM — prompts, retrieval, routing, output parsing — using a multi-agent loop inspired by [Meta-Harness](https://yoonholee.com/meta-harness/) (Lee et al., 2026).

The harness is the 80% factor. Changing just the scaffolding can produce a [6x performance gap](https://arxiv.org/abs/2603.28052) on the same benchmark. This plugin automates that search.

---

## Install

```bash
npx harness-evolver@latest
```

> Works with Claude Code, Cursor, Codex, and Windsurf. Restart your agent after install.

---

## Quick Start

```bash
cd my-llm-project
claude

/harness-evolver:init        # scans code, creates eval + tasks if missing
/harness-evolver:evolve      # runs the optimization loop
/harness-evolver:status      # check progress anytime
```

**Zero-config mode:** If your project has no eval script or test cases, the plugin generates them automatically — test cases from code analysis, scoring via LLM-as-judge.

---

## How It Works

<table>
<tr>
<td><b>5 Proposers</b></td>
<td>Each iteration spawns 5 parallel agents with different strategies: exploit (targeted fix), explore (bold rewrite), crossover (combine two parents), prompt specialist, retrieval specialist. Best candidate wins.</td>
</tr>
<tr>
<td><b>Full Traces</b></td>
<td>Every harness run captures stdout, stderr, timing, and per-task I/O. LangSmith auto-tracing for LangChain/LangGraph agents. Proposers read actual LLM prompts and responses.</td>
</tr>
<tr>
<td><b>Critic</b></td>
<td>Auto-triggers when scores jump suspiciously fast. Analyzes eval quality, detects gaming, proposes stricter evaluation. Prevents false convergence.</td>
</tr>
<tr>
<td><b>Architect</b></td>
<td>Auto-triggers on stagnation or regression. Recommends topology changes (single-call → RAG, chain → ReAct, etc.) with concrete migration steps.</td>
</tr>
<tr>
<td><b>Judge</b></td>
<td>LLM-as-judge scoring when no eval exists. Multi-dimensional: accuracy, completeness, relevance, hallucination detection. No expected answers needed.</td>
</tr>
</table>

---

## Commands

| Command | What it does |
|---|---|
| `/harness-evolver:init` | Scan project, create harness/eval/tasks, run baseline |
| `/harness-evolver:evolve` | Run the autonomous optimization loop (5 parallel proposers) |
| `/harness-evolver:status` | Show progress, scores, stagnation detection |
| `/harness-evolver:compare` | Diff two versions with per-task analysis |
| `/harness-evolver:diagnose` | Deep trace analysis of a specific version |
| `/harness-evolver:deploy` | Promote the best harness back to your project |
| `/harness-evolver:architect` | Analyze and recommend optimal agent topology |
| `/harness-evolver:critic` | Evaluate eval quality and detect gaming |

---

## Agents

| Agent | Role | Color |
|---|---|---|
| **Proposer** | Evolves the harness code based on trace analysis | Green |
| **Architect** | Recommends multi-agent topology (ReAct, RAG, hierarchical, etc.) | Blue |
| **Critic** | Evaluates eval quality, detects gaming, proposes stricter scoring | Red |
| **Judge** | LLM-as-judge scoring — works without expected answers | Yellow |
| **TestGen** | Generates synthetic test cases from code analysis | Cyan |

---

## Integrations

<table>
<tr>
<td><b>LangSmith</b></td>
<td>Auto-traces LangChain/LangGraph agents. Proposers read actual LLM prompts/responses via <code>langsmith-cli</code>. Processed into readable format per iteration.</td>
</tr>
<tr>
<td><b>Context7</b></td>
<td>Proposers consult up-to-date library documentation before writing code. Detects 17 libraries via AST analysis.</td>
</tr>
<tr>
<td><b>LangChain Docs</b></td>
<td>LangChain/LangGraph-specific documentation search via MCP.</td>
</tr>
</table>

```bash
# Optional — install during npx setup or manually:
uv tool install langsmith-cli && langsmith-cli auth login
claude mcp add context7 -- npx -y @upstash/context7-mcp@latest
claude mcp add docs-langchain --transport http https://docs.langchain.com/mcp
```

---

## The Harness Contract

A harness is **any executable**:

```bash
python3 harness.py --input task.json --output result.json [--traces-dir DIR] [--config config.json]
```

Works with any language, any framework, any domain. If your project doesn't have a harness, the init skill creates a wrapper around your entry point.

---

## Evolution Loop

```
/harness-evolver:evolve
  │
  ├─ 1. Gather LangSmith traces (processed into readable format)
  ├─ 2. Spawn 5 proposers in parallel (exploit/explore/crossover/prompt/retrieval)
  ├─ 3. Validate all candidates
  ├─ 4. Evaluate all candidates
  ├─ 4.5 Judge (if using LLM-as-judge eval)
  ├─ 5. Select winner (highest combined_score)
  ├─ 6. Report results
  ├─ 6.5 Auto-trigger Critic (if score jumped >0.3 or reached 1.0 too fast)
  ├─ 7. Auto-trigger Architect (if regression or stagnation)
  └─ 8. Check stop conditions (target reached, N iterations, stagnation post-architect)
```

---

## API Keys

Set in your shell before launching Claude Code:

```bash
export GEMINI_API_KEY="AIza..."             # Gemini-based harnesses
export ANTHROPIC_API_KEY="sk-ant-..."       # Claude-based harnesses
export OPENAI_API_KEY="sk-..."              # OpenAI-based harnesses
export OPENROUTER_API_KEY="sk-or-..."       # Multi-model via OpenRouter
export LANGSMITH_API_KEY="lsv2_pt_..."      # Auto-enables LangSmith tracing
```

The plugin auto-detects available keys. No key needed for the included example.

---

## Comparison

| | Meta-Harness | A-Evolve | ECC | **Harness Evolver** |
|---|---|---|---|---|
| **Format** | Paper artifact | Framework (Docker) | Plugin (passive) | **Plugin (active)** |
| **Search** | Code-space | Code-space | Prompt-space | **Code-space** |
| **Candidates/iter** | 1 | 1 | N/A | **5 parallel** |
| **Auto-critique** | No | No | No | **Yes (critic + judge)** |
| **Architecture** | Fixed | Fixed | N/A | **Auto-recommended** |
| **LangSmith** | No | No | No | **Yes** |
| **Context7** | No | No | No | **Yes** |
| **Zero-config** | No | No | No | **Yes** |

---

## References

- [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052) — Lee et al., 2026
- [Darwin Godel Machine](https://sakana.ai/dgm/) — Sakana AI (parallel evolution architecture)
- [AlphaEvolve](https://deepmind.google/blog/alphaevolve/) — DeepMind (population-based code evolution)
- [Agent Skills Specification](https://agentskills.io) — Open standard for AI agent skills

---

## License

MIT
