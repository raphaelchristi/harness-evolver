# Harness Evolver

End-to-end optimization of LLM agent harnesses, inspired by [Meta-Harness](https://yoonholee.com/meta-harness/) (Lee et al., 2026).

## Overview

Harness Evolver automatically discovers better harnesses — the scaffolding code that determines what information to store, retrieve, and present to an LLM at each step. Instead of manual prompt engineering, it uses a search loop where a coding agent proposes, evaluates, and iterates on harness designs using full execution traces as feedback.

## Architecture

```
harness-evolver/
├── evolver/
│   ├── proposer.py      # Coding agent that proposes new harnesses
│   ├── evaluator.py     # Evaluates candidate harnesses on task sets
│   ├── loop.py          # Main search loop orchestration
│   └── filesystem.py    # Filesystem-based feedback store
├── harnesses/           # Discovered harness candidates
├── traces/              # Execution traces and evaluation logs
├── tasks/               # Task definitions and datasets
└── config.yaml          # Search configuration
```

## Key Ideas

- **Filesystem as feedback channel**: All prior candidates, scores, and full execution traces are stored in a growing filesystem — providing orders of magnitude more diagnostic context than score-only or summary-based optimizers.
- **Code-space search**: Harnesses are full Python programs, not prompt templates. The proposer can modify algorithmic structure, retrieval logic, memory management, and prompt construction.
- **Coding agent as proposer**: A coding agent navigates the feedback filesystem using standard dev tools, enabling counterfactual diagnosis across execution traces.

## Getting Started

```bash
pip install -e .
```

## References

- [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052)
- [stanford-iris-lab/meta-harness-tbench2-artifact](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact)

## License

MIT
