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
import sys


class Colors:
    def __init__(self, enabled=True):
        if enabled:
            self.G = '\033[32m'
            self.R = '\033[31m'
            self.Y = '\033[33m'
            self.C = '\033[36m'
            self.B = '\033[1m'
            self.D = '\033[90m'
            self.RST = '\033[0m'
        else:
            self.G = self.R = self.Y = self.C = ''
            self.B = self.D = self.RST = ''


def sparkline(values):
    blocks = ' ▁▂▃▄▅▆▇█'
    if not values:
        return ''
    mn, mx = min(values), max(values)
    rng = mx - mn or 1
    return ''.join(blocks[min(8, int((v - mn) / rng * 8))] for v in values)


def hbar(val, width, c):
    filled = round(val * width)
    return f'{c.G}{"█" * filled}{c.D}{"░" * (width - filled)}{c.RST}'


def fmt_tokens(t):
    if not t:
        return '—'
    if t >= 1_000_000:
        return f'{t / 1_000_000:.1f}M'
    if t >= 1000:
        return f'{t / 1000:.1f}k'
    return str(t)


def trend_icon(delta, is_best, c):
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
    base = scores[0]
    best = max(scores)
    W = 70

    lines = []
    lines.append(f'  {c.B}SCORE PROGRESSION{c.RST}')
    lines.append(f'  {c.D}{"─" * W}{c.RST}')
    has_loc = any(h.get('code_loc') for h in history)
    loc_hdr = f'{"LOC":>6}' if has_loc else ''
    lines.append(f'  {c.D}{"Version":<10}{"Score":>6}{"Δ":>8}{"vs Base":>9}{"Pass":>7}{"Err":>5}{"Tokens":>8}{"Latency":>9}{loc_hdr}{c.RST}')
    lines.append(f'  {c.D}{"─" * W}{c.RST}')

    for i, h in enumerate(history):
        v = h['version']
        s = h['score']
        passing = h.get('passing')
        total = h.get('total')
        errors = h.get('error_count', h.get('errors'))
        tokens = h.get('tokens', 0)
        latency = h.get('latency_ms', 0)

        s_str = f'{c.G}{c.B}{s:.3f}{c.RST}' if s == best else f'{s:.3f}'

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

        if passing is not None and total is not None:
            pass_str = f'{passing}/{total}'
        else:
            pass_str = '—'

        if errors is not None:
            e_str = f'{c.R}{errors}{c.RST}' if errors > 0 else f'{c.G}{errors}{c.RST}'
        else:
            e_str = '—'

        tok_str = fmt_tokens(tokens)
        lat_str = f'{latency}ms' if latency else '—'

        loc_str = ''
        if has_loc:
            loc = h.get('code_loc')
            if loc:
                base_loc = history[0].get('code_loc', 0)
                if base_loc and loc > base_loc * 1.3:
                    loc_str = f' {c.R}{loc}{c.RST}⚠'
                else:
                    loc_str = f' {loc:>5}'
            else:
                loc_str = '     —'

        lines.append(f'  {v:<10}{s_str:>6}  {d_str}  {p_str} {pass_str:>5}  {e_str:>3}  {tok_str:>6}  {lat_str:>6}{loc_str}  {icon}')

    return '\n'.join(lines)


def render_evaluator_breakdown(history, config, best_results, c):
    evaluators = config.get('evaluators', [])
    if not evaluators:
        return None

    has_per_eval = any(h.get('per_evaluator') for h in history)

    if not has_per_eval and not best_results:
        return None

    W = 70
    lines = []
    lines.append(f'  {c.B}PER-EVALUATOR BREAKDOWN{c.RST}')
    lines.append(f'  {c.D}{"─" * W}{c.RST}')

    if has_per_eval:
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
        lines.append(f'  {c.D}{"Evaluator":<20}{"Avg Score":>10}  {"":20}{c.RST}')
        lines.append(f'  {c.D}{"─" * W}{c.RST}')

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
    has_narrative = any(h.get('approach') for h in history[1:])
    if not has_narrative:
        return None

    W = 70
    best_score = max(h['score'] for h in history)
    lines = []
    lines.append(f'  {c.B}WHAT CHANGED{c.RST}')
    lines.append(f'  {c.D}{"─" * W}{c.RST}')

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

    if not os.path.exists(args.config):
        print(f"Config not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    history = config.get('history', [])
    if not history:
        print("No history data in config.", file=sys.stderr)
        sys.exit(1)

    best_results = None
    br_path = args.best_results or os.path.join(os.path.dirname(args.config) or '.', 'best_results.json')
    if os.path.exists(br_path):
        with open(br_path) as f:
            best_results = json.load(f)

    use_color = not args.no_color and sys.stdout.isatty() and args.output is None
    c = Colors(enabled=use_color)

    scores = [h['score'] for h in history]

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

    output = '\n'.join(s for s in sections if s is not None)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(output + '\n')
        print(f"Chart written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
