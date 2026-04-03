# Architecture

For the quick overview, see [README.md](../README.md).

## Three Layers

```
Plugin hook (SessionStart)
  └→ Creates venv, installs langsmith + langsmith-cli, exports env vars

Skills (markdown)
  ├── /evolver:setup    → explores project, smart defaults, runs setup.py
  ├── /evolver:health   → dataset quality + secret scan + auto-correct
  ├── /evolver:evolve   → orchestrates the evolution loop
  ├── /evolver:status   → rich ASCII evolution chart + stagnation detection
  └── /evolver:deploy   → tags and pushes

Agents (markdown)
  ├── Proposer (xN)     → self-organizing, lens-driven, isolated git worktrees
  ├── Evaluator          → rubric-aware LLM-as-judge via langsmith-cli
  ├── Critic             → detects gaming + implements stricter evaluators
  ├── Architect          → ULTRAPLAN deep analysis (opus model)
  ├── Consolidator       → cross-iteration memory (autoDream-inspired)
  └── TestGen            → generates test inputs with rubrics + adversarial injection

Tools (Python)
  ├── setup.py              → creates datasets, configures evaluators + weights
  ├── run_eval.py           → runs target against dataset (canary preflight, {input_text})
  ├── read_results.py       → weighted scoring, Pareto front, pairwise comparison
  ├── trace_insights.py     → clusters errors from traces
  ├── seed_from_traces.py   → imports production traces (secret-filtered)
  ├── evolution_chart.py    → rich ASCII chart (stdlib-only)
  ├── constraint_check.py   → validates proposals (growth, syntax, tests) (stdlib-only)
  ├── secret_filter.py      → detects 15+ secret patterns (stdlib-only)
  ├── mine_sessions.py      → extracts eval data from Claude Code history (stdlib-only)
  ├── preflight.py          → integrated pre-loop validation (stdlib-only)
  ├── archive.py            → persistent candidate history (stdlib-only)
  ├── dataset_health.py     → dataset quality diagnostic + secret scanning
  ├── validate_state.py     → validates config vs LangSmith state
  ├── regression_tracker.py → tracks regressions, auto-adds failure guards
  ├── add_evaluator.py      → programmatically adds evaluators
  ├── adversarial_inject.py → detects memorization, injects adversarial tests
  └── _common.py            → shared utilities (API key resolution, atomic writes)
```

## Entry Point Placeholders

| Placeholder | Behavior | Use when |
|---|---|---|
| `{input_text}` | Extracts plain text, shell-escapes it | Agent takes `--query "text"` or positional args |
| `{input}` | Passes path to a JSON file | Agent reads structured JSON from file |
| `{input_json}` | Passes raw JSON string inline | Agent parses JSON from command line |

**Example:**
```bash
python agent.py --query {input_text}   # text input
python agent.py {input}                # JSON file path
```

## Evolution Loop (detailed)

```
/evolver:evolve
  |
  +- 0.5  Validate state (check .evolver.json vs LangSmith)
  +- 0.6  /evolver:health — dataset quality + secret scan + auto-correct
  +- 0.7  Baseline LLM-judge — re-score baseline if only has_output exists
  +- 1.   Read state (.evolver.json + LangSmith experiments)
  +- 1.5  Gather trace insights + judge feedback (parallel, --format summary)
  +- 1.8  Analyze per-task failures with judge comments (train split only)
  +- 1.8a Generate strategy.md (1500 token cap) + lenses.json (incl. archive_branch)
  +- 1.9  Prepare shared proposer context (KV cache-optimized prefix)
  +- 2.   Wave 1: spawn critical/high proposers in parallel worktrees
  +- 2.5  Wave 2: medium/open proposers see wave 1 results before starting
  +- 3.   Copy config + archive to worktrees, run canary, evaluate candidates
  +- 3.5  Spawn evaluator agent (rubric-aware, few-shot calibrated LLM-as-judge)
  +- 4.   Compare on held-out split → winner + Pareto front + pairwise if close
  +- 4.5  Constraint gate — reject candidates that break size/tests/entry-point
  +- 5.   Merge winning worktree into main branch
  +- 5.5  Archive ALL candidates (winners + losers)
  +- 5.6  Regression tracking + auto-guard failures (train-only, deduplicated)
  +- 6.   Report results + evolution chart
  +- 6.2  Consolidator agent updates evolution memory (background)
  +- 6.5  Auto-trigger Active Critic if score jump >0.3
  +- 7.   Auto-trigger ULTRAPLAN Architect if 3 iterations stagnated
  +- 8.   Gate check (plateau, target reached, diminishing returns)
```
