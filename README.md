# Harness Evolver

End-to-end optimization of LLM agent harnesses, inspired by [Meta-Harness](https://yoonholee.com/meta-harness/) (Lee et al., 2026).

**The harness is the 80% factor.** Changing just the scaffolding around a fixed LLM can produce a [6x performance gap](https://arxiv.org/abs/2603.28052) on the same benchmark. Harness Evolver automates the search for better harnesses using an autonomous propose-evaluate-iterate loop with full execution traces as feedback.

## Install

```bash
npx harness-evolver@latest
```

Select your runtime (Claude Code, Cursor, Codex, Windsurf) and scope (global/local). Then **restart your AI coding agent** for the skills to appear.

## Prerequisites

### API Keys (set in your shell before launching Claude Code)

The harness you're evolving may call LLM APIs. Set the keys your harness needs:

```bash
# Required: at least one LLM provider
export ANTHROPIC_API_KEY="sk-ant-..."       # For Claude-based harnesses
export OPENAI_API_KEY="sk-..."              # For OpenAI-based harnesses
export GEMINI_API_KEY="AIza..."             # For Gemini-based harnesses
export OPENROUTER_API_KEY="sk-or-..."       # For OpenRouter (multi-model)

# Optional: enhanced tracing
export LANGSMITH_API_KEY="lsv2_pt_..."      # Auto-enables LangSmith tracing
```

The plugin auto-detects which keys are available during `/harness-evolver:init` and shows them. The proposer agent knows which APIs are available and uses them accordingly.

**No API key needed for the example** — the classifier example uses keyword matching (mock mode), no LLM calls.

### Optional: Enhanced Integrations

```bash
# LangSmith — rich trace analysis for the proposer
uv tool install langsmith-cli && langsmith-cli auth login

# Context7 — up-to-date library documentation for the proposer
claude mcp add context7 -- npx -y @upstash/context7-mcp@latest

# LangChain Docs — LangChain/LangGraph-specific documentation
claude mcp add docs-langchain --transport http https://docs.langchain.com/mcp
```

## Quick Start

### Try the Example (no API key needed)

```bash
# 1. Copy the example
cp -r ~/.harness-evolver/examples/classifier ./my-classifier
cd my-classifier

# 2. Open Claude Code
claude

# 3. Initialize — auto-detects harness.py, eval.py, tasks/
/harness-evolver:init

# 4. Run the evolution loop
/harness-evolver:evolve --iterations 3

# 5. Check progress
/harness-evolver:status
```

### Use with Your Own Project

```bash
cd my-llm-project
claude

# Init scans your project, identifies the entry point,
# and helps create harness wrapper + eval + tasks if missing
/harness-evolver:init

# Run optimization
/harness-evolver:evolve --iterations 10
```

The init skill adapts to your project — if you have `graph.py` instead of `harness.py`, it creates a thin wrapper. If you don't have an eval script, it helps you write one.

## Available Commands

| Command | What it does |
|---|---|
| `/harness-evolver:init` | Scan project, create harness/eval/tasks, run baseline |
| `/harness-evolver:evolve` | Run the autonomous optimization loop |
| `/harness-evolver:status` | Show progress (scores, iterations, stagnation) |
| `/harness-evolver:compare` | Diff two versions with per-task analysis |
| `/harness-evolver:diagnose` | Deep trace analysis of a specific version |
| `/harness-evolver:deploy` | Copy the best harness back to your project |

## How It Works

```
                    ┌─────────────────────────────┐
                    │   /harness-evolver:evolve    │
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

1. **Propose** — A proposer agent reads all prior candidates' code, execution traces, and scores. Diagnoses failure modes via counterfactual analysis and writes a new harness.
2. **Evaluate** — The harness runs against every task. Traces are captured per-task (input, output, stdout, stderr, timing). Your eval script scores the results.
3. **Update** — State files are updated with the new score, parent lineage, and regression detection.
4. **Repeat** — Until N iterations, stagnation (3 rounds without >1% improvement), or target score reached.

## The Harness Contract

A harness is **any executable** that accepts:

```bash
python3 harness.py --input task.json --output result.json [--traces-dir DIR] [--config config.json]
```

- `--input`: JSON with `{id, input, metadata}` (never sees expected answers)
- `--output`: JSON with `{id, output}`
- `--traces-dir`: optional directory for rich traces
- `--config`: optional JSON with evolvable parameters

The eval script is also any executable:

```bash
python3 eval.py --results-dir results/ --tasks-dir tasks/ --scores scores.json
```

Works with **any language, any framework, any domain**.

## Project Structure (after init)

```
.harness-evolver/                     # Created by /harness-evolver:init
├── config.json                       # Project config (harness cmd, eval, API keys detected)
├── summary.json                      # Source of truth (versions, scores, parents)
├── STATE.md                          # Human-readable status
├── PROPOSER_HISTORY.md               # Log of all proposals and outcomes
├── baseline/                         # Original harness (read-only)
│   └── harness.py
├── eval/
│   ├── eval.py                       # Your scoring script
│   └── tasks/                        # Test cases
└── harnesses/
    └── v001/
        ├── harness.py                # Evolved candidate
        ├── proposal.md               # Why this version was created
        ├── scores.json               # How it scored
        └── traces/                   # Full execution traces
            ├── stdout.log
            ├── stderr.log
            ├── timing.json
            └── task_001/
                ├── input.json
                └── output.json
```

## The Proposer

The core of the system. 4-phase workflow from the Meta-Harness paper:

| Phase | What it does |
|---|---|
| **Orient** | Read `summary.json` + `PROPOSER_HISTORY.md`. Pick 2-3 versions to investigate. |
| **Diagnose** | Deep trace analysis. grep for errors, diff versions, counterfactual diagnosis. |
| **Propose** | Write new harness. Prefer additive changes after regressions. |
| **Document** | Write `proposal.md` with evidence. Update history. |

**7 rules:** evidence-based changes, conservative after regression, don't repeat mistakes, one hypothesis at a time, maintain interface, prefer readability, use available API keys from environment.

## Integrations

### LangSmith (optional, recommended for LangChain/LangGraph harnesses)

```bash
export LANGSMITH_API_KEY=lsv2_...
uv tool install langsmith-cli && langsmith-cli auth login
```

When detected, the plugin:
- Sets `LANGCHAIN_TRACING_V2=true` automatically — all LLM calls are traced
- The proposer queries traces directly via `langsmith-cli`:

```bash
langsmith-cli --json runs list --project harness-evolver-v003 --failed --fields id,name,error
langsmith-cli --json runs stats --project harness-evolver-v003
```

### Context7 (optional, recommended for any library-heavy harness)

```bash
claude mcp add context7 -- npx -y @upstash/context7-mcp@latest
```

The plugin detects your stack via AST analysis (17 libraries: LangChain, LangGraph, OpenAI, Anthropic, ChromaDB, FastAPI, etc.) and instructs the proposer to consult current docs before proposing API changes.

## Development

```bash
# Run all tests (41 tests, stdlib-only)
python3 -m unittest discover -s tests -v

# Test example manually
python3 examples/classifier/harness.py --input examples/classifier/tasks/task_001.json --output /tmp/result.json --config examples/classifier/config.json

# Install locally for development
node bin/install.js
```

## Comparison

| | Meta-Harness | A-Evolve | ECC | **Harness Evolver** |
|---|---|---|---|---|
| **Format** | Paper artifact | Framework (Docker) | Plugin (passive) | **Plugin (active)** |
| **Search** | Code-space | Code-space | Prompt-space | **Code-space** |
| **Domain** | TerminalBench-2 | Coding benchmarks | Dev workflow | **Any domain** |
| **Install** | Manual Python | Docker CLI | `/plugin install` | **`npx`** |
| **LangSmith** | No | No | No | **Yes** |
| **Context7** | No | No | No | **Yes** |

## References

- [Meta-Harness paper (arxiv 2603.28052)](https://arxiv.org/abs/2603.28052) — Lee et al., 2026
- [Design Spec](docs/specs/2026-03-31-harness-evolver-design.md)
- [LangSmith Integration](docs/specs/2026-03-31-langsmith-integration.md)
- [Context7 Integration](docs/specs/2026-03-31-context7-integration.md)

## License

MIT
