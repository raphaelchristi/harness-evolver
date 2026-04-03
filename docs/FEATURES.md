# Features

Full feature list for Harness Evolver. For the quick overview, see [README.md](../README.md).

## Core

| Feature | Description |
|---|---|
| **LangSmith-Native** | No custom eval scripts or task files. Uses LangSmith Datasets for test inputs, Experiments for results, and an agent-based LLM-as-judge for scoring via langsmith-cli. No external API keys needed. Everything is visible in the LangSmith UI. |
| **Real Code Evolution** | Proposers modify your actual agent code — not a wrapper. Each candidate works in an isolated git worktree. Winners are merged automatically. Config files (.evolver.json, .env, evolution_archive/) are auto-propagated to worktrees. |
| **Self-Organizing Proposers** | Two-wave spawning: critical lenses run first, then medium/open lenses see wave 1 results (+14% quality). Dynamic investigation lenses from failure data, architecture analysis, production traces, evolution memory, and archive branching (revisit losing candidates). Proposers self-organize, self-abstain, and can fork from any ancestor. |
| **Evolution Modes** | Three intensity levels: `light` (20 examples, 2 proposers, sample eval, ~2 min/iter), `balanced` (30 examples, 3 proposers, full train, ~8 min/iter), `heavy` (50 examples, 5 proposers, full dataset, ~25 min/iter). Selected at setup, switchable at evolve start. |
| **Background Mode** | Run all iterations in background while you continue working. Get notified on completion or significant improvements. |

## Evaluation

| Feature | Description |
|---|---|
| **Rubric-Based Evaluation** | Dataset examples support `expected_behavior` rubrics — specific criteria the judge evaluates against, not just generic correctness. Partial scoring (0.5) for partially-met rubrics. |
| **Agent-Based LLM-as-Judge** | Justification BEFORE score (15-25% reliability improvement). Rubric-aware scoring via langsmith-cli. Judge feedback surfaced to proposers. Position bias mitigation. Few-shot self-improvement from human corrections. Pairwise head-to-head comparison when top candidates are within 5%. |
| **Weighted Evaluators + Pareto** | Configure `evaluator_weights` to prioritize what matters. Pareto front reported when candidates offer different tradeoffs. MAP-Elites diversity grid preserves approach diversity. |
| **Canary Preflight** | 1 example tested before full evaluation. If agent produces no output, evaluation stops immediately. Accepts both `output` and `answer` response formats. |
| **Rate-Limit Early Abort** | After 5+ runs, if >50% hit 429 errors, evaluation stops to save API quota. Reports `rate_limited: true` + `aborted_early: true` in output. |
| **Evolution Tracing** | Each iteration logged as a LangSmith run with score, approach, duration. With the langsmith-tracing companion, proposer tool calls nest hierarchically under iterations. Full evolution timeline in LangSmith UI. |
| **has_output Excluded** | `has_output` evaluator tracked but excluded from combined score by default (weight=0). Any `print()` gives 1.0, inflating scores artificially. |
| **`--strict` Evaluator Validation** | `add_evaluator.py --strict` rejects evaluators without known implementation. Prevents ghost evaluators in config. |

## Safety

| Feature | Description |
|---|---|
| **Constraint Gates** | Proposals must pass hard constraints before merge: code growth <=30%, entry point syntax valid (Python/JS/TS/shell), test suite passes. Fails closed when validation tools unavailable. |
| **Efficiency Gate** | Pre-merge check: tokens >2x with <2% score improvement or latency >50% with <5% gain → reject candidate. Prevents merging expensive regressions. |
| **Secret Detection** | Detects 15+ secret patterns (API keys, tokens, PEM keys). Filtered from production trace imports and flagged in dataset health checks. |
| **Smart Gating** | Score plateau, target reached, diminishing returns. Holdout enforcement ensures final comparison uses unseen data. Baseline re-scored with LLM-judge before loop. |
| **Active Critic** | Auto-triggers on suspicious score jumps. Detects evaluator gaming AND implements stricter evaluators. |
| **Regression Guards** | Failed examples auto-added as permanent regression tests. Deduplication prevents inflation. Train-only (never contaminates held_out). |

## Intelligence

| Feature | Description |
|---|---|
| **Evolution Archive** | Persistent history of ALL candidates (winners + losers) — diffs, proposals, scores. Proposers grep archive for cross-iteration causal reasoning. |
| **Evolution Memory** | Anchored iterative summarization — promoted insights are immutable anchors. Garbage collection removes stale observations. |
| **ULTRAPLAN Architect** | Auto-triggers on stagnation. Opus model for deep architectural analysis. Recommends topology changes. |
| **Production Traces** | Auto-discovers LangSmith production projects. Real user inputs for test generation. Can also mine Claude Code session history. |

## Operations

| Feature | Description |
|---|---|
| **`update_config.py`** | Atomic config update after merge. Three actions: `backup` (before merge), `restore` (after merge overwrites), `update` (increments iterations, appends enriched history). Replaces manual inline Python. |
| **`cleanup_worktrees.py`** | Removes orphan worktrees from `.claude/worktrees/` after eval. `--dry-run` to preview, `--keep` to preserve specific ones. Prevents worktree accumulation. |
| **Rubric Pinning** | Evaluator includes rubric text in feedback comment (`RUBRIC: ... JUDGMENT: ...`). Makes scores reproducible and diagnosable across iterations. |
| **`--retry-on-rate-limit`** | When rate-limited, `run_eval.py` waits 60s and suggests re-run instead of just aborting. |

## Visualization

| Feature | Description |
|---|---|
| **Evolution Chart** | Rich ASCII visualization with ANSI colors: sparkline trend, score progression table, per-evaluator breakdown, what-changed narrative, horizontal bar chart, code growth tracking. |
| **Integrated Preflight** | 5 checks in one pass: API key, config schema, LangSmith state, dataset health, canary. Reports all issues at once. |
