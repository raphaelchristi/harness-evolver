# Changelog

All notable changes to Harness Evolver are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioned per [Semantic Versioning](https://semver.org/).

---

## [4.8.1] - 2026-04-03

### Fixed

- **`top_failing` in summary now populated** — Threshold changed from `< 0.5` to `<= 0.5` so examples with combined score 0.5 (e.g., has_output=1.0 + correctness=0.0) are included. Added `output_preview` (80 chars) to each entry. Summary now provides actionable context: input + output + feedback for top 3 failures (~800 bytes vs 27KB full).

---

## [4.8.0] - 2026-04-03

Four context engineering improvements inspired by [Agent Skills for Context Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering).

### Added

- **Justification-before-score** — Evaluator agent now reasons through correctness BEFORE assigning a score. Improves LLM-as-judge reliability 15-25%. Added position bias warning to prevent order-dependent scoring.
- **`--format summary`** — `read_results.py` and `trace_insights.py` support compact output (~200 tokens vs ~5K). Returns aggregated metrics, failure pattern, and top 3 failing inputs instead of full per-example data. Reduces context bloat for strategy generation.
- **Strategy.md filtering** — Evolve skill now instructs: current iteration data only, top 3 promoted insights from memory, 1500 token cap. Stale data from prior iterations is an active distractor per context degradation research.
- **Anchored iterative summarization** — Consolidator agent treats promoted insights (rec >= 3) as immutable anchors that are never re-summarized. New observations use literal text from proposal.md sections. Garbage collection removes observations not recurring in 5+ iterations.

---

## [4.7.0] - 2026-04-03

Three improvements targeting the agent's 9+/10 criteria.

### Added

- **Integrated preflight** — New `tools/preflight.py` runs 5 checks in one pass: API key resolution, config schema validation, LangSmith state verification, dataset health, and entry point canary. Replaces 3 separate steps (0.5 + 0.6 + canary) with a single invocation. Reports all issues at once instead of failing across multiple steps.
- **Config schema validation** — `validate_config_schema()` in `validate_state.py` checks required fields, types, history structure, evaluator_weights, and evaluator list. Catches malformed `.evolver.json` before it causes cryptic errors downstream.
- **Proposer observability** — Evolve skill now reports each proposer's completion as it happens: `"Proposer N (lens) completed — committed/abstained. Progress: 2/4"`. Users see progress while other proposers are still running.

---

## [4.6.0] - 2026-04-03

Three structural improvements from the agent's final verdict (7/10 review).

### Added

- **Auto-copy worktree files** — `run_eval.py` automatically copies `.evolver.json` and `.env` from the config directory to the worktree if missing. Eliminates the most frequent bug from all real-world reports (worktree untracked files).
- **Preflight mode** — `run_eval.py --preflight-only` runs API key check + canary + config validation in one command, then exits. Single command to verify everything works before running full evolution.
- **Atomic config writes** — `add_evaluator.py`, `validate_state.py`, and `setup.py` now write `.evolver.json` via temp file + `os.replace()` (atomic on same filesystem). Prevents corruption from concurrent writers (critic + main loop).

---

## [4.5.4] - 2026-04-03

### Fixed

- **Project .env takes precedence over global credentials** — Reordered `ensure_langsmith_api_key()` in all 7 tools: env var > project `.env` > global `~/.config/langsmith-cli/credentials`. Fixes stale/invalid key in global credentials file shadowing the valid key in the project's `.env`. This was the root cause of the persistent 403 Forbidden bug across all real-world runs.

---

## [4.5.3] - 2026-04-03

Fixes the two longest-standing bugs across all 4 REPORT.md files.

### Fixed

- **LANGSMITH_API_KEY .env resolution** — All 7 tools with `ensure_langsmith_api_key()` now search `.env` in both CWD AND the `--config` file's directory. Fixes the bug that hit every single real-world run: tools failed with 403 Forbidden when CWD differed from the project directory. No more `set -a && source .env && set +a` workaround needed.
- **`constraint_check.py` pytest skip** — "No module named pytest" in stderr is now treated as skip (pass) instead of test failure. Previously, valid candidates were rejected when pytest wasn't installed in the project's venv.

---

## [4.5.2] - 2026-04-03

Fixes from second round of real-world testing (arag project REPORT.md).

### Fixed

- **`constraint_check.py` uses project venv for pytest** — Detects `.venv/bin/python` or extracts Python path from `entry_point` config instead of using system `python3`. Fixes false test failures when pytest is only in the venv.
- **`add_evaluator.py` race condition** — Re-reads `.evolver.json` immediately before writing to pick up concurrent changes from the main loop. Prevents critic agent from overwriting `best_score`, `iterations`, and `history` fields.
- **`evolution_chart.py` "? examples"** — Searches all history entries for `total` field, not just baseline. Fixes display when baseline was created before enriched history (v4.4.0+).

---

## [4.5.1] - 2026-04-02

Fixes the 4 highest-frequency bugs from real-world evolution runs (3 independent REPORT.md files).

### Fixed

- **`{input_text}` placeholder** — New placeholder in `run_eval.py` extracts plain text from inputs dict and shell-escapes it. Fixes the #1 bug (3/3 repos): agents receiving JSON file paths instead of query text. Use `{input_text}` for agents that take `--query "text"`.
- **Worktree file propagation** — Evolve skill now copies `.evolver.json` and `.env` into worktrees before evaluation (step 3). Fixes the #2 bug (3/3 repos): `FileNotFoundError` for untracked config files in git worktrees.
- **Canary preflight** — `run_eval.py` runs 1 example before the full evaluation to catch broken agents early. Exits with code 2 if canary fails. Prevents wasting API quota on broken runs (OpenAI report #6). Disable with `--no-canary`.
- **Baseline LLM-judge** — New step 0.7 in evolve skill: if baseline only has code-based evaluator scores (has_output), trigger the evaluator agent to score it with LLM-judge before the loop starts. Prevents inflated baseline scores that cause premature stopping (ARAG report #4).

---

## [4.5.0] - 2026-04-02

9 improvements inspired by [NousResearch/hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution), hardening evaluation rigor, data safety, and decision quality.

### Added

- **Rubric-based evaluation** — Dataset examples support `expected_behavior` rubrics in metadata. Evaluator agent scores against specific criteria instead of generic correctness. Testgen agent generates rubrics automatically. `setup.py` parses `expected_behavior`, `difficulty`, and `category` fields from input files.
- **Constraint gates** — New `constraint_check.py` (stdlib-only) validates proposals before merge: code growth ≤30%, entry point syntax valid, test suite passes. Step 4.5 in evolve skill rejects failing candidates and falls back to next-best.
- **Evaluator weights** — `evaluator_weights` field in `.evolver.json` enables weighted scoring (e.g., `{"correctness": 0.5, "latency": 0.3}`). `read_results.py` uses `weighted_score()` instead of flat average.
- **Judge feedback in proposers** — `read_results.py` captures `feedback_comments` from LangSmith feedback. Evolve skill surfaces judge comments in proposer strategy for targeted mutations.
- **Secret detection** — New `secret_filter.py` (stdlib-only) detects 15+ secret patterns (API keys, tokens, PEM keys). Integrated into `seed_from_traces.py` (skips runs with secrets) and `dataset_health.py` (flags examples with secrets as critical issue).
- **Holdout enforcement** — Candidate comparison now uses `--split held_out` for unbiased winner selection. Split filtering works in both single and multi-experiment modes.
- **Code growth tracking** — `code_loc` field in history entries. Evolution chart shows LOC column with ⚠ warning when growth exceeds 30% vs baseline.
- **Pareto selection** — `read_results.py` computes Pareto front across evaluators via `pareto_front()`. Evolve skill reports non-dominated candidates when tradeoffs exist.
- **Session mining** — New `mine_sessions.py` (stdlib-only) extracts eval data from Claude Code session history (`~/.claude/`), with keyword relevance filtering and secret detection.

---

## [4.4.0] - 2026-04-02

### Added

- **Evolution chart** — New `evolution_chart.py` (stdlib-only) renders rich ASCII chart with ANSI colors: header with sparkline, score progression table, per-evaluator breakdown, what-changed narrative, and horizontal bar chart. Called by `/evolver:evolve` (final report) and `/evolver:status`.
- **Enriched history** — `.evolver.json` history entries now store `tokens`, `latency_ms`, `error_count`, `passing`, `total`, `per_evaluator`, `approach`, and `lens` alongside score. Backward compatible with lean entries.

---

## [4.3.1] - 2026-04-02

### Added

- **Parallel candidate evaluation** — `run_eval.py` for all candidates runs simultaneously via `&` + `wait` instead of sequentially. ~2.5min → ~30s for 5 candidates.
- **Parallel data gathering** — `trace_insights.py`, `read_results.py`, and `seed_from_traces.py` run in parallel. ~15s → ~5s.
- **Configurable eval concurrency** — `run_eval.py` accepts `--concurrency` flag and reads `eval_concurrency` from `.evolver.json`. Default 1, set higher for agents that handle concurrent calls.

---

## [4.3.0] - 2026-04-02

Refactor inspired by ["Harnessing Claude's Intelligence"](https://claude.com/blog/harnessing-claudes-intelligence) (Lance Martin, Anthropic). Core principle: "What can I stop doing?"

### Added

- **`/evolver:health` skill** — dataset quality check + auto-correct, extracted from evolve. Independently invocable.

### Changed

- **Evolve skill** — 734 → 542 lines (-26%). Agent prompts deduped (reference agent .md instead of inline), `synthesize_strategy.py`/`iteration_gate.py`/`consolidate.py` replaced with direct Claude analysis, health check delegated to `/evolver:health`
- **Proposer agent** — 158 → 119 lines (-25%). Turn budget as guidance (10-15 turns) not mandate (max 16). Context7 recommended not mandatory. Workflow simplified.
- **Setup skill** — 3 interactive questions → 1 smart-default confirmation on happy path ("Looks good, proceed" uses defaults)
- **`seed_from_traces.py`** — 482 → 401 lines (-17%). SDK-only, removed urllib dual implementation

### Removed

- **`synthesize_strategy.py` from evolve loop** — Claude generates strategy.md + lenses.json directly from analysis data
- **`iteration_gate.py` from evolve loop** — Claude assesses gate conditions directly
- **`consolidate.py` from evolve loop** — consolidator agent handles everything (tool was redundant scaffolding)

---

## [4.2.9] - 2026-04-02

### Fixed

- **MCP detection in per-project configs** — `claude mcp add` saves servers under `projects[path].mcpServers` in `.claude.json`, not top-level. Installer now searches both locations via `hasMcpServer()` helper. Fixes LangChain Docs MCP not being detected after install.

---

## [4.2.8] - 2026-04-02

### Fixed

- **Installer detects marketplace plugins** — Context7 and LangChain Docs installed via `/plugin install` are now detected from `~/.claude/plugins/marketplaces/`, not just `mcpServers` in settings.json. No longer asks to install what's already there.

---

## [4.2.7] - 2026-04-02

### Fixed

- **npm tarball size** — `__pycache__/*.pyc` excluded via `files: tools/*.py` in package.json. Tarball: 107kB → 69kB, 39 → 31 files.

---

## [4.2.6] - 2026-04-02

### Added

- **`--yes` flag** on installer — non-interactive mode for CI/scripts (`npx harness-evolver@latest --yes`)
- **API key validation** — installer validates key with real HTTP request before saving
- **Upgrade detection** — shows "Upgrading X → Y" vs "Fresh install" vs "Reinstalling"
- **Plugin marketplace note** — final output shows `/plugin install harness-evolver`
- **`.worktreeinclude` hint** — suggests creating `.worktreeinclude` for worktree support
- **Never expose API key** — skills instruct agents to never pass `LANGSMITH_API_KEY` inline in Bash commands

### Fixed

- **npm tarball bloat** — `.npmignore` excludes `__pycache__/`, `docs/`, `playground/`, `.claude/`, `CHANGELOG.md`

---

## [4.2.5] - 2026-04-02

### Fixed

- **BLOCKER: Entry point relative paths in worktrees** — `setup.py` now resolves relative Python interpreter paths (e.g., `../.venv/bin/python`) to absolute paths before saving to `.evolver.json`. Fixes "No such file or directory" when agents run in worktrees where venvs don't exist.
- **`.evolver.json` missing in worktrees** — new `.worktreeinclude` file ensures `.evolver.json` and `.env` are copied to worktrees despite being gitignored
- **Orphaned datasets on setup failure** — `setup.py` now wraps dataset creation in try/except and cleans up orphaned datasets if setup fails mid-way

---

## [4.2.4] - 2026-04-02

### Fixed

- **Venv detection in setup skill** — Phase 1 now checks `.venv/`, `venv/`, `../.venv/`, `../venv/` and suggests the venv Python for the entry point instead of bare `python`. Prevents "module not found" failures when agent dependencies are in a venv.
- **Playground docs** — updated README with venv creation instructions (`uv venv`) and correct entry point using venv Python

---

## [4.2.3] - 2026-04-02

### Fixed

- **Worktree subdirectory resolution** — `setup.py` computes `project_dir` (relative path from git root via `git rev-parse --show-prefix`) and stores it in `.evolver.json`. Evolve skill Step 0.8 reads this to resolve all worktree paths correctly. Fixes `FileNotFoundError` when project is in a monorepo subdirectory.
- **Smarter uniform-failure lenses** — when all examples fail with the same error, `synthesize_strategy.py` now generates a `uniform_failure` lens (critical) + `input_diversity` lens instead of only the generic open lens

---

## [4.2.2] - 2026-04-02

### Fixed

- **LangSmith runs query limit** — changed `limit=200` to `limit=100` in 5 tools (`read_results.py`, `regression_tracker.py`, `adversarial_inject.py`, `trace_insights.py`, `dataset_health.py`). LangSmith API rejects `POST /runs/query` with limit > 100, causing Step 1.8 (per-task failure analysis) to return empty results and degrade lens generation

---

## [4.2.1] - 2026-04-02

### Fixed

- **API key source tracking** — `ensure_langsmith_api_key()` now reports WHERE the key came from (environment, credentials file, .env) and gives clear error messages when a credentials-file key is invalid instead of a generic 403 traceback
- **Write permission check** — setup validates write access (create+delete temporary dataset) before proceeding, catching 403 before the real dataset creation
- **Retry on transient 403** — new `create_dataset_with_retry()` with 3 attempts and exponential backoff for transient LangSmith 403/500 errors (SDK doesn't retry 403)
- **Baseline experiment saved on score failure** — `run_baseline()` returns experiment name even when score extraction fails (`'dict' object has no attribute 'evaluation_results'`), handling both object and dict SDK result formats
- **best_experiment always set** — baseline_experiment is always populated when the experiment exists, so best_experiment and history are never null after a successful setup

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
