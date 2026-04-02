# Changelog

All notable changes to Harness Evolver are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioned per [Semantic Versioning](https://semver.org/).

---

## [4.2.0] - 2026-04-02

### Added

- **`tools/dataset_health.py`** — new diagnostic tool that checks dataset quality before evolution: size adequacy, difficulty distribution (easy/medium/hard), dead example detection, production coverage analysis, and split configuration. Outputs `health_report.json` with actionable corrections
- **LangSmith native splits** — train (70%) / held_out (30%) splits assigned automatically by `setup.py`, `adversarial_inject.py`, and `regression_tracker.py`. Proposers only see train-split results, preventing overfit to held-out data
- **Enriched metadata** — all created examples tagged with `source`, `added_at_iteration`, and `difficulty` (post-hoc from experiment scores)
- **Auto-correction** — evolve skill Steps 0.6 + 0.7 run before the iteration loop: creates missing splits, generates hard examples via testgen, fills coverage gaps from production data, retires dead examples
- **`--split` flag** on `read_results.py` — filter results by dataset split for proposer briefing
- **Playground** — 3 sample agents (simple-qa, rag-agent, react-agent) for testing the evolver

### Fixed

- **N+1 feedback queries** — `read_results.py`, `trace_insights.py`, and `regression_tracker.py` now batch all feedback in a single API call instead of one call per run

---

## [4.1.0] - 2026-04-02

### Added

- **Dynamic Lenses** — proposers now receive data-driven investigation questions (lenses) instead of fixed strategy assignments (exploit/explore/crossover/failure-targeted). Lenses are generated dynamically from failure clusters, architecture analysis, production traces, and evolution memory. Based on Dochkina (2026), ["Drop the Hierarchy and Roles"](https://arxiv.org/abs/2603.28990)
- **Self-Organizing Proposer (v4)** — proposers decide their own approach based on lens investigation. No prescribed strategies, no fixed workflow phases. Each proposer writes a self-described approach in `proposal.md`
- **Self-Abstention** — proposers can abstain when they assess their contribution as insufficient, saving evaluation tokens. Abstained candidates skip evaluation entirely
- **Dynamic proposer count** — `synthesize_strategy.py` generates 2-5 lenses based on available data. `max_proposers` field in `.evolver.json` controls the upper bound (default 5)
- **`--lenses` flag** on `synthesize_strategy.py` — outputs `lenses.json` alongside `strategy.md`

### Changed

- **Experiment naming** — candidates use numeric IDs (`v001-1`, `v001-2`) instead of letter suffixes (`v001a`, `v001b`)
- **Consolidation tracking** — `consolidate.py` tracks emergent approaches from `proposal.md` instead of mapping fixed labels (`strategy_map` removed)
- **Reporting format** — iteration reports show self-described approaches and abstention counts

### Removed

- **Fixed strategy system** — `<strategy>` blocks, fixed candidate labels (A-E), per-strategy tool restrictions, and hardcoded 5-proposer count are all removed
- **`strategy_map`** in `consolidate.py` — no longer maps suffix letters to strategy names

---

## [4.0.3] - 2026-04-02

### Added

- **`/dev:release` skill** — interactive release workflow: changelog generation, version bump in both `package.json` and `plugin.json`, git tag, GitHub release, npm publish — all in one command
- **`/dev:validate` skill** — plugin integrity checks: skill/agent frontmatter validation, cross-reference verification, Python tool syntax, version sync, hook executability
- **`/dev:dry-run` skill** — smoke-test the evolve pipeline: offline mode (syntax + argparse checks) or online mode (full setup → eval → read → trace pipeline with mock agent)

---

## [4.0.2] - 2026-04-02

### Fixed

- **Production data regression** — `synthesize_strategy.py` now reads `production_seed.json` via `--production-seed` flag (was completely ignored, losing real user inputs, error patterns, and negative feedback). Also restored `production_seed.json` to proposer `<files_to_read>`

### Removed

- **Self-scheduling** — `CronCreate` is session-scoped (dies when Claude exits) with 3-day expiry. "Nightly optimization" was impossible. Kept background mode which actually works
- **Per-proposer tool restrictions** — `Agent()` tool doesn't accept a `tools` parameter (`additionalProperties: false` in schema). Removed rather than provide false sense of enforcement

---

## [4.0.1] - 2026-04-02

### Fixed

- **Adversarial injection** — replaced fake `[REPHRASE]` string prefix with 4 real variation strategies: negation, constraint, ambiguous, partial input
- **State validator `--fix` flag** — was accepted by argparse but never used. Now auto-fixes dataset_id mismatch and history/best_experiment divergence
- **Evaluator templates** — replaced `no_hallucination_markers` (penalized hedging phrases, incentivizing overconfident wrong answers) with `no_fabricated_references` and `no_empty_filler`
- **CLAUDE.md** — updated "Five agent types" to Six, added evolver-consolidator
- **Orphaned consolidator agent** — evolve skill now spawns `evolver-consolidator` via `Agent()` instead of calling `consolidate.py` directly
- **Cron scheduling** — added `--no-interactive` flag so scheduled runs skip interactive prompts

---

## [4.0.0] - 2026-04-02

New features making the evolution loop smarter and more autonomous.

### Added

- **State Validation** (`tools/validate_state.py`) — skeptical memory pattern that validates `.evolver.json` against LangSmith reality before each iteration. Checks dataset existence, experiment accessibility, git state, and history consistency.
- **Three-Gate Iteration Triggers** (`tools/iteration_gate.py`) — score plateau detection, cost budget tracking, and statistical convergence analysis replace blind N-iteration loops. Auto-suggests architect on stagnation.
- **Regression Tracking** (`tools/regression_tracker.py`) — compares per-example scores between iterations, detects failing-to-passing transitions, and auto-injects regression guard examples into the LangSmith dataset.
- **autoConsolidate** (`tools/consolidate.py`, `agents/evolver-consolidator.md`) — cross-iteration memory consolidation inspired by Claude Code's autoDream. Four phases: orient, gather, consolidate, prune. Promotes insights to proposer briefings after 2+ recurrences.
- **Proposer Prompt Optimization** — restructured proposer prompts with a shared prefix (objective + files + context) and strategy-only suffix, enabling prompt cache reuse across 5 parallel proposers.
- **Proposer Turn Budget** — 16-turn cap with phased allocation (orient/diagnose/implement/test/commit) and stuck proposer detection via git log. Prevents runaway agents.
- **Coordinator Synthesis Phase** (`tools/synthesize_strategy.py`) — generates a targeted `strategy.md` from trace insights, results, evolution memory, and production traces. Proposers receive synthesized specs alongside raw data.
- **Active Critic** (`tools/add_evaluator.py`) — upgraded from passive reporter to active fixer. Detects evaluator gaming AND implements stricter code-based evaluators (`answer_not_question`, `no_fabricated_references`, `min_length`, `no_repetition`, `no_empty_filler`).
- **ULTRAPLAN Architect** — runs with `model: opus` for deep architectural analysis. Full codebase scan, AST-based topology classification, performance pattern analysis from evolution memory, and detailed migration plans.
- **Background Mode** — run all iterations in background while continuing to work. Get notified on completion or significant improvements.
- **Anti-Distillation** (`tools/adversarial_inject.py`) — detects potential memorization by comparing agent outputs to reference outputs, then injects adversarial rephrased examples to test generalization.

### Changed

- `agents/evolver-critic.md` — upgraded to Active Critic v3.1 with three phases (Detect, Act, Verify)
- `agents/evolver-architect.md` — upgraded to ULTRAPLAN Mode v3.1 with `model: opus` in frontmatter
- `agents/evolver-proposer.md` — added Turn Budget section
- `agents/evolver-testgen.md` — added Phase 3.5 for adversarial injection mode
- `skills/evolve/SKILL.md` — expanded with validation, gate checks, synthesis, consolidation, background mode, and restructured proposer spawning

---

## [3.3.1] - 2026-04-01

### Fixed

- 8 production bugs discovered during first real-world evolve run

---

## [3.3.0] - 2026-04-01

### Added

- Plugin marketplace support with SessionStart hook (`hooks/hooks.json`, `hooks/session-start.sh`)
- Redesigned installer UI with gradient banner and clack-style output
- Architecture section in README

### Fixed

- Box-drawing font rendering with green gradient for banner

---

## [3.2.0] - 2026-04-01

### Added

- Plugin marketplace install path (`/plugin marketplace add`)
- `SessionStart` hook auto-creates venv, installs langsmith + langsmith-cli, exports env vars

### Fixed

- Auto-version datasets on 409 conflict
- Handle null baseline gracefully in setup

---

## [3.1.0] - 2026-04-01

### Added

- Agent-based LLM-as-judge evaluator (`agents/evolver-evaluator.md`) — replaces openevals dependency entirely
- Context7 MCP is now mandatory in proposer agent (ensures up-to-date library docs)

### Removed

- `detect_stack.py` — replaced by Context7's library detection
- openevals dependency — evaluator agent IS the LLM judge

---

## [3.0.1] - 2026-03-31

### Fixed

- Installer cleans previous version before installing new one
- Auto-load LangSmith API key from langsmith-cli credentials file
- Installer insists on API key and offers langsmith-cli installation
- Isolated venv for Python deps instead of global pip install

---

## [3.0.0] - 2026-03-31

Complete rewrite. LangSmith-native architecture replaces custom eval harness.

### Added

- `tools/setup.py` — creates LangSmith datasets, configures evaluators, runs baseline
- `tools/run_eval.py` — executes agent against dataset via `client.evaluate()`
- `tools/read_results.py` — reads and compares LangSmith experiments
- `tools/trace_insights.py` — clusters errors, analyzes tokens, generates hypotheses from traces
- `tools/seed_from_traces.py` — imports production traces as test data
- `tools/analyze_architecture.py` — AST-based topology classification (stdlib-only)
- `skills/evolve/SKILL.md` — full evolution loop orchestration
- `skills/setup/SKILL.md` — interactive project setup with AskUserQuestion
- `skills/status/SKILL.md` — progress and stagnation detection
- `skills/deploy/SKILL.md` — tag, push, finalize
- `.evolver.json` as local state (replaces `config.json` + `summary.json`)

### Changed

- Evaluation backend: LangSmith Datasets + Experiments (was custom `tasks/*.json` + `eval.py`)
- Proposer isolation: native git worktrees via `isolation: "worktree"` (was manual branch management)
- State: hybrid `.evolver.json` + LangSmith (was local-only `config.json`)

### Removed

- `harness.py` contract — proposers modify real code directly
- `eval.py` — replaced by `run_eval.py` + LangSmith SDK
- `tasks/*.json` — replaced by LangSmith Datasets
- All v2 artifacts and references

---

## [2.9.1] - 2026-03-31

### Changed

- Use preview mode for eval and LangSmith questions in interactive UX

---

## [2.9.0] - 2026-03-31

### Added

- Interactive UX with `AskUserQuestion` in init, evolve, and deploy skills
- Multi-select for optimization goals, single-select for iteration count

---

## [2.8.0] - 2026-03-31

### Added

- Auto-discover and leverage existing LangSmith production traces
- Production-aware proposer briefings (real user inputs, error patterns, negative feedback)

### Fixed

- Init timeout scaling for large projects
- Segfault tolerance in eval orchestrator
- Auto-detect source files in monorepo setups

---

## [2.6.0] - 2026-03-31

### Added

- `trace_insights.py` — error clustering, token analysis, score cross-referencing, hypothesis generation
- Test suite growth — add regression examples to dataset after iteration
- Import production traces from existing LangSmith projects

---

## [2.2.0] - 2026-03-31

### Added

- Adaptive quality-diversity evolution (replaces fixed proposer strategies)
- 5 parallel proposers per iteration: exploit, explore, crossover, prompt-focused, retrieval-focused
- LLM-as-judge via subagent + synthetic test generation
- Per-task champion selection (quality-diversity)

### Fixed

- Process LangSmith runs into readable format for proposers
- TestGen uses concrete file paths instead of unresolved placeholders

---

## [1.0.0] - 2026-03-31

### Added

- Architect agent (`agents/evolver-architect.md`) — recommends topology changes on stagnation
- Critic agent (`agents/evolver-critic.md`) — detects evaluator gaming
- Auto-trigger architect after 3 stagnant iterations or any regression
- Auto-trigger critic on suspicious score jumps
- Orchestrator gathers LangSmith + Context7 data before dispatching agents
- Color-coded agents: proposer (green), architect (blue), critic (red)
- Parallel multi-candidate evolution: exploit, explore, crossover strategies
- Optional integrations in installer: LangSmith CLI, Context7, LangChain Docs

---

## [0.5.1] - 2026-03-31

### Added

- Interactive installer with runtime selection (Claude Code, Cursor, Codex, Windsurf) and ASCII branding
- Intelligent `/harness-evolve-init` with project auto-detection
- Plugin namespace (`plugin:skill` → `evolver:skill`)
- Compare, deploy, diagnose skills
- LLM API key detection in environment during init

### Fixed

- Harness example reads API key from env only, not config

---

## [0.1.0] - 2026-03-31

Initial release.

### Added

- Proposer agent definition
- Init, evolve, status skills
- Evaluation orchestrator with trace capture
- State manager (`summary.json`, `STATE.md`, `PROPOSER_HISTORY.md`)
- TraceLogger helper for structured trace recording
- Classifier example with mock mode (10 tasks)
- npm package and installer for Claude Code
- LangSmith integration (env var tracing + langsmith-cli)
- Context7 integration (stack detection + documentation-aware proposer)
