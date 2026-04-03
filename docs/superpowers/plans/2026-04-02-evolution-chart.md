# Evolution Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a rich ASCII evolution chart with ANSI colors that visualizes score progression, per-evaluator breakdown, what changed per iteration, and a horizontal bar chart — displayed at the end of `/harness:evolve` and via `/harness:status`.

**Architecture:** A new stdlib-only Python tool (`tools/evolution_chart.py`) reads the enriched `.evolver.json` history and optionally `best_results.json` to render 5 sections: header, score progression table, per-evaluator breakdown, what-changed narrative, and score bar chart. The evolve skill's Step 5 is updated to write richer history entries. Both evolve (final report) and status skills call the tool.

**Tech Stack:** Python 3 stdlib only (json, argparse, os, shutil). ANSI escape codes for color. Unicode box-drawing and block characters.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `tools/evolution_chart.py` | Reads `.evolver.json` + `best_results.json`, renders ASCII chart to stdout |
| Modify | `skills/evolve/SKILL.md:408-421` | Enrich history entries with tokens, latency, errors, passing, per_evaluator, approach, lens |
| Modify | `skills/evolve/SKILL.md:530-537` | Replace bullet-point final report with evolution_chart.py call |
| Modify | `skills/status/SKILL.md` | Replace inline Python with evolution_chart.py call |
| Modify | `CLAUDE.md` | Add evolution_chart.py usage to tool documentation |

---

### Task 1: Create `tools/evolution_chart.py`

**Files:**
- Create: `tools/evolution_chart.py`

This is the core deliverable. Stdlib-only (no langsmith dependency), follows the existing tool conventions (argparse, `--config`, `--output`).

- [ ] **Step 1: Create the tool with ANSI helpers and CLI skeleton**

