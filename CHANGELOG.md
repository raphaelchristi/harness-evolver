# Changelog

## [4.0.0] - 2026-04-02

Twelve features inspired by Claude Code's architecture, making the evolution loop smarter, cheaper, and more autonomous.

### Added

- **State Validation** (`tools/validate_state.py`) — skeptical memory pattern that validates `.evolver.json` against LangSmith reality before each iteration. Checks dataset existence, experiment accessibility, git state, and history consistency.
- **Three-Gate Iteration Triggers** (`tools/iteration_gate.py`) — score plateau detection, cost budget tracking, and statistical convergence analysis replace blind N-iteration loops. Auto-suggests architect on stagnation.
- **Regression Tracking** (`tools/regression_tracker.py`) — compares per-example scores between iterations, detects failing-to-passing transitions, and auto-injects regression guard examples into the LangSmith dataset.
- **autoConsolidate** (`tools/consolidate.py`, `agents/evolver-consolidator.md`) — cross-iteration memory consolidation inspired by Claude Code's autoDream. Four phases: orient, gather, consolidate, prune. Promotes insights to proposer briefings after 2+ recurrences.
- **KV Cache-Optimized Proposer Spawning** — restructured proposer prompts with a shared byte-identical prefix (objective + files + context) and strategy-only suffix for ~80% token savings across 5 parallel proposers.
- **Per-Proposer Tool Restrictions** — exploit/crossover/failure-targeted proposers get Edit-only (no Write); explore gets full access. Prevents conservative strategies from creating unnecessary files.
- **Proposer Turn Budget** — 16-turn cap with phased allocation (orient/diagnose/implement/test/commit) and stuck proposer detection. Prevents runaway agents consuming tokens in loops.
- **Coordinator Synthesis Phase** (`tools/synthesize_strategy.py`) — generates a targeted `strategy.md` document from trace insights, results, and evolution memory. Proposers receive synthesized specs instead of raw data dumps.
- **Active Critic** (`tools/add_evaluator.py`) — upgraded from passive reporter to active fixer. Detects evaluator gaming AND implements stricter code-based evaluators (`answer_not_question`, `no_hallucination_markers`, `min_length`, `no_repetition`).
- **ULTRAPLAN Architect** — runs with `model: opus` for deep architectural analysis. Full codebase scan, AST-based topology classification, performance pattern analysis from evolution memory, and detailed migration plans.
- **Self-Scheduling Evolution** — background and cron-based execution modes. Schedule nightly optimization runs with `CronCreate` and check progress via `/evolver:status`.
- **Anti-Distillation** (`tools/adversarial_inject.py`) — detects potential memorization by comparing agent outputs to reference outputs, then injects adversarial rephrased examples to test generalization.

### Changed

- `agents/evolver-critic.md` — upgraded to Active Critic v3.1 with three phases (Detect, Act, Verify)
- `agents/evolver-architect.md` — upgraded to ULTRAPLAN Mode v3.1 with `model: opus` in frontmatter
- `agents/evolver-proposer.md` — added Turn Budget section and Tool Restrictions documentation
- `agents/evolver-testgen.md` — added Phase 3.5 for adversarial injection mode
- `skills/evolve/SKILL.md` — expanded with validation, gate checks, synthesis, consolidation, scheduling, and restructured proposer spawning (+378 lines)

## [3.3.1] - 2026-03-31

### Fixed

- 8 production bugs from first real-world evolve run

## [3.3.0] - 2026-03-31

### Added

- Redesigned installer UI with gradient banner and clack-style output
- Plugin marketplace install support
- Architecture section in README
