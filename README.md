# Harness Evolver

End-to-end optimization of LLM agent harnesses, inspired by [Meta-Harness](https://yoonholee.com/meta-harness/) (Lee et al., 2026).

## Install

```bash
npx harness-evolver@latest
```

## Quick Start

```bash
# 1. Copy the example into a working directory
cp -r ~/.harness-evolver/examples/classifier ./my-classifier
cd my-classifier

# 2. Initialize (runs baseline evaluation)
/harness-evolve-init --harness harness.py --eval eval.py --tasks tasks/

# 3. Evolve (runs the optimization loop)
/harness-evolve --iterations 5

# 4. Check progress
/harness-evolve-status
```

## How It Works

1. You provide a **harness** (any executable that processes tasks) and an **eval** (any executable that scores outputs).
2. The plugin runs an autonomous loop: a proposer agent reads all prior candidates' code, execution traces, and scores, then writes a better harness.
3. Each iteration stores full diagnostic traces — enabling the proposer to do counterfactual diagnosis across versions.

## Architecture

```
Plugin (installed globally)          Project (.harness-evolver/)
├── skills/  → slash commands        ├── baseline/     → original harness
├── agents/  → proposer subagent     ├── eval/         → eval script + tasks
├── tools/   → Python CLI tools      ├── harnesses/    → versioned candidates
└── bin/     → npx installer         │   └── v001/
                                     │       ├── harness.py
                                     │       ├── scores.json
                                     │       ├── proposal.md
                                     │       └── traces/
                                     ├── summary.json
                                     └── PROPOSER_HISTORY.md
```

## References

- [Meta-Harness paper (arxiv 2603.28052)](https://arxiv.org/abs/2603.28052)
- [Design spec](docs/specs/2026-03-31-harness-evolver-design.md)