```python
#!/usr/bin/env python3
"""Evolution chart — ASCII visualization of agent optimization progress.

Reads .evolver.json history and optionally best_results.json to render
a rich terminal chart with score progression, per-evaluator breakdown,
change narrative, and horizontal bar chart.

Usage:
    python3 evolution_chart.py --config .evolver.json
    python3 evolution_chart.py --config .evolver.json --no-color

Stdlib-only — no langsmith dependency.
"""

import argparse
import json
import os
import shutil
import sys


# ─── ANSI codes (disabled by --no-color or non-TTY) ───

class Colors:
    def __init__(self, enabled=True):
        if enabled:
            self.G = '\033[32m'    # green
            self.R = '\033[31m'    # red
            self.Y = '\033[33m'    # yellow
            self.C = '\033[36m'    # cyan
            self.B = '\033[1m'     # bold
            self.D = '\033[90m'    # dim
            self.RST = '\033[0m'   # reset
        else:
            self.G = self.R = self.Y = self.C = ''
            self.B = self.D = self.RST = ''


def sparkline(values):
    """Render a sparkline using Unicode block characters."""
    blocks = ' ▁▂▃▄▅▆▇█'
    if not values:
        return ''
    mn, mx = min(values), max(values)
    rng = mx - mn or 1
    return ''.join(blocks[min(8, int((v - mn) / rng * 8))] for v in values)


def hbar(val, width, c):
    """Render a horizontal bar: filled + empty."""
    filled = round(val * width)
    return f'{c.G}{"█" * filled}{c.D}{"░" * (width - filled)}{c.RST}'


def fmt_tokens(t):
    """Human-readable token count."""
    if not t:
        return '—'
    if t >= 1_000_000:
        return f'{t / 1_000_000:.1f}M'
    if t >= 1000:
        return f'{t / 1000:.1f}k'
    return str(t)


def trend_icon(delta, is_best, c):
    """Return a colored trend indicator."""
    if is_best and delta >= 0:
        return f'{c.G}★{c.RST}'
    if delta > 0:
        return f'{c.G}▲{c.RST}'
    if delta < -0.01:
        return f'{c.R}▼{c.RST}'
    if delta < 0:
        return f'{c.Y}━{c.RST}'
    return f'{c.Y}━{c.RST}'


def render_header(config, history, scores, c):
    """Render the header box with summary stats."""
    project = config.get('project', 'unknown')
    dataset = config.get('dataset', 'unknown')
    evals = config.get('evaluators', [])
    total = history[0].get('total', config.get('num_examples', '?'))
    base_score = scores[0]
    best_score = max(scores)
    iters = len(history) - 1
    pct = ((best_score - base_score) / base_score * 100) if base_score > 0 else 0
    spark = sparkline(scores)
    evals_str = ' · '.join(evals)

    W = 70
    lines = []
    lines.append(f'  {c.C}╔{"═" * W}╗{c.RST}')
    lines.append(f'  {c.C}║{c.RST}  {c.B}EVOLUTION REPORT{c.RST}{" " * (W - 18)}{c.C}║{c.RST}')
    lines.append(f'  {c.C}║{c.RST}  {project:<{W - 16}}{c.D}{iters} iterations{c.RST}  {c.C}║{c.RST}')
    lines.append(f'  {c.C}║{c.RST}  {c.D}dataset{c.RST}  {dataset} ({total} examples){" " * max(0, W - 22 - len(dataset) - len(str(total)))}{c.C}║{c.RST}')
    lines.append(f'  {c.C}║{c.RST}  {c.D}evals{c.RST}    {evals_str:<{W - 11}}{c.C}║{c.RST}')
    lines.append(f'  {c.C}║{c.RST}  {c.D}trend{c.RST}    {spark}  {base_score:.3f} → {c.G}{c.B}{best_score:.3f}{c.RST} {c.G}(+{pct:.1f}%){c.RST}{" " * max(0, W - 40 - len(spark))}{c.C}║{c.RST}')
    lines.append(f'  {c.C}╚{"═" * W}╝{c.RST}')
    return '\n'.join(lines)


def render_score_table(history, scores, c):
    """Render the score progression table."""
    base = scores[0]
    best = max(scores)
    W = 70

    lines = []
    lines.append(f'  {c.B}SCORE PROGRESSION{c.RST}')
    lines.append(f'  {c.D}{"─" * W}{c.RST}')
    lines.append(f'  {c.D}{"Version":<10}{"Score":>6}{"Δ":>8}{"vs Base":>9}{"Pass":>7}{"Err":>5}{"Tokens":>8}{"Latency":>9}{c.RST}')
    lines.append(f'  {c.D}{"─" * W}{c.RST}')

    for i, h in enumerate(history):
        v = h['version']
        s = h['score']
        passing = h.get('passing')
        total = h.get('total')
        errors = h.get('error_count', h.get('errors'))
        tokens = h.get('tokens', 0)
        latency = h.get('latency_ms', 0)

        # Score column — highlight best
        s_str = f'{c.G}{c.B}{s:.3f}{c.RST}' if s == best else f'{s:.3f}'

        # Delta & % columns
        if i == 0:
            d_str = f'{c.D}{"—":>7}{c.RST}'
            p_str = f'{c.D}{"—":>8}{c.RST}'
            icon = ''
        else:
            d = s - history[i - 1]['score']
            pct = ((s - base) / base * 100) if base > 0 else 0
            dc = c.G if d > 0 else (c.R if d < 0 else c.Y)
            d_str = f'{dc}{d:>+7.3f}{c.RST}'
            p_str = f'{dc}{pct:>+7.1f}%{c.RST}'
            icon = trend_icon(d, i == len(history) - 1 and s == best, c)

        # Pass column
        if passing is not None and total is not None:
            pass_str = f'{passing}/{total}'
        else:
            pass_str = '—'

        # Error column
        if errors is not None:
            e_str = f'{c.R}{errors}{c.RST}' if errors > 0 else f'{c.G}{errors}{c.RST}'
        else:
            e_str = '—'

        tok_str = fmt_tokens(tokens)
        lat_str = f'{latency}ms' if latency else '—'

        lines.append(f'  {v:<10}{s_str:>6}  {d_str}  {p_str} {pass_str:>5}  {e_str:>3}  {tok_str:>6}  {lat_str:>6}  {icon}')

    return '\n'.join(lines)


def render_evaluator_breakdown(history, config, best_results, c):
    """Render per-evaluator trends from baseline to best."""
    evaluators = config.get('evaluators', [])
    if not evaluators:
        return ''

    # Try to get per-evaluator data from enriched history
    has_per_eval = any(h.get('per_evaluator') for h in history)

    # Fallback: extract from best_results.json for baseline vs best comparison
    if not has_per_eval and not best_results:
        return ''

    W = 70
    lines = []
    lines.append(f'  {c.B}PER-EVALUATOR BREAKDOWN{c.RST}')
    lines.append(f'  {c.D}{"─" * W}{c.RST}')

    if has_per_eval:
        # Rich mode: show all evaluators across all iterations
        lines.append(f'  {c.D}{"Evaluator":<20}{"Base":>6}{"Best":>7}{"Δ":>7}  {"":20}  Trend{c.RST}')
        lines.append(f'  {c.D}{"─" * W}{c.RST}')

        for ev in evaluators:
            vals = [h.get('per_evaluator', {}).get(ev, 0) for h in history]
            bv = vals[0]
            best_v = vals[-1]
            delta = best_v - bv
            dc = c.G if delta > 0 else c.R
            spark_ev = sparkline(vals)

            lines.append(
                f'  {ev:<20}{bv:>5.2f} → {dc}{c.B}{best_v:.2f}{c.RST}'
                f'  {dc}{delta:>+6.2f}{c.RST}'
                f'  {hbar(best_v, 20, c)}'
                f'  {spark_ev}'
            )
    elif best_results:
        # Fallback: baseline vs best from best_results.json per-example scores
        lines.append(f'  {c.D}{"Evaluator":<20}{"Avg Score":>10}  {"":20}{c.RST}')
        lines.append(f'  {c.D}{"─" * W}{c.RST}')

        # Aggregate per-evaluator scores from best_results per_example
        eval_scores = {}
        for ex_data in best_results.get('per_example', {}).values():
            for ev_name, ev_score in ex_data.get('scores', {}).items():
                eval_scores.setdefault(ev_name, []).append(ev_score)

        for ev in evaluators:
            if ev in eval_scores:
                avg = sum(eval_scores[ev]) / len(eval_scores[ev])
                lines.append(f'  {ev:<20}{avg:>9.3f}   {hbar(avg, 20, c)}')

    return '\n'.join(lines)


def render_what_changed(history, c):
    """Render the what-changed narrative per iteration."""
    # Only render if at least one entry has approach data
    has_narrative = any(h.get('approach') for h in history[1:])
    if not has_narrative:
        return ''

    W = 70
    lines = []
    lines.append(f'  {c.B}WHAT CHANGED{c.RST}')
    lines.append(f'  {c.D}{"─" * W}{c.RST}')

    best_score = max(h['score'] for h in history)
    for i, h in enumerate(history):
        if i == 0:
            continue
        d = h['score'] - history[i - 1]['score']
        dc = c.G if d > 0 else (c.R if d < 0 else c.Y)
        icon = trend_icon(d, i == len(history) - 1 and h['score'] == best_score, c)
        approach = (h.get('approach') or '—')[:42]
        lens = h.get('lens', '')
        lens_str = f' {c.D}[{lens}]{c.RST}' if lens else ''
        lines.append(f'  {h["version"]:<6} {icon} {dc}{d:>+.3f}{c.RST}  {approach:<42}{lens_str}')

    return '\n'.join(lines)


def render_bar_chart(history, scores, c):
    """Render horizontal bar chart of score per version."""
    best = max(scores)
    best_idx = scores.index(best)
    BAR_W = 40
    W = 70

    lines = []
    lines.append(f'  {c.B}SCORE CHART{c.RST}')
    lines.append(f'  {c.D}{"─" * W}{c.RST}')

    for i, h in enumerate(history):
        v = h['version']
        s = h['score']
        filled = round(s * BAR_W)

        if i == best_idx:
            bar_str = f'{c.G}{"█" * filled}{c.D}{"░" * (BAR_W - filled)}{c.RST}'
            score_str = f'{c.G}{c.B}{s:.3f}{c.RST}'
        elif i == 0:
            bar_str = f'{c.C}{"█" * filled}{c.D}{"░" * (BAR_W - filled)}{c.RST}'
            score_str = f'{c.C}{s:.3f}{c.RST}'
        else:
            bar_str = f'{c.G}{"█" * filled}{c.D}{"░" * (BAR_W - filled)}{c.RST}'
            score_str = f'{s:.3f}'

        lines.append(f'  {v:<10}{bar_str} {score_str}')

    # Scale
    lines.append(f'  {c.D}{" " * 10}|{" " * 9}|{" " * 9}|{" " * 9}|{" " * 9}|{c.RST}')
    lines.append(f'  {c.D}{" " * 10}0{" " * 8}.25{" " * 7}.50{" " * 7}.75{" " * 8}1.0{c.RST}')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description="Render evolution progress chart")
    parser.add_argument("--config", default=".evolver.json", help="Path to .evolver.json")
    parser.add_argument("--best-results", default=None, help="Path to best_results.json (auto-detected if not set)")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    parser.add_argument("--output", default=None, help="Write output to file instead of stdout")
    args = parser.parse_args()

    # Load config
    if not os.path.exists(args.config):
        print(f"Config not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    history = config.get('history', [])
    if not history:
        print("No history data in config.", file=sys.stderr)
        sys.exit(1)

    # Auto-detect best_results.json
    best_results = None
    br_path = args.best_results or os.path.join(os.path.dirname(args.config), 'best_results.json')
    if os.path.exists(br_path):
        with open(br_path) as f:
            best_results = json.load(f)

    # Color support
    use_color = not args.no_color and sys.stdout.isatty() and args.output is None
    c = Colors(enabled=use_color)

    scores = [h['score'] for h in history]

    # Render all sections
    sections = [
        '',
        render_header(config, history, scores, c),
        '',
        render_score_table(history, scores, c),
        '',
        render_evaluator_breakdown(history, config, best_results, c),
        '',
        render_what_changed(history, c),
        '',
        render_bar_chart(history, scores, c),
        '',
    ]

    # Filter empty sections
    output = '\n'.join(s for s in sections if s is not None)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(output + '\n')
        print(f"Chart written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make it executable and test with a mock `.evolver.json`**

Create a temporary enriched config to verify all 5 sections render:

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver
cat > /tmp/test_evolver.json << 'EOF'
{
  "project": "evolver-react-agent",
  "dataset": "react-agent-eval-v4",
  "evaluators": ["correctness", "token_efficiency", "latency"],
  "history": [
    {"version": "baseline", "score": 0.500, "passing": 10, "total": 21, "error_count": 5, "tokens": 0, "latency_ms": 876, "per_evaluator": {"correctness": 0.38, "token_efficiency": 0.72, "latency": 0.40}},
    {"version": "v001", "score": 0.620, "passing": 13, "total": 21, "error_count": 2, "tokens": 15200, "latency_ms": 420, "per_evaluator": {"correctness": 0.50, "token_efficiency": 0.75, "latency": 0.55}, "approach": "Fixed error handling in main loop", "lens": "failure_cluster"},
    {"version": "v002", "score": 0.710, "passing": 16, "total": 21, "error_count": 1, "tokens": 14800, "latency_ms": 380, "per_evaluator": {"correctness": 0.62, "token_efficiency": 0.80, "latency": 0.65}, "approach": "Added retry logic for API calls", "lens": "architecture"},
    {"version": "v003", "score": 0.750, "passing": 17, "total": 21, "error_count": 0, "tokens": 13500, "latency_ms": 350, "per_evaluator": {"correctness": 0.70, "token_efficiency": 0.82, "latency": 0.70}, "approach": "Improved prompt template", "lens": "failure_cluster"},
    {"version": "v004", "score": 0.748, "passing": 17, "total": 21, "error_count": 0, "tokens": 13200, "latency_ms": 345, "per_evaluator": {"correctness": 0.69, "token_efficiency": 0.83, "latency": 0.71}, "approach": "Refactored internals", "lens": "open"},
    {"version": "v005", "score": 0.820, "passing": 18, "total": 21, "error_count": 0, "tokens": 12100, "latency_ms": 310, "per_evaluator": {"correctness": 0.78, "token_efficiency": 0.90, "latency": 0.80}, "approach": "Added output validation", "lens": "production"},
    {"version": "v006", "score": 0.850, "passing": 19, "total": 21, "error_count": 0, "tokens": 11800, "latency_ms": 295, "per_evaluator": {"correctness": 0.81, "token_efficiency": 0.92, "latency": 0.82}, "approach": "Optimized token usage", "lens": "evolution_memory"}
  ]
}
EOF
python3 tools/evolution_chart.py --config /tmp/test_evolver.json
```

