# Harness Evolver

End-to-end optimization of LLM agent harnesses, inspired by [Meta-Harness](https://yoonholee.com/meta-harness/) (Lee et al., 2026).

**The harness is the 80% factor.** Changing just the scaffolding around a fixed LLM can produce a [6x performance gap](https://arxiv.org/abs/2603.28052) on the same benchmark. Harness Evolver automates the search for better harnesses using an autonomous propose-evaluate-iterate loop with full execution traces as feedback.

## Why

Manual harness engineering is slow and doesn't scale. Existing optimizers work in prompt-space (OPRO, TextGrad, GEPA) or use compressed summaries. Meta-Harness showed that **code-space search with full diagnostic context** (10M+ tokens of traces) outperforms all of them by 10+ points.

Harness Evolver brings that approach to any domain as a Claude Code plugin.

## Install

```bash
# Via npx (recommended)
npx harness-evolver@latest

# Or as a Claude Code plugin
/plugin install harness-evolver
```

## Quick Start

```bash
# 1. Copy the example into a working directory
cp -r ~/.harness-evolver/examples/classifier ./my-classifier
cd my-classifier

# 2. Initialize (validates harness, evaluates baseline)
/harness-evolve-init --harness harness.py --eval eval.py --tasks tasks/

# 3. Run the evolution loop
/harness-evolve --iterations 5

# 4. Check progress anytime
/harness-evolve-status
```

The classifier example runs in mock mode (no API key needed) and demonstrates the full loop in under 2 minutes.

## How It Works

```
                    ┌─────────────────────────────┐
                    │     /harness-evolve          │
                    │     (orchestrator skill)     │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        ┌──────────┐   ┌────────────┐   ┌──────────┐
        │ PROPOSE  │   │  EVALUATE  │   │  UPDATE   │
        │ proposer │   │ evaluate.py│   │ state.py  │
        │ agent    │   │ + eval.py  │   │           │
        └──────────┘   └────────────┘   └──────────┘
              │                │                │
              ▼                ▼                ▼
        harnesses/       traces/         summary.json
        v{N}/            per-task        STATE.md
        harness.py       stdout/stderr   PROPOSER_HISTORY.md
        proposal.md      timing.json
        scores.json
```

1. **Propose** — A proposer agent (Claude Code subagent) reads all prior candidates' code, execution traces, and scores. It diagnoses failure modes via counterfactual analysis and writes a new harness.
2. **Evaluate** — The harness runs against every task. Traces are captured per-task (input, output, stdout, stderr, timing). The user's eval script scores the results.
3. **Update** — State files are updated with the new score, parent lineage, and regression detection.
4. **Repeat** — The loop continues until N iterations, stagnation (3 rounds without >1% improvement), or a target score is reached.

## The Harness Contract

A harness is **any executable** that accepts:

```bash
python3 harness.py --input task.json --output result.json [--traces-dir DIR] [--config config.json]
```

- `--input`: JSON with `{id, input, metadata}` (never sees expected answers)
- `--output`: JSON with `{id, output}`
- `--traces-dir`: optional directory for the harness to write rich traces
- `--config`: optional JSON with evolvable parameters (model, temperature, etc.)

The eval script is also any executable:

```bash
python3 eval.py --results-dir results/ --tasks-dir tasks/ --scores scores.json
```

This means Harness Evolver works with **any language, any framework, any domain**.

## Project Structure

```
.harness-evolver/                     # Created in your project by /harness-evolve-init
├── config.json                       # Project config (harness cmd, eval cmd, evolution params)
├── summary.json                      # Source of truth (versions, scores, parents)
├── STATE.md                          # Human-readable status (generated)
├── PROPOSER_HISTORY.md               # Log of all proposals and outcomes
├── baseline/                         # Original harness (read-only reference)
│   ├── harness.py
│   └── config.json
├── eval/
│   ├── eval.py                       # Scoring script
│   └── tasks/                        # Test cases (JSON files)
└── harnesses/
    └── v001/
        ├── harness.py                # Candidate code
        ├── config.json               # Evolvable parameters
        ├── proposal.md               # Proposer's reasoning
        ├── scores.json               # Evaluation results
        └── traces/                   # Full execution traces
            ├── stdout.log
            ├── stderr.log
            ├── timing.json
            └── task_001/
                ├── input.json        # What the harness received
                └── output.json       # What the harness returned
```

## Plugin Architecture

Three-layer design inspired by [GSD](https://github.com/gsd-build/get-shit-done):

```
Layer 1: Skills + Agents (markdown)     → AI orchestration
Layer 2: Tools (Python stdlib-only)     → Deterministic operations
Layer 3: Installer (Node.js)            → Distribution via npx
```

| Component | Files | Purpose |
|---|---|---|
| **Skills** | `skills/harness-evolve-init/`, `skills/harness-evolve/`, `skills/harness-evolve-status/` | Slash commands that orchestrate the loop |
| **Agent** | `agents/harness-evolver-proposer.md` | The proposer — 4-phase workflow (orient, diagnose, propose, document) with 6 rules |
| **Tools** | `tools/evaluate.py`, `tools/state.py`, `tools/init.py`, `tools/detect_stack.py`, `tools/trace_logger.py` | CLI tools called via subprocess — zero LLM tokens spent on deterministic work |
| **Installer** | `bin/install.js`, `package.json` | Copies skills/agents/tools to the right locations |
| **Example** | `examples/classifier/` | 10-task medical classifier with mock mode |

## Integrations

### LangSmith (optional)

If `LANGSMITH_API_KEY` is set, the plugin automatically:
- Enables `LANGCHAIN_TRACING_V2` for auto-tracing of LangChain/LangGraph harnesses
- Detects [langsmith-cli](https://github.com/gigaverse-app/langsmith-cli) for the proposer to query traces directly

```bash
# Setup
export LANGSMITH_API_KEY=lsv2_...
uv tool install langsmith-cli && langsmith-cli auth login

# The proposer can then do:
langsmith-cli --json runs list --project harness-evolver-v003 --failed --fields id,name,error
langsmith-cli --json runs stats --project harness-evolver-v003
```

No custom API client — the proposer uses `langsmith-cli` like it uses `grep` and `diff`.

### Context7 (optional)

The plugin detects the harness's technology stack via AST analysis (17 libraries supported) and instructs the proposer to consult current documentation before proposing API changes.

```bash
# Setup
claude mcp add context7 -- npx -y @upstash/context7-mcp@latest

# The proposer automatically:
# 1. Reads config.json → stack.detected (e.g., LangChain, ChromaDB)
# 2. Queries Context7 for current docs before writing code
# 3. Annotates proposal.md with "API verified via Context7"
```

Without Context7, the proposer uses model knowledge and annotates "API not verified against current docs."

### LangChain Docs MCP (optional)

```bash
claude mcp add docs-langchain --transport http https://docs.langchain.com/mcp
```

Complements Context7 with LangChain/LangGraph/LangSmith-specific documentation search.

## The Proposer

The proposer agent is the core of the system. It follows a 4-phase workflow derived from the Meta-Harness paper:

| Phase | Context % | What it does |
|---|---|---|
| **Orient** | ~6% | Read `summary.json` and `PROPOSER_HISTORY.md`. Decide which 2-3 versions to investigate. |
| **Diagnose** | ~80% | Deep trace analysis on selected versions. grep for errors, diff between good/bad versions, counterfactual diagnosis. |
| **Propose** | ~10% | Write new `harness.py` + `config.json`. Prefer additive changes after regressions. |
| **Document** | ~4% | Write `proposal.md` with evidence. Append to `PROPOSER_HISTORY.md`. |

**6 rules:**
1. Every change motivated by evidence (cite task ID, trace line, or score delta)
2. After regression, prefer additive changes
3. Don't repeat past mistakes (read PROPOSER_HISTORY.md)
4. One hypothesis at a time when possible
5. Maintain the CLI interface
6. Prefer readable harnesses over defensive ones

## Supported Libraries (Stack Detection)

The AST-based stack detector recognizes 17 libraries:

| Category | Libraries |
|---|---|
| **AI Frameworks** | LangChain, LangGraph, LlamaIndex, OpenAI, Anthropic, DSPy, CrewAI, AutoGen |
| **Vector Stores** | ChromaDB, Pinecone, Qdrant, Weaviate |
| **Web** | FastAPI, Flask, Pydantic |
| **Data** | Pandas, NumPy |

## Development

```bash
# Run all tests (41 tests, stdlib-only, no pip install needed)
python3 -m unittest discover -s tests -v

# Test the example manually
cd examples/classifier
python3 harness.py --input tasks/task_001.json --output /tmp/result.json --config config.json
cat /tmp/result.json

# Run the installer locally
node bin/install.js
```

## Comparison with Related Work

| | Meta-Harness (paper) | A-Evolve | ECC /evolve | **Harness Evolver** |
|---|---|---|---|---|
| **Format** | Paper artifact | Framework (Docker) | Plugin (passive) | **Plugin (active)** |
| **Search space** | Code-space | Code-space | Prompt-space | **Code-space** |
| **Context/iter** | 10M tokens | Variable | N/A | **Full filesystem** |
| **Domain** | TerminalBench-2 | Coding benchmarks | Dev workflow | **Any domain** |
| **Install** | Manual Python | Docker CLI | `/plugin install` | **`npx` or `/plugin install`** |
| **LangSmith** | No | No | No | **Yes (langsmith-cli)** |
| **Context7** | No | No | No | **Yes (MCP)** |

## References

- [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052) — Lee et al., 2026
- [GSD (Get Shit Done)](https://github.com/gsd-build/get-shit-done) — CLI architecture inspiration
- [LangSmith CLI](https://github.com/gigaverse-app/langsmith-cli) — Trace analysis for the proposer
- [Context7](https://github.com/upstash/context7) — Documentation lookup via MCP
- [Design Spec](docs/specs/2026-03-31-harness-evolver-design.md)
- [LangSmith Integration Spec](docs/specs/2026-03-31-langsmith-integration.md)
- [Context7 Integration Spec](docs/specs/2026-03-31-context7-integration.md)

## License

MIT