Expected: All 5 sections render with ANSI colors, no Python errors.

- [ ] **Step 3: Test backward compatibility with lean history**

```bash
python3 tools/evolution_chart.py --config playground/react-agent/.evolver.json
```

Expected: Renders header + score table + bar chart. Per-evaluator and what-changed sections are empty (no enriched data). No crash.

- [ ] **Step 4: Test `--no-color` flag**

```bash
python3 tools/evolution_chart.py --config /tmp/test_evolver.json --no-color | head -5
```

Expected: Output has no `\033[` escape sequences.

- [ ] **Step 5: Commit**

```bash
git add tools/evolution_chart.py
git commit -m "feat: add evolution_chart.py — ASCII visualization of optimization progress"
```

---

### Task 2: Enrich history entries in evolve skill

**Files:**
- Modify: `skills/evolve/SKILL.md:408-421` (Step 5 — update `.evolver.json` section)

The current history append only stores `version`, `experiment`, `score`. We need to also store `tokens`, `latency_ms`, `error_count`, `passing`, `total`, `per_evaluator`, `approach`, and `lens` — all available from `comparison.json` and `proposal.md` at this point in the loop.

- [ ] **Step 1: Update the history append in Step 5**

Replace lines 408-421 in `skills/evolve/SKILL.md`:

**Old (lines 408-421):**
```python
import json
c = json.load(open('.evolver.json'))
c['best_experiment'] = '{winner_experiment}'
c['best_score'] = {winner_score}
c['iterations'] = c['iterations'] + 1
c['history'].append({
    'version': 'v{NNN}',
    'experiment': '{winner_experiment}',
    'score': {winner_score}
})
json.dump(c, open('.evolver.json', 'w'), indent=2)
```

**New:**
```python
import json
c = json.load(open('.evolver.json'))
c['best_experiment'] = '{winner_experiment}'
c['best_score'] = {winner_score}
c['iterations'] = c['iterations'] + 1
c['history'].append({
    'version': 'v{NNN}',
    'experiment': '{winner_experiment}',
    'score': {winner_score},
    'tokens': {winner_tokens},
    'latency_ms': {winner_latency_ms},
    'error_count': {winner_errors},
    'passing': {winner_passing},
    'total': {winner_total},
    'per_evaluator': {winner_per_evaluator_dict},
    'approach': '{approach_from_proposal_md}',
    'lens': '{lens_source}'
})
json.dump(c, open('.evolver.json', 'w'), indent=2)
```

The placeholder values come from:
- `comparison.json` → `all_candidates[winner]` has `tokens`, `latency_ms`, `errors`
- `best_results.json` (re-read for winner) → `per_example` for `passing`/`total` counts and `per_evaluator` averages
- Winner's `proposal.md` → first line of `## Approach` section
- `lenses.json` → the lens `source` that was assigned to the winning proposer

- [ ] **Step 2: Add a comment block before the history append explaining where each field comes from**

Add this comment above the Python block in the skill:

```
Extract winner metrics from comparison.json for enriched history:
- `tokens`, `latency_ms`, `errors` → from `comparison.all_candidates` for the winner
- `passing`, `total` → count per_example scores ≥0.5 vs total from best_results.json (re-read for winner experiment)
- `per_evaluator` → average each evaluator's scores across per_example from best_results.json
- `approach` → first line of `## Approach` section from winner's proposal.md
- `lens` → the `source` field from the winning proposer's lens in lenses.json
```

- [ ] **Step 3: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: enrich evolution history with tokens, latency, errors, per-evaluator, approach, lens"
```

---

### Task 3: Update evolve skill final report

**Files:**
- Modify: `skills/evolve/SKILL.md:530-537` (the "When Loop Ends — Final Report" section)

- [ ] **Step 1: Replace the final report section**

Replace lines 530-537:

**Old:**
```markdown
## When Loop Ends — Final Report

- Best version and score
- Improvement over baseline (absolute and %)
- Total iterations run
- Key changes made (git log from baseline to current)
- LangSmith experiment URLs for comparison
- Suggest: `/harness:deploy` to finalize
```

**New:**
```markdown
## When Loop Ends — Final Report

Display the evolution chart:

```bash
$EVOLVER_PY $TOOLS/evolution_chart.py --config .evolver.json
```

Then add:
- LangSmith experiment URL for the best experiment (construct from project name)
- `git log --oneline` from baseline to current HEAD (key changes summary)
- Suggest: `/harness:deploy` to finalize
```

- [ ] **Step 2: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: replace evolve final report with evolution_chart.py call"
```

---

### Task 4: Update status skill

**Files:**
- Modify: `skills/status/SKILL.md` (full rewrite — it's only 36 lines)

- [ ] **Step 1: Replace the status skill**

Replace the entire `## What To Do` section with:

**Old (lines 11-37):**
```markdown
## What To Do

Read `.evolver.json` and report:

```bash
python3 -c "
import json
c = json.load(open('.evolver.json'))
print(f'Project: {c[\"project\"]}')
...
"
```

Detect stagnation: if last 3 scores are within 1% of each other, warn.
Detect regression: if current best is lower than a previous best, warn.

Print LangSmith URL for the best experiment if available.
```

**New:**
```markdown
## What To Do

### Resolve Tool Path

```bash
TOOLS="${EVOLVER_TOOLS:-$([ -d ".evolver/tools" ] && echo ".evolver/tools" || echo "$HOME/.evolver/tools")}"
EVOLVER_PY="${EVOLVER_PY:-$([ -f "$HOME/.evolver/venv/bin/python" ] && echo "$HOME/.evolver/venv/bin/python" || echo "python3")}"
```

### Display Chart

```bash
$EVOLVER_PY $TOOLS/evolution_chart.py --config .evolver.json
```

### Additional Analysis

After displaying the chart:

- Detect stagnation: if last 3 scores within 1% of each other, warn and suggest `/harness:evolve` with architect trigger.
- Detect regression: if current best is lower than a previous best, warn.
- Print LangSmith experiment URL for the best experiment if available.
```

- [ ] **Step 2: Commit**

```bash
git add skills/status/SKILL.md
git commit -m "feat: status skill now uses evolution_chart.py for rich display"
```

---

### Task 5: Update CLAUDE.md tool documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add evolution_chart.py entry to the tool list**

In the `## Running tools locally` section, after the `dataset_health.py` entry, add:

```bash
# Evolution progress chart (stdlib-only, no langsmith needed)
python tools/evolution_chart.py --config .evolver.json
```

- [ ] **Step 2: Update the Architecture section tool description**

In the `## Architecture` section under point 3 (Tools), add `evolution_chart.py` to the list of stdlib-only tools:

> `analyze_architecture.py` is stdlib-only (no langsmith dependency). [...] `evolution_chart.py` is stdlib-only (no langsmith dependency).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add evolution_chart.py to CLAUDE.md tool documentation"
```
