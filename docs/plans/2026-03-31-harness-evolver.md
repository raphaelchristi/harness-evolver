# Harness Evolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that implements Meta-Harness-style autonomous harness optimization — propose, evaluate, iterate — with full execution traces as feedback.

**Architecture:** Three-layer plugin (GSD-style): markdown skills/agents for AI orchestration, Python stdlib-only CLI tools for deterministic operations (state, eval, traces), Node.js installer for distribution via npx. The proposer subagent navigates a growing filesystem of candidates/traces/scores to produce better harnesses each iteration.

**Tech Stack:** Python 3.8+ (stdlib only), Node.js (installer), Markdown (skills/agents), JSON (data interchange)

**Spec:** `docs/specs/2026-03-31-harness-evolver-design.md`
**LangSmith Integration Spec:** `docs/specs/2026-03-31-langsmith-integration.md`

**Phases:**
- **Phase 1 (Tasks 1-11):** MVP — core loop with local traces and user-written eval
- **Phase 2 (Tasks 12-14):** LangSmith integration — auto-tracing, LLM-as-Judge evaluators, dataset sync

**LangSmith Hook Points (implemented in Phase 2, designed for in Phase 1):**
The MVP code has clean phase boundaries where LangSmith plugs in:
1. `evaluate.py` before harness loop → `setup_langsmith_tracing()` sets LANGCHAIN_TRACING_V2 env var
2. `evaluate.py` after harness loop, before user eval → `export_langsmith_traces()` pulls runs to filesystem
3. `evaluate.py` after user eval → `run_langsmith_evaluators()` adds LLM-as-Judge scores
4. `init.py` during setup → `detect_langsmith()` auto-configures if LANGSMITH_API_KEY exists
5. `state.py` during update → includes langsmith scores in summary.json (optional fields)

---

### Task 1: Repo Restructure

**Files:**
- Delete: `evolver/__init__.py`, `evolver/`, `harnesses/.gitkeep`, `harnesses/`, `tasks/.gitkeep`, `tasks/`, `traces/.gitkeep`, `traces/`
- Modify: `.gitignore`
- Create: `tools/`, `skills/`, `agents/`, `bin/`, `examples/`, `tests/`

- [ ] **Step 1: Remove old scaffold directories**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver
rm -rf evolver harnesses tasks traces
```

- [ ] **Step 2: Create new directory structure**

```bash
mkdir -p tools skills agents bin examples/classifier/tasks tests
```

- [ ] **Step 3: Update .gitignore**

Replace `.gitignore` with:

```gitignore
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
node_modules/
.env
.venv
venv/
*.log
.harness-evolver/
```

- [ ] **Step 4: Update README.md**

Replace `README.md` with:

```markdown
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
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: restructure repo to match plugin spec

Remove old scaffold (evolver/, harnesses/, tasks/, traces/).
Create plugin structure: tools/, skills/, agents/, bin/, examples/, tests/."
```

---

### Task 2: trace_logger.py

**Files:**
- Create: `tools/trace_logger.py`
- Create: `tests/test_trace_logger.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_trace_logger.py`:

```python
"""Tests for trace_logger.py — stdlib-only TraceLogger helper."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from trace_logger import TraceLogger


class TestTraceLogger(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_step_records_entry(self):
        tl = TraceLogger(self.tmpdir)
        tl.step("llm_call", {"prompt": "hello", "response": "world"})
        self.assertEqual(len(tl.steps), 1)
        self.assertEqual(tl.steps[0]["name"], "llm_call")
        self.assertEqual(tl.steps[0]["data"]["prompt"], "hello")
        self.assertIn("timestamp", tl.steps[0])

    def test_save_writes_json(self):
        tl = TraceLogger(self.tmpdir)
        tl.step("step_a", {"key": "val"})
        tl.step("step_b")
        tl.save()
        path = os.path.join(self.tmpdir, "trace.json")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "step_a")
        self.assertEqual(data[1]["name"], "step_b")
        self.assertEqual(data[1]["data"], {})

    def test_save_noop_when_no_dir(self):
        tl = TraceLogger(None)
        tl.step("ignored")
        tl.save()  # should not raise

    def test_creates_dir_if_missing(self):
        nested = os.path.join(self.tmpdir, "a", "b", "c")
        tl = TraceLogger(nested)
        tl.step("x")
        tl.save()
        self.assertTrue(os.path.exists(os.path.join(nested, "trace.json")))

    def test_steps_returns_copy(self):
        tl = TraceLogger(self.tmpdir)
        tl.step("a")
        steps = tl.steps
        steps.append({"fake": True})
        self.assertEqual(len(tl.steps), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_trace_logger.py -v 2>&1 || python3 -m unittest tests.test_trace_logger -v
```

Expected: `ModuleNotFoundError: No module named 'trace_logger'`

- [ ] **Step 3: Write implementation**

Create `tools/trace_logger.py`:

```python
"""TraceLogger — optional helper for harnesses to write structured trace records.

Usage in a harness:
    from trace_logger import TraceLogger

    trace = TraceLogger(traces_dir)
    trace.step("llm_call", {"prompt": p, "response": r, "model": "gpt-4"})
    trace.step("tool_use", {"tool": "search", "query": q, "results": results})
    trace.save()

Stdlib-only. No external dependencies.
"""

import json
import os
import time


class TraceLogger:
    def __init__(self, traces_dir):
        self.traces_dir = traces_dir
        self._steps = []
        if traces_dir:
            os.makedirs(traces_dir, exist_ok=True)

    def step(self, name, data=None):
        self._steps.append({
            "name": name,
            "timestamp": time.time(),
            "data": data if data is not None else {},
        })

    def save(self):
        if not self.traces_dir:
            return
        path = os.path.join(self.traces_dir, "trace.json")
        with open(path, "w") as f:
            json.dump(self._steps, f, indent=2)

    @property
    def steps(self):
        return list(self._steps)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_trace_logger -v
```

Expected: 5 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/trace_logger.py tests/test_trace_logger.py
git commit -m "feat: add TraceLogger helper for structured trace recording"
```

---

### Task 3: state.py

**Files:**
- Create: `tools/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_state.py`:

```python
"""Tests for state.py — manages summary.json, STATE.md, PROPOSER_HISTORY.md."""

import json
import os
import sys
import subprocess
import tempfile
import unittest

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
STATE_PY = os.path.join(TOOLS_DIR, "state.py")


def run_state(*args):
    result = subprocess.run(
        ["python3", STATE_PY] + list(args),
        capture_output=True, text=True,
    )
    return result


class TestStateInit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_init_creates_files(self):
        r = run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "summary.json")))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "STATE.md")))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "PROPOSER_HISTORY.md")))

    def test_init_summary_json_content(self):
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        self.assertEqual(data["iterations"], 0)
        self.assertEqual(data["best"]["version"], "baseline")
        self.assertAlmostEqual(data["best"]["combined_score"], 0.50)
        self.assertEqual(len(data["history"]), 1)
        self.assertIsNone(data["history"][0]["parent"])

    def test_init_state_md_contains_baseline(self):
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        with open(os.path.join(self.tmpdir, "STATE.md")) as f:
            content = f.read()
        self.assertIn("baseline", content)
        self.assertIn("0.50", content)

    def test_init_proposer_history_is_empty_with_header(self):
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        with open(os.path.join(self.tmpdir, "PROPOSER_HISTORY.md")) as f:
            content = f.read()
        self.assertIn("Proposer History", content)


class TestStateUpdate(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")
        # Create a mock scores.json
        self.scores_path = os.path.join(self.tmpdir, "test_scores.json")
        with open(self.scores_path, "w") as f:
            json.dump({"combined_score": 0.72, "accuracy": 0.72}, f)
        # Create a mock proposal.md
        self.proposal_path = os.path.join(self.tmpdir, "test_proposal.md")
        with open(self.proposal_path, "w") as f:
            f.write("Based on baseline\n\nAdded few-shot examples to improve accuracy.")

    def test_update_increments_iteration(self):
        run_state(
            "update", "--base-dir", self.tmpdir,
            "--version", "v001",
            "--scores", self.scores_path,
            "--proposal", self.proposal_path,
        )
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        self.assertEqual(data["iterations"], 1)

    def test_update_sets_best(self):
        run_state(
            "update", "--base-dir", self.tmpdir,
            "--version", "v001",
            "--scores", self.scores_path,
            "--proposal", self.proposal_path,
        )
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        self.assertEqual(data["best"]["version"], "v001")
        self.assertAlmostEqual(data["best"]["combined_score"], 0.72)

    def test_update_detects_parent_from_proposal(self):
        run_state(
            "update", "--base-dir", self.tmpdir,
            "--version", "v001",
            "--scores", self.scores_path,
            "--proposal", self.proposal_path,
        )
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        entry = [h for h in data["history"] if h["version"] == "v001"][0]
        self.assertEqual(entry["parent"], "baseline")

    def test_update_fallback_parent_to_best(self):
        # Proposal without "Based on" declaration
        with open(self.proposal_path, "w") as f:
            f.write("Improved the prompt template.")
        run_state(
            "update", "--base-dir", self.tmpdir,
            "--version", "v001",
            "--scores", self.scores_path,
            "--proposal", self.proposal_path,
        )
        with open(os.path.join(self.tmpdir, "summary.json")) as f:
            data = json.load(f)
        entry = [h for h in data["history"] if h["version"] == "v001"][0]
        self.assertEqual(entry["parent"], "baseline")  # best at that point

    def test_update_appends_proposer_history(self):
        run_state(
            "update", "--base-dir", self.tmpdir,
            "--version", "v001",
            "--scores", self.scores_path,
            "--proposal", self.proposal_path,
        )
        with open(os.path.join(self.tmpdir, "PROPOSER_HISTORY.md")) as f:
            content = f.read()
        self.assertIn("v001", content)
        self.assertIn("0.72", content)

    def test_update_marks_regression(self):
        # First update: good score
        run_state(
            "update", "--base-dir", self.tmpdir,
            "--version", "v001",
            "--scores", self.scores_path,
            "--proposal", self.proposal_path,
        )
        # Second update: bad score
        bad_scores = os.path.join(self.tmpdir, "bad_scores.json")
        with open(bad_scores, "w") as f:
            json.dump({"combined_score": 0.30}, f)
        bad_proposal = os.path.join(self.tmpdir, "bad_proposal.md")
        with open(bad_proposal, "w") as f:
            f.write("Based on v001\n\nChanged prompt structure.")
        run_state(
            "update", "--base-dir", self.tmpdir,
            "--version", "v002",
            "--scores", bad_scores,
            "--proposal", bad_proposal,
        )
        with open(os.path.join(self.tmpdir, "PROPOSER_HISTORY.md")) as f:
            content = f.read()
        self.assertIn("REGRESSION", content)

    def test_update_refreshes_state_md(self):
        run_state(
            "update", "--base-dir", self.tmpdir,
            "--version", "v001",
            "--scores", self.scores_path,
            "--proposal", self.proposal_path,
        )
        with open(os.path.join(self.tmpdir, "STATE.md")) as f:
            content = f.read()
        self.assertIn("v001", content)
        self.assertIn("0.72", content)


class TestStateShow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        run_state("init", "--base-dir", self.tmpdir, "--baseline-score", "0.50")

    def test_show_outputs_status(self):
        r = run_state("show", "--base-dir", self.tmpdir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("baseline", r.stdout)
        self.assertIn("0.50", r.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_state -v
```

Expected: `FileNotFoundError` or similar — `state.py` doesn't exist yet.

- [ ] **Step 3: Write implementation**

Create `tools/state.py`:

```python
#!/usr/bin/env python3
"""State manager for Harness Evolver.

Commands:
    init   --base-dir DIR --baseline-score FLOAT
    update --base-dir DIR --version VER --scores PATH --proposal PATH
    show   --base-dir DIR

Manages: summary.json (source of truth), STATE.md (human view), PROPOSER_HISTORY.md (log).
Stdlib-only. No external dependencies.
"""

import argparse
import json
import os
import re
import sys


def _read_json(path):
    with open(path) as f:
        return json.load(f)


def _write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _read_text(path):
    with open(path) as f:
        return f.read()


def _write_text(path, text):
    with open(path, "w") as f:
        f.write(text)


def _summary_path(base_dir):
    return os.path.join(base_dir, "summary.json")


def _state_md_path(base_dir):
    return os.path.join(base_dir, "STATE.md")


def _history_path(base_dir):
    return os.path.join(base_dir, "PROPOSER_HISTORY.md")


def _detect_parent(proposal_text, current_best):
    """Parse 'Based on vXXX' or 'Based on baseline' from proposal text."""
    match = re.search(r"[Bb]ased on (v\d+|baseline)", proposal_text)
    if match:
        return match.group(1)
    return current_best


def _render_state_md(summary):
    """Generate STATE.md from summary.json data."""
    lines = ["# Harness Evolver Status", ""]
    best = summary["best"]
    worst = summary["worst"]
    lines.append(f"**Iterations:** {summary['iterations']}")
    lines.append(f"**Best:** {best['version']} ({best['combined_score']:.2f})")
    lines.append(f"**Worst:** {worst['version']} ({worst['combined_score']:.2f})")
    if summary["history"]:
        last = summary["history"][-1]
        lines.append(f"**Latest:** {last['version']} ({last['combined_score']:.2f})")
    lines.append("")
    lines.append("## History")
    lines.append("")
    lines.append("| Version | Score | Parent | Delta |")
    lines.append("|---------|-------|--------|-------|")
    prev_score = None
    for entry in summary["history"]:
        v = entry["version"]
        s = entry["combined_score"]
        p = entry["parent"] or "-"
        if prev_score is not None and v != "baseline":
            delta = s - prev_score
            if delta < -0.01:
                delta_str = f"{delta:+.2f} REGRESSION"
            elif delta > 0.01:
                delta_str = f"{delta:+.2f}"
            else:
                delta_str = f"{delta:+.2f} (stagnant)"
        else:
            delta_str = "-"
        lines.append(f"| {v} | {s:.2f} | {p} | {delta_str} |")
        prev_score = s
    return "\n".join(lines) + "\n"


def cmd_init(args):
    base_dir = args.base_dir
    score = args.baseline_score
    os.makedirs(base_dir, exist_ok=True)

    summary = {
        "iterations": 0,
        "best": {"version": "baseline", "combined_score": score},
        "worst": {"version": "baseline", "combined_score": score},
        "history": [
            {"version": "baseline", "combined_score": score, "parent": None}
        ],
    }
    _write_json(_summary_path(base_dir), summary)
    _write_text(_state_md_path(base_dir), _render_state_md(summary))
    _write_text(_history_path(base_dir), "# Proposer History\n")


def cmd_update(args):
    base_dir = args.base_dir
    version = args.version
    scores = _read_json(args.scores)
    proposal_text = _read_text(args.proposal) if args.proposal else ""

    summary = _read_json(_summary_path(base_dir))
    combined = scores.get("combined_score", 0.0)
    parent = _detect_parent(proposal_text, summary["best"]["version"])

    entry = {
        "version": version,
        "combined_score": combined,
        "parent": parent,
    }
    summary["history"].append(entry)
    summary["iterations"] = len(summary["history"]) - 1  # exclude baseline

    # Update best/worst
    non_baseline = [h for h in summary["history"] if h["version"] != "baseline"]
    if non_baseline:
        best_entry = max(non_baseline, key=lambda h: h["combined_score"])
        worst_entry = min(non_baseline, key=lambda h: h["combined_score"])
        summary["best"] = {
            "version": best_entry["version"],
            "combined_score": best_entry["combined_score"],
        }
        summary["worst"] = {
            "version": worst_entry["version"],
            "combined_score": worst_entry["combined_score"],
        }

    _write_json(_summary_path(base_dir), summary)
    _write_text(_state_md_path(base_dir), _render_state_md(summary))

    # Append to PROPOSER_HISTORY.md
    parent_score = None
    for h in summary["history"]:
        if h["version"] == parent:
            parent_score = h["combined_score"]
            break

    is_regression = parent_score is not None and combined < parent_score - 0.01
    regression_tag = " <- REGRESSION" if is_regression else ""

    # Extract first non-empty, non-"Based on" line as summary
    proposal_lines = proposal_text.strip().split("\n")
    summary_line = ""
    for line in proposal_lines:
        stripped = line.strip()
        if stripped and not re.match(r"^[Bb]ased on", stripped):
            summary_line = stripped
            break

    history_entry = f"\n## {version} (score: {combined:.2f}){regression_tag}\n{summary_line}\n"
    history_path = _history_path(base_dir)
    with open(history_path, "a") as f:
        f.write(history_entry)


def cmd_show(args):
    base_dir = args.base_dir
    summary = _read_json(_summary_path(base_dir))
    best = summary["best"]
    worst = summary["worst"]

    print(f"Harness Evolver — Iteration {summary['iterations']}")
    print(f"Best:  {best['version']}  score: {best['combined_score']:.2f}")
    print(f"Worst: {worst['version']}  score: {worst['combined_score']:.2f}")
    print()
    for entry in summary["history"]:
        v = entry["version"]
        s = entry["combined_score"]
        bar_len = int(s * 30)
        bar = "\u2588" * bar_len
        print(f"  {v:>10}: {s:.2f} {bar}")


def main():
    parser = argparse.ArgumentParser(description="Harness Evolver state manager")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init")
    p_init.add_argument("--base-dir", required=True)
    p_init.add_argument("--baseline-score", type=float, required=True)

    p_update = sub.add_parser("update")
    p_update.add_argument("--base-dir", required=True)
    p_update.add_argument("--version", required=True)
    p_update.add_argument("--scores", required=True)
    p_update.add_argument("--proposal", default=None)

    p_show = sub.add_parser("show")
    p_show.add_argument("--base-dir", required=True)

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "show":
        cmd_show(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_state -v
```

Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/state.py tests/test_state.py
git commit -m "feat: add state manager (summary.json, STATE.md, PROPOSER_HISTORY.md)"
```

---

### Task 4: Example Classifier

**Files:**
- Create: `examples/classifier/tasks/task_001.json` through `task_010.json`
- Create: `examples/classifier/harness.py`
- Create: `examples/classifier/eval.py`
- Create: `examples/classifier/config.json`
- Create: `examples/classifier/README.md`

- [ ] **Step 1: Create 10 task files**

Create `examples/classifier/tasks/task_001.json`:
```json
{"id": "task_001", "input": "The patient presents with persistent cough, fever of 38.5C, and shortness of breath", "expected": "respiratory", "metadata": {"difficulty": "easy"}}
```

Create `examples/classifier/tasks/task_002.json`:
```json
{"id": "task_002", "input": "Patient reports severe chest pain radiating to left arm with elevated blood pressure", "expected": "cardiac", "metadata": {"difficulty": "easy"}}
```

Create `examples/classifier/tasks/task_003.json`:
```json
{"id": "task_003", "input": "Recurring nausea, vomiting after meals, and sharp abdominal pain in lower right quadrant", "expected": "gastrointestinal", "metadata": {"difficulty": "easy"}}
```

Create `examples/classifier/tasks/task_004.json`:
```json
{"id": "task_004", "input": "Patient complains of severe headache, dizziness, and intermittent numbness in left hand", "expected": "neurological", "metadata": {"difficulty": "easy"}}
```

Create `examples/classifier/tasks/task_005.json`:
```json
{"id": "task_005", "input": "Chronic lower back pain with stiffness, worsening after prolonged sitting, mild joint swelling", "expected": "musculoskeletal", "metadata": {"difficulty": "easy"}}
```

Create `examples/classifier/tasks/task_006.json`:
```json
{"id": "task_006", "input": "Red itchy rash spreading across torso with small raised bumps and occasional skin peeling", "expected": "dermatological", "metadata": {"difficulty": "easy"}}
```

Create `examples/classifier/tasks/task_007.json`:
```json
{"id": "task_007", "input": "Patient has a mild cough and reports feeling dizzy with occasional heart palpitations", "expected": "cardiac", "metadata": {"difficulty": "hard"}}
```

Create `examples/classifier/tasks/task_008.json`:
```json
{"id": "task_008", "input": "Fatigue and muscle weakness with tingling in extremities and difficulty concentrating", "expected": "neurological", "metadata": {"difficulty": "hard"}}
```

Create `examples/classifier/tasks/task_009.json`:
```json
{"id": "task_009", "input": "Stomach cramps with alternating diarrhea and constipation, bloating after eating", "expected": "gastrointestinal", "metadata": {"difficulty": "medium"}}
```

Create `examples/classifier/tasks/task_010.json`:
```json
{"id": "task_010", "input": "Joint pain in fingers and wrists with morning stiffness lasting over an hour and skin rash on knuckles", "expected": "musculoskeletal", "metadata": {"difficulty": "hard"}}
```

- [ ] **Step 2: Write harness.py with mock mode**

Create `examples/classifier/harness.py`:

```python
#!/usr/bin/env python3
"""Medical symptom classifier — deliberately naive, with room for improvement.

Mock mode (default): keyword matching, ~40% accuracy.
LLM mode: calls API, ~50-60% accuracy (no few-shot, no retry, no structured output).

The evolver should discover improvements like few-shot examples, structured output,
retry logic, better prompt templates, etc.
"""

import argparse
import json
import os
import sys

CATEGORIES = [
    "respiratory", "cardiac", "gastrointestinal",
    "neurological", "musculoskeletal", "dermatological",
]

KEYWORDS = {
    "respiratory": ["cough", "breath", "lung", "wheeze", "sputum"],
    "cardiac": ["chest pain", "heart", "blood pressure", "palpitation"],
    "gastrointestinal": ["nausea", "vomit", "abdominal", "diarrhea", "stomach"],
    "neurological": ["headache", "dizz", "numb", "seizure", "confusion"],
    "musculoskeletal": ["joint", "back pain", "muscle", "stiffness", "swelling"],
    "dermatological": ["rash", "itch", "skin", "lesion", "bump"],
}


def classify_mock(text):
    """Keyword-based classifier. Deliberately bad — the evolver should improve this."""
    text_lower = text.lower()
    scores = {}
    for category, words in KEYWORDS.items():
        scores[category] = sum(1 for w in words if w in text_lower)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "unknown"
    return best


def classify_llm(text, config):
    """LLM-based classifier. Naive single-shot prompt, no retry."""
    import urllib.request

    api_key = config.get("api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
    model = config.get("model", "claude-haiku-4-5-20251001")

    prompt = (
        f"Classify the following medical symptom description into exactly one category.\n"
        f"Categories: {', '.join(CATEGORIES)}\n"
        f"Reply with ONLY the category name, nothing else.\n\n"
        f"{text}"
    )

    body = json.dumps({
        "model": model,
        "max_tokens": 50,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    answer = result["content"][0]["text"].strip().lower()
    for cat in CATEGORIES:
        if cat in answer:
            return cat
    return answer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--traces-dir", default=None)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    task = json.load(open(args.input))
    config = json.load(open(args.config)) if args.config and os.path.exists(args.config) else {}
    use_mock = config.get("mock", True)

    if use_mock:
        result = classify_mock(task["input"])
    else:
        result = classify_llm(task["input"], config)

    output = {"id": task["id"], "output": result}

    # Write optional traces
    if args.traces_dir:
        os.makedirs(args.traces_dir, exist_ok=True)
        trace = {
            "mode": "mock" if use_mock else "llm",
            "input_text": task["input"],
            "output_category": result,
            "config": {k: v for k, v in config.items() if k != "api_key"},
        }
        with open(os.path.join(args.traces_dir, "trace.json"), "w") as f:
            json.dump([trace], f, indent=2)

    json.dump(output, open(args.output, "w"), indent=2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Write eval.py**

Create `examples/classifier/eval.py`:

```python
#!/usr/bin/env python3
"""Exact match accuracy scorer for the classifier example."""

import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--tasks-dir", required=True)
    parser.add_argument("--scores", required=True)
    args = parser.parse_args()

    correct = 0
    total = 0
    per_task = {}

    for fname in sorted(os.listdir(args.tasks_dir)):
        if not fname.endswith(".json"):
            continue
        task_path = os.path.join(args.tasks_dir, fname)
        task = json.load(open(task_path))
        task_id = task["id"]

        result_path = os.path.join(args.results_dir, fname)
        if not os.path.exists(result_path):
            per_task[task_id] = {"score": 0.0, "error": "no output file"}
            total += 1
            continue

        result = json.load(open(result_path))
        expected = task["expected"].lower().strip()
        actual = result.get("output", "").lower().strip()
        match = actual == expected

        per_task[task_id] = {
            "score": 1.0 if match else 0.0,
            "expected": expected,
            "actual": actual,
        }
        correct += int(match)
        total += 1

    accuracy = correct / total if total > 0 else 0.0
    scores = {
        "combined_score": accuracy,
        "accuracy": accuracy,
        "total_tasks": total,
        "correct": correct,
        "per_task": per_task,
    }
    json.dump(scores, open(args.scores, "w"), indent=2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write config.json and README.md**

Create `examples/classifier/config.json`:
```json
{
  "mock": true
}
```

Create `examples/classifier/README.md`:
```markdown
# Classifier Example

Medical symptom classifier — deliberately naive, designed to be improved by the evolver.

## Quick Start (Mock Mode — No API Key)

```bash
/harness-evolve-init --harness harness.py --eval eval.py --tasks tasks/
/harness-evolve --iterations 5
```

## With LLM

Edit `config.json`:
```json
{
  "mock": false,
  "api_key": "sk-ant-...",
  "model": "claude-haiku-4-5-20251001"
}
```

## Categories

respiratory, cardiac, gastrointestinal, neurological, musculoskeletal, dermatological

## Expected Improvement Curve

- Mock: ~40% → ~70-80% (better keywords, regex, fallback logic)
- LLM: ~50-60% → ~85-95% (few-shot, structured output, retry)
```

- [ ] **Step 5: Smoke test the example manually**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver
TMPDIR=$(mktemp -d)
python3 examples/classifier/harness.py \
    --input examples/classifier/tasks/task_001.json \
    --output "$TMPDIR/result.json" \
    --traces-dir "$TMPDIR/traces" \
    --config examples/classifier/config.json
cat "$TMPDIR/result.json"
# Expected: {"id": "task_001", "output": "respiratory"}
```

- [ ] **Step 6: Commit**

```bash
git add examples/
git commit -m "feat: add classifier example with mock mode (10 tasks)"
```

---

### Task 5: evaluate.py

**Files:**
- Create: `tools/evaluate.py`
- Create: `tests/test_evaluate.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_evaluate.py`:

```python
"""Tests for evaluate.py — evaluation orchestrator."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
EVALUATE_PY = os.path.join(TOOLS_DIR, "evaluate.py")
EXAMPLE_DIR = os.path.join(REPO_ROOT, "examples", "classifier")


def run_evaluate(*args):
    result = subprocess.run(
        ["python3", EVALUATE_PY] + list(args),
        capture_output=True, text=True, timeout=120,
    )
    return result


class TestValidate(unittest.TestCase):
    def test_validate_passes_for_valid_harness(self):
        r = run_evaluate(
            "validate",
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--config", os.path.join(EXAMPLE_DIR, "config.json"),
        )
        self.assertEqual(r.returncode, 0, f"stdout: {r.stdout}\nstderr: {r.stderr}")

    def test_validate_fails_for_missing_harness(self):
        r = run_evaluate("validate", "--harness", "/nonexistent/harness.py")
        self.assertNotEqual(r.returncode, 0)

    def test_validate_fails_for_broken_harness(self):
        tmpdir = tempfile.mkdtemp()
        broken = os.path.join(tmpdir, "broken.py")
        with open(broken, "w") as f:
            f.write("import sys; sys.exit(1)\n")
        r = run_evaluate("validate", "--harness", broken)
        self.assertNotEqual(r.returncode, 0)


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.traces_dir = os.path.join(self.tmpdir, "traces")
        self.scores_path = os.path.join(self.tmpdir, "scores.json")

    def test_run_produces_scores(self):
        r = run_evaluate(
            "run",
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tasks-dir", os.path.join(EXAMPLE_DIR, "tasks"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--traces-dir", self.traces_dir,
            "--scores", self.scores_path,
            "--timeout", "30",
        )
        self.assertEqual(r.returncode, 0, f"stdout: {r.stdout}\nstderr: {r.stderr}")
        self.assertTrue(os.path.exists(self.scores_path))
        scores = json.load(open(self.scores_path))
        self.assertIn("combined_score", scores)
        self.assertIn("per_task", scores)
        self.assertGreater(scores["combined_score"], 0.0)

    def test_run_creates_per_task_traces(self):
        run_evaluate(
            "run",
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tasks-dir", os.path.join(EXAMPLE_DIR, "tasks"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--traces-dir", self.traces_dir,
            "--scores", self.scores_path,
            "--timeout", "30",
        )
        # Should have stdout.log, stderr.log, timing.json
        self.assertTrue(os.path.exists(os.path.join(self.traces_dir, "stdout.log")))
        self.assertTrue(os.path.exists(os.path.join(self.traces_dir, "stderr.log")))
        self.assertTrue(os.path.exists(os.path.join(self.traces_dir, "timing.json")))
        # Should have per-task directories
        task_trace_dir = os.path.join(self.traces_dir, "task_001")
        self.assertTrue(os.path.isdir(task_trace_dir))
        self.assertTrue(os.path.exists(os.path.join(task_trace_dir, "input.json")))
        self.assertTrue(os.path.exists(os.path.join(task_trace_dir, "output.json")))

    def test_run_handles_harness_crash(self):
        broken = os.path.join(self.tmpdir, "broken.py")
        with open(broken, "w") as f:
            f.write("import sys; sys.exit(1)\n")
        r = run_evaluate(
            "run",
            "--harness", broken,
            "--tasks-dir", os.path.join(EXAMPLE_DIR, "tasks"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--traces-dir", self.traces_dir,
            "--scores", self.scores_path,
            "--timeout", "30",
        )
        # Should still complete (crash → score 0.0 per task)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        scores = json.load(open(self.scores_path))
        self.assertEqual(scores["combined_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_evaluate -v
```

Expected: `FileNotFoundError` — `evaluate.py` doesn't exist yet.

- [ ] **Step 3: Write implementation**

Create `tools/evaluate.py`:

```python
#!/usr/bin/env python3
"""Evaluation orchestrator for Harness Evolver.

Commands:
    validate --harness PATH [--config PATH]
    run      --harness PATH --tasks-dir PATH --eval PATH --traces-dir PATH --scores PATH
             [--config PATH] [--timeout SECONDS]

Runs harness per task, captures traces (stdout/stderr/timing), then calls user's eval script.
Stdlib-only. No external dependencies.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time


def _run_harness_on_task(harness, config, task_input_path, output_path, task_traces_dir, timeout):
    """Run the harness on a single task. Returns (success, elapsed_ms)."""
    cmd = ["python3", harness, "--input", task_input_path, "--output", output_path]
    if task_traces_dir:
        extra_dir = os.path.join(task_traces_dir, "extra")
        os.makedirs(extra_dir, exist_ok=True)
        cmd.extend(["--traces-dir", extra_dir])
    if config and os.path.exists(config):
        cmd.extend(["--config", config])

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        elapsed_ms = (time.time() - start) * 1000
        return result.returncode == 0, elapsed_ms, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.time() - start) * 1000
        return False, elapsed_ms, "", f"TIMEOUT after {timeout}s"
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        return False, elapsed_ms, "", str(e)


def cmd_validate(args):
    """Run harness with a dummy task to verify the interface works."""
    harness = args.harness
    config = getattr(args, "config", None)

    if not os.path.exists(harness):
        print(f"FAIL: harness not found: {harness}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        dummy_task = {"id": "validation", "input": "test input for validation", "metadata": {}}
        input_path = os.path.join(tmpdir, "input.json")
        output_path = os.path.join(tmpdir, "output.json")
        with open(input_path, "w") as f:
            json.dump(dummy_task, f)

        success, elapsed, stdout, stderr = _run_harness_on_task(
            harness, config, input_path, output_path, None, timeout=30,
        )

        if not success:
            print(f"FAIL: harness exited with error.\nstderr: {stderr}", file=sys.stderr)
            sys.exit(1)

        if not os.path.exists(output_path):
            print("FAIL: harness did not create output file.", file=sys.stderr)
            sys.exit(1)

        try:
            with open(output_path) as f:
                output = json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"FAIL: output is not valid JSON: {e}", file=sys.stderr)
            sys.exit(1)

        if "id" not in output or "output" not in output:
            print(f"FAIL: output missing 'id' or 'output' fields. Got: {output}", file=sys.stderr)
            sys.exit(1)

        print(f"OK: harness validated in {elapsed:.0f}ms. Output: {output}")


def cmd_run(args):
    """Run full evaluation: harness on each task, then user's eval script."""
    harness = args.harness
    config = getattr(args, "config", None)
    tasks_dir = args.tasks_dir
    eval_script = args.eval
    traces_dir = args.traces_dir
    scores_path = args.scores
    timeout = args.timeout

    os.makedirs(traces_dir, exist_ok=True)

    # Collect task files
    task_files = sorted(f for f in os.listdir(tasks_dir) if f.endswith(".json"))
    if not task_files:
        print(f"FAIL: no .json task files in {tasks_dir}", file=sys.stderr)
        sys.exit(1)

    all_stdout = []
    all_stderr = []
    timing = {"per_task": {}}
    results_dir = tempfile.mkdtemp()

    for task_file in task_files:
        task_path = os.path.join(tasks_dir, task_file)
        with open(task_path) as f:
            task = json.load(f)
        task_id = task["id"]

        # Create input without "expected" field
        task_input = {k: v for k, v in task.items() if k != "expected"}

        # Per-task traces directory
        task_traces_dir = os.path.join(traces_dir, task_id)
        os.makedirs(task_traces_dir, exist_ok=True)

        # Write sanitized input
        input_path = os.path.join(task_traces_dir, "input.json")
        with open(input_path, "w") as f:
            json.dump(task_input, f, indent=2)

        # Output path (also saved in results_dir for eval script)
        output_path = os.path.join(results_dir, task_file)

        success, elapsed_ms, stdout, stderr = _run_harness_on_task(
            harness, config, input_path, output_path, task_traces_dir, timeout,
        )

        # Save per-task output to traces
        if os.path.exists(output_path):
            import shutil
            shutil.copy2(output_path, os.path.join(task_traces_dir, "output.json"))
        else:
            # Write empty output for crashed tasks so eval can detect missing output
            with open(os.path.join(task_traces_dir, "output.json"), "w") as f:
                json.dump({"id": task_id, "output": "", "error": "harness failed"}, f)

        timing["per_task"][task_id] = round(elapsed_ms, 1)
        all_stdout.append(f"--- {task_id} ---\n{stdout}")
        all_stderr.append(f"--- {task_id} ---\n{stderr}")

    # Write aggregate traces
    timing["total_ms"] = round(sum(timing["per_task"].values()), 1)
    with open(os.path.join(traces_dir, "timing.json"), "w") as f:
        json.dump(timing, f, indent=2)
    with open(os.path.join(traces_dir, "stdout.log"), "w") as f:
        f.write("\n".join(all_stdout))
    with open(os.path.join(traces_dir, "stderr.log"), "w") as f:
        f.write("\n".join(all_stderr))

    # Run user's eval script
    eval_cmd = [
        "python3", eval_script,
        "--results-dir", results_dir,
        "--tasks-dir", tasks_dir,
        "--scores", scores_path,
    ]
    result = subprocess.run(eval_cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"FAIL: eval script failed.\nstderr: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Print summary
    if os.path.exists(scores_path):
        scores = json.load(open(scores_path))
        print(f"Evaluation complete. combined_score: {scores.get('combined_score', 'N/A')}")
    else:
        print("WARNING: eval script did not produce scores file.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Harness Evolver evaluation orchestrator")
    sub = parser.add_subparsers(dest="command")

    p_val = sub.add_parser("validate")
    p_val.add_argument("--harness", required=True)
    p_val.add_argument("--config", default=None)

    p_run = sub.add_parser("run")
    p_run.add_argument("--harness", required=True)
    p_run.add_argument("--config", default=None)
    p_run.add_argument("--tasks-dir", required=True)
    p_run.add_argument("--eval", required=True)
    p_run.add_argument("--traces-dir", required=True)
    p_run.add_argument("--scores", required=True)
    p_run.add_argument("--timeout", type=int, default=60)

    args = parser.parse_args()
    if args.command == "validate":
        cmd_validate(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_evaluate -v
```

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/evaluate.py tests/test_evaluate.py
git commit -m "feat: add evaluation orchestrator with trace capture"
```

---

### Task 6: init.py

**Files:**
- Create: `tools/init.py`
- Create: `tests/test_init.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_init.py`:

```python
"""Tests for init.py — project initialization."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
INIT_PY = os.path.join(TOOLS_DIR, "init.py")
EXAMPLE_DIR = os.path.join(REPO_ROOT, "examples", "classifier")


def run_init(*args):
    result = subprocess.run(
        ["python3", INIT_PY] + list(args),
        capture_output=True, text=True, timeout=120,
    )
    return result


class TestInit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.tmpdir, ".harness-evolver")

    def test_init_creates_structure(self):
        r = run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        self.assertEqual(r.returncode, 0, f"stdout: {r.stdout}\nstderr: {r.stderr}")

        # Check directory structure
        self.assertTrue(os.path.isdir(os.path.join(self.base_dir, "baseline")))
        self.assertTrue(os.path.isdir(os.path.join(self.base_dir, "eval", "tasks")))
        self.assertTrue(os.path.isdir(os.path.join(self.base_dir, "harnesses")))

    def test_init_copies_baseline(self):
        run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        self.assertTrue(os.path.exists(os.path.join(self.base_dir, "baseline", "harness.py")))
        self.assertTrue(os.path.exists(os.path.join(self.base_dir, "baseline", "config.json")))

    def test_init_copies_eval_and_tasks(self):
        run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        self.assertTrue(os.path.exists(os.path.join(self.base_dir, "eval", "eval.py")))
        tasks = os.listdir(os.path.join(self.base_dir, "eval", "tasks"))
        self.assertGreater(len(tasks), 0)

    def test_init_creates_config_json(self):
        run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        config_path = os.path.join(self.base_dir, "config.json")
        self.assertTrue(os.path.exists(config_path))
        config = json.load(open(config_path))
        self.assertIn("harness", config)
        self.assertIn("eval", config)
        self.assertIn("evolution", config)

    def test_init_creates_summary_with_baseline_score(self):
        run_init(
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )
        summary_path = os.path.join(self.base_dir, "summary.json")
        self.assertTrue(os.path.exists(summary_path))
        summary = json.load(open(summary_path))
        self.assertEqual(summary["best"]["version"], "baseline")
        self.assertGreater(summary["best"]["combined_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_init -v
```

Expected: `FileNotFoundError` — `init.py` doesn't exist.

- [ ] **Step 3: Write implementation**

Create `tools/init.py`:

```python
#!/usr/bin/env python3
"""Project initializer for Harness Evolver.

Usage:
    init.py --harness PATH --eval PATH --tasks PATH --base-dir PATH
            [--harness-config PATH] [--tools-dir PATH]

Creates the .harness-evolver/ directory structure, copies baseline files,
runs validation, evaluates the baseline, and initializes state.
Stdlib-only. No external dependencies.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Initialize Harness Evolver project")
    parser.add_argument("--harness", required=True, help="Path to harness script")
    parser.add_argument("--eval", required=True, help="Path to eval script")
    parser.add_argument("--tasks", required=True, help="Path to tasks directory")
    parser.add_argument("--base-dir", required=True, help="Path for .harness-evolver/")
    parser.add_argument("--harness-config", default=None, help="Path to harness config.json")
    parser.add_argument("--tools-dir", default=None, help="Path to tools directory (for eval/state)")
    args = parser.parse_args()

    base = args.base_dir
    tools = args.tools_dir or os.path.join(os.path.dirname(__file__))

    evaluate_py = os.path.join(tools, "evaluate.py")
    state_py = os.path.join(tools, "state.py")

    # 1. Create directory structure
    for d in ["baseline", "eval/tasks", "harnesses"]:
        os.makedirs(os.path.join(base, d), exist_ok=True)

    # 2. Copy baseline harness
    shutil.copy2(args.harness, os.path.join(base, "baseline", "harness.py"))
    if args.harness_config and os.path.exists(args.harness_config):
        shutil.copy2(args.harness_config, os.path.join(base, "baseline", "config.json"))

    # 3. Copy eval script and tasks
    shutil.copy2(args.eval, os.path.join(base, "eval", "eval.py"))
    for f in os.listdir(args.tasks):
        src = os.path.join(args.tasks, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(base, "eval", "tasks", f))

    # 4. Generate config.json
    harness_name = os.path.basename(args.harness)
    eval_name = os.path.basename(args.eval)
    config = {
        "version": "0.1.0",
        "harness": {
            "command": f"python3 {harness_name}",
            "args": [
                "--input", "{input}",
                "--output", "{output}",
                "--traces-dir", "{traces_dir}",
                "--config", "{config}",
            ],
            "timeout_per_task_sec": 60,
        },
        "eval": {
            "command": f"python3 {eval_name}",
            "args": [
                "--results-dir", "{results_dir}",
                "--tasks-dir", "{tasks_dir}",
                "--scores", "{scores}",
            ],
        },
        "evolution": {
            "max_iterations": 10,
            "candidates_per_iter": 1,
            "stagnation_limit": 3,
            "stagnation_threshold": 0.01,
            "target_score": None,
        },
        "paths": {
            "baseline": "baseline/",
            "eval_tasks": "eval/tasks/",
            "eval_script": "eval/eval.py",
            "harnesses": "harnesses/",
        },
    }
    with open(os.path.join(base, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    # 5. Validate baseline harness
    print("Validating baseline harness...")
    val_args = ["python3", evaluate_py, "validate",
                "--harness", os.path.join(base, "baseline", "harness.py")]
    config_path = os.path.join(base, "baseline", "config.json")
    if os.path.exists(config_path):
        val_args.extend(["--config", config_path])
    r = subprocess.run(val_args, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL: baseline harness validation failed.\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    print(r.stdout.strip())

    # 6. Evaluate baseline
    print("Evaluating baseline harness...")
    import tempfile
    baseline_traces = tempfile.mkdtemp()
    baseline_scores = os.path.join(base, "baseline_scores.json")
    eval_args = [
        "python3", evaluate_py, "run",
        "--harness", os.path.join(base, "baseline", "harness.py"),
        "--tasks-dir", os.path.join(base, "eval", "tasks"),
        "--eval", os.path.join(base, "eval", "eval.py"),
        "--traces-dir", baseline_traces,
        "--scores", baseline_scores,
        "--timeout", "60",
    ]
    if os.path.exists(config_path):
        eval_args.extend(["--config", config_path])
    r = subprocess.run(eval_args, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"WARNING: baseline evaluation failed. Using score 0.0.\n{r.stderr}", file=sys.stderr)
        baseline_score = 0.0
    else:
        print(r.stdout.strip())
        scores = json.load(open(baseline_scores))
        baseline_score = scores.get("combined_score", 0.0)

    # Cleanup temp files
    if os.path.exists(baseline_scores):
        os.remove(baseline_scores)

    # 7. Initialize state with baseline score
    print(f"Baseline score: {baseline_score:.2f}")
    r = subprocess.run(
        ["python3", state_py, "init",
         "--base-dir", base,
         "--baseline-score", str(baseline_score)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"FAIL: state init failed.\n{r.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"\nInitialized .harness-evolver/ at {base}")
    print(f"Baseline score: {baseline_score:.2f}")
    print("Run /harness-evolve to start the optimization loop.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_init -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/init.py tests/test_init.py
git commit -m "feat: add project initializer (copies baseline, runs eval, inits state)"
```

---

### Task 7: Integration Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_integration.py`:

```python
"""Integration test: init → evaluate → state update — full pipeline with mock classifier."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
EXAMPLE_DIR = os.path.join(REPO_ROOT, "examples", "classifier")


class TestFullPipeline(unittest.TestCase):
    def setUp(self):
        self.project_dir = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.project_dir, ".harness-evolver")

    def _run(self, *cmd):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, f"Command failed: {' '.join(cmd)}\nstderr: {r.stderr}")
        return r

    def test_init_evaluate_update_cycle(self):
        """Simulates one full cycle: init, create v001, evaluate, update state."""

        # 1. Init
        self._run(
            "python3", os.path.join(TOOLS_DIR, "init.py"),
            "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
            "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
            "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
            "--base-dir", self.base_dir,
            "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
            "--tools-dir", TOOLS_DIR,
        )

        # Verify init created everything
        summary = json.load(open(os.path.join(self.base_dir, "summary.json")))
        self.assertEqual(summary["iterations"], 0)
        baseline_score = summary["best"]["combined_score"]
        self.assertGreater(baseline_score, 0.0)

        # 2. Create v001 directory (simulating what proposer would do)
        v001_dir = os.path.join(self.base_dir, "harnesses", "v001")
        os.makedirs(v001_dir, exist_ok=True)
        shutil.copy2(
            os.path.join(self.base_dir, "baseline", "harness.py"),
            os.path.join(v001_dir, "harness.py"),
        )
        shutil.copy2(
            os.path.join(self.base_dir, "baseline", "config.json"),
            os.path.join(v001_dir, "config.json"),
        )
        with open(os.path.join(v001_dir, "proposal.md"), "w") as f:
            f.write("Based on baseline\n\nCopy of baseline for testing.")

        # 3. Evaluate v001
        traces_dir = os.path.join(v001_dir, "traces")
        scores_path = os.path.join(v001_dir, "scores.json")
        self._run(
            "python3", os.path.join(TOOLS_DIR, "evaluate.py"), "run",
            "--harness", os.path.join(v001_dir, "harness.py"),
            "--config", os.path.join(v001_dir, "config.json"),
            "--tasks-dir", os.path.join(self.base_dir, "eval", "tasks"),
            "--eval", os.path.join(self.base_dir, "eval", "eval.py"),
            "--traces-dir", traces_dir,
            "--scores", scores_path,
            "--timeout", "30",
        )

        # Verify evaluation produced scores
        scores = json.load(open(scores_path))
        self.assertIn("combined_score", scores)

        # 4. Update state
        self._run(
            "python3", os.path.join(TOOLS_DIR, "state.py"), "update",
            "--base-dir", self.base_dir,
            "--version", "v001",
            "--scores", scores_path,
            "--proposal", os.path.join(v001_dir, "proposal.md"),
        )

        # Verify state updated
        summary = json.load(open(os.path.join(self.base_dir, "summary.json")))
        self.assertEqual(summary["iterations"], 1)
        self.assertEqual(len(summary["history"]), 2)  # baseline + v001

        # Verify PROPOSER_HISTORY.md was appended
        history = open(os.path.join(self.base_dir, "PROPOSER_HISTORY.md")).read()
        self.assertIn("v001", history)

        # Verify STATE.md was regenerated
        state_md = open(os.path.join(self.base_dir, "STATE.md")).read()
        self.assertIn("v001", state_md)

        # Verify traces exist
        self.assertTrue(os.path.exists(os.path.join(traces_dir, "timing.json")))
        self.assertTrue(os.path.exists(os.path.join(traces_dir, "stdout.log")))

        # 5. Show status
        r = self._run(
            "python3", os.path.join(TOOLS_DIR, "state.py"), "show",
            "--base-dir", self.base_dir,
        )
        self.assertIn("v001", r.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run integration test**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_integration -v
```

Expected: 1 test, PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration test for init → evaluate → state update cycle"
```

---

### Task 8: Proposer Agent

**Files:**
- Create: `agents/harness-evolver-proposer.md`

- [ ] **Step 1: Write the proposer agent definition**

Create `agents/harness-evolver-proposer.md`:

````markdown
---
name: harness-evolver-proposer
description: |
  Use this agent when the harness-evolve skill needs to propose a new harness candidate.
  This agent navigates the .harness-evolver/ filesystem to diagnose failures in prior
  candidates and propose an improved harness. It is the core of the Meta-Harness optimization loop.
model: opus
---

# Harness Evolver — Proposer Agent

You are the proposer in a Meta-Harness optimization loop. Your job is to analyze all prior harness candidates — their code, execution traces, and scores — and propose a new harness that improves on them.

## Context

You are working inside a `.harness-evolver/` directory with this structure:

```
.harness-evolver/
├── summary.json              # Panorama: all versions, scores, parents
├── PROPOSER_HISTORY.md       # Your prior decisions and their outcomes
├── config.json               # Project config (harness command, eval command, etc.)
├── baseline/
│   ├── harness.py            # Original harness (read-only reference)
│   └── config.json           # Original config
├── eval/
│   ├── eval.py               # Scoring script (DO NOT MODIFY)
│   └── tasks/                # Test cases (DO NOT MODIFY)
└── harnesses/
    └── v001/
        ├── harness.py        # Candidate code
        ├── config.json       # Candidate params
        ├── proposal.md       # Why this version exists
        ├── scores.json       # How it scored
        └── traces/
            ├── stdout.log    # Raw stdout from harness runs
            ├── stderr.log    # Raw stderr
            ├── timing.json   # Per-task timing
            └── task_001/
                ├── input.json   # What the harness received
                ├── output.json  # What the harness returned
                └── extra/       # Optional traces from harness
```

## Your Workflow

### Phase 1: ORIENT (read summary, identify focus)

1. Read `summary.json` to see all versions, scores, and parent lineage.
2. Read `PROPOSER_HISTORY.md` to see what you've tried before and what worked or failed.
3. Decide which 2-3 versions to investigate deeply:
   - (a) The current best candidate
   - (b) The most recent regression (if any)
   - (c) A version with a different failure mode

### Phase 2: DIAGNOSE (deep trace analysis)

Investigate the selected versions. Use standard tools:
- `cat .harness-evolver/harnesses/v{N}/scores.json` — see per-task results
- `cat .harness-evolver/harnesses/v{N}/traces/task_XXX/output.json` — see what went wrong
- `cat .harness-evolver/harnesses/v{N}/traces/stderr.log` — look for errors
- `diff .harness-evolver/harnesses/v{A}/harness.py .harness-evolver/harnesses/v{B}/harness.py` — compare
- `grep -r "error\|Error\|FAIL\|exception" .harness-evolver/harnesses/v{N}/traces/`

Ask yourself:
- Which tasks fail? Is there a pattern?
- What changed between a version that passed and one that failed?
- Is this a code bug, a prompt issue, a retrieval problem, or a parameter problem?

**Do NOT read traces of all versions.** Focus on 2-3. Use summary.json to filter.

### Phase 3: PROPOSE (write new harness)

Based on your diagnosis, create a new version directory and write:

1. `harnesses/v{NEXT}/harness.py` — the new harness code
2. `harnesses/v{NEXT}/config.json` — parameters (copy from parent, modify if needed)
3. `harnesses/v{NEXT}/proposal.md` — your reasoning (MUST include "Based on v{PARENT}")

**The harness MUST maintain this CLI interface:**
```
python3 harness.py --input INPUT.json --output OUTPUT.json [--traces-dir DIR] [--config CONFIG.json]
```

### Phase 4: DOCUMENT

Write a clear `proposal.md` that includes:
- `Based on v{PARENT}` on the first line
- What failure modes you identified
- What specific changes you made and why
- What you expect to improve

Append a summary to `PROPOSER_HISTORY.md`.

## Rules

1. **Every change motivated by evidence.** Cite the task ID, trace line, or score delta that justifies the change. Never change code "to see what happens."

2. **After a regression, prefer additive changes.** If the last version regressed, make smaller, safer modifications. Don't combine multiple changes.

3. **Don't repeat past mistakes.** Read PROPOSER_HISTORY.md. If an approach already failed (e.g., "changed prompt template, broke JSON parsing"), don't try a similar approach without strong justification.

4. **One hypothesis at a time when possible.** Changing A+B+C simultaneously makes it impossible to diagnose which helped or hurt. If you must make multiple changes, document each clearly.

5. **Maintain the interface.** The harness must accept --input, --output, --traces-dir, --config. Breaking the interface breaks the entire loop.

6. **Prefer readable harnesses over defensive ones.** If the harness has grown past 2x the baseline size without proportional score improvement, consider simplifying. Accumulated try/catch blocks, redundant fallbacks, and growing if-chains are a code smell in evolved harnesses.

## What You Do NOT Do

- Do NOT run the evaluation. The evolve skill handles that after you propose.
- Do NOT modify anything in `eval/` — the eval set and scoring are fixed.
- Do NOT modify `baseline/` — it is your immutable reference.
- Do NOT modify any prior version's files — history is immutable.
- Do NOT create files outside of `harnesses/v{NEXT}/` and `PROPOSER_HISTORY.md`.

## Output

When done, report what you created:
- Version number (e.g., "v003")
- Parent version
- 1-sentence summary of the change
- Expected impact on score
````

- [ ] **Step 2: Validate markdown syntax**

```bash
head -5 agents/harness-evolver-proposer.md
# Should show YAML frontmatter: ---\nname: harness-evolver-proposer\n...
```

- [ ] **Step 3: Commit**

```bash
git add agents/harness-evolver-proposer.md
git commit -m "feat: add proposer agent definition"
```

---

### Task 9: Skills (init, evolve, status)

**Files:**
- Create: `skills/harness-evolve-init/SKILL.md`
- Create: `skills/harness-evolve/SKILL.md`
- Create: `skills/harness-evolve-status/SKILL.md`

- [ ] **Step 1: Write harness-evolve-init skill**

Create `skills/harness-evolve-init/SKILL.md`:

````markdown
---
name: harness-evolve-init
description: "Initialize harness evolution in the current project. Sets up .harness-evolver/ with baseline harness, eval script, and tasks."
argument-hint: "--harness <path> --eval <path> --tasks <path>"
allowed-tools: [Read, Write, Bash, Glob]
---

# /harness-evolve-init

Initialize the Harness Evolver for this project.

## Arguments

- `--harness <path>` — path to the harness script (any executable, typically Python)
- `--eval <path>` — path to the evaluation script
- `--tasks <path>` — path to the tasks directory (JSON files with id, input, expected)

## What To Do

Run the init tool:

```bash
python3 ~/.harness-evolver/tools/init.py \
    --harness {harness} \
    --eval {eval} \
    --tasks {tasks} \
    --base-dir .harness-evolver \
    --harness-config {config if provided, else omit} \
    --tools-dir ~/.harness-evolver/tools
```

If `~/.harness-evolver/tools/init.py` does not exist, check `.harness-evolver/tools/init.py` (local override).

After init completes, report:
- Baseline score
- Number of tasks
- Next step: run `/harness-evolve` to start the optimization loop
````

- [ ] **Step 2: Write harness-evolve skill**

Create `skills/harness-evolve/SKILL.md`:

````markdown
---
name: harness-evolve
description: "Run the harness evolution loop. Autonomously proposes, evaluates, and iterates on harness designs using full execution traces as feedback."
argument-hint: "[--iterations N] [--candidates-per-iter N]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent]
---

# /harness-evolve

Run the Meta-Harness optimization loop.

## Arguments

- `--iterations N` (default: 10) — number of evolution iterations
- `--candidates-per-iter N` (default: 1) — harnesses per iteration

## Prerequisites

Run `/harness-evolve-init` first. The `.harness-evolver/` directory must exist with a valid `summary.json`.

## The Loop

For each iteration i from 1 to N:

### 1. PROPOSE

Determine the next version number by reading `summary.json`:

```bash
python3 -c "import json; s=json.load(open('.harness-evolver/summary.json')); print(f'v{s[\"iterations\"]+1:03d}')"
```

Spawn the `harness-evolver-proposer` agent with this prompt:

> You are proposing iteration {i}. Create version {version_number} in `.harness-evolver/harnesses/{version_number}/`.
> Working directory contains `.harness-evolver/` with all prior candidates and traces.

The proposer agent will create:
- `.harness-evolver/harnesses/v{NNN}/harness.py`
- `.harness-evolver/harnesses/v{NNN}/config.json`
- `.harness-evolver/harnesses/v{NNN}/proposal.md`

### 2. VALIDATE

```bash
python3 ~/.harness-evolver/tools/evaluate.py validate \
    --harness .harness-evolver/harnesses/v{NNN}/harness.py \
    --config .harness-evolver/harnesses/v{NNN}/config.json
```

If validation fails, ask the proposer to fix (1 retry). If it fails again, set score to 0.0 and continue.

### 3. EVALUATE

```bash
python3 ~/.harness-evolver/tools/evaluate.py run \
    --harness .harness-evolver/harnesses/v{NNN}/harness.py \
    --config .harness-evolver/harnesses/v{NNN}/config.json \
    --tasks-dir .harness-evolver/eval/tasks/ \
    --eval .harness-evolver/eval/eval.py \
    --traces-dir .harness-evolver/harnesses/v{NNN}/traces/ \
    --scores .harness-evolver/harnesses/v{NNN}/scores.json \
    --timeout 60
```

### 4. UPDATE STATE

```bash
python3 ~/.harness-evolver/tools/state.py update \
    --base-dir .harness-evolver \
    --version v{NNN} \
    --scores .harness-evolver/harnesses/v{NNN}/scores.json \
    --proposal .harness-evolver/harnesses/v{NNN}/proposal.md
```

### 5. REPORT

Read the updated `summary.json` and report:
- `Iteration {i}/{N}: v{NNN} scored {score} (best: v{best} at {best_score})`
- If regression (score < parent score): warn
- If new best: celebrate

### Stop Conditions

- All N iterations completed
- **Stagnation**: 3 consecutive iterations without >1% improvement. Read `summary.json` history to check.
- **Target reached**: if `config.json` has `target_score` set and achieved.

When stopping, report final summary: best version, score, number of iterations, improvement over baseline.

## Tool Path Resolution

Check `.harness-evolver/tools/` first (local override), then `~/.harness-evolver/tools/` (global install).
````

- [ ] **Step 3: Write harness-evolve-status skill**

Create `skills/harness-evolve-status/SKILL.md`:

````markdown
---
name: harness-evolve-status
description: "Show the current status of harness evolution: best score, iteration count, progress history."
allowed-tools: [Read, Bash]
---

# /harness-evolve-status

Show the current evolution status.

## What To Do

```bash
python3 ~/.harness-evolver/tools/state.py show --base-dir .harness-evolver
```

If that doesn't exist, try:

```bash
python3 .harness-evolver/tools/state.py show --base-dir .harness-evolver
```

Also read and display the contents of `.harness-evolver/STATE.md` for the full status table.

If `.harness-evolver/` doesn't exist, tell the user to run `/harness-evolve-init` first.
````

- [ ] **Step 4: Commit**

```bash
git add skills/
git commit -m "feat: add skills for init, evolve, and status commands"
```

---

### Task 10: Installer (package.json + install.js)

**Files:**
- Create: `package.json`
- Create: `bin/install.js`

- [ ] **Step 1: Write package.json**

Create `package.json`:

```json
{
  "name": "harness-evolver",
  "version": "0.1.0",
  "description": "Meta-Harness-style autonomous harness optimization for Claude Code",
  "author": "Raphael Valdetaro Christi Cordeiro",
  "license": "MIT",
  "repository": {
    "type": "git",
    "url": "https://github.com/raphaelchristi/harness-evolver.git"
  },
  "keywords": [
    "claude-code",
    "harness",
    "meta-harness",
    "llm",
    "optimization",
    "agent"
  ],
  "bin": {
    "harness-evolver": "bin/install.js"
  },
  "files": [
    "bin/",
    "skills/",
    "agents/",
    "tools/",
    "examples/"
  ]
}
```

- [ ] **Step 2: Write install.js**

Create `bin/install.js`:

```javascript
#!/usr/bin/env node
/**
 * Harness Evolver installer.
 * Detects Claude Code, copies skills/agents/tools to the right locations.
 *
 * Usage: npx harness-evolver@latest
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const PLUGIN_ROOT = path.resolve(__dirname, "..");
const HOME = process.env.HOME || process.env.USERPROFILE;

// Destination paths
const CLAUDE_DIR = path.join(HOME, ".claude");
const COMMANDS_DIR = path.join(CLAUDE_DIR, "commands", "harness-evolver");
const AGENTS_DIR = path.join(CLAUDE_DIR, "agents");
const TOOLS_DIR = path.join(HOME, ".harness-evolver", "tools");
const EXAMPLES_DIR = path.join(HOME, ".harness-evolver", "examples");

function log(msg) {
  console.log(`  ${msg}`);
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function copyFile(src, dest) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

function checkPython() {
  try {
    execSync("python3 --version", { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

function main() {
  console.log("\n  Harness Evolver v0.1.0\n");

  // 1. Check prerequisites
  if (!checkPython()) {
    console.error("  ERROR: python3 not found in PATH. Install Python 3.8+ first.");
    process.exit(1);
  }
  log("python3 found");

  // 2. Detect Claude Code
  if (!fs.existsSync(CLAUDE_DIR)) {
    console.error(`  ERROR: Claude Code directory not found at ${CLAUDE_DIR}`);
    console.error("  Install Claude Code first: https://claude.ai/code");
    process.exit(1);
  }
  log("Claude Code detected");

  // 3. Copy skills
  const skillsSource = path.join(PLUGIN_ROOT, "skills");
  for (const skill of fs.readdirSync(skillsSource, { withFileTypes: true })) {
    if (skill.isDirectory()) {
      const src = path.join(skillsSource, skill.name);
      const dest = path.join(COMMANDS_DIR, skill.name);
      copyDir(src, dest);
      log(`skill: ${skill.name}`);
    }
  }

  // 4. Copy agents
  const agentsSource = path.join(PLUGIN_ROOT, "agents");
  fs.mkdirSync(AGENTS_DIR, { recursive: true });
  for (const agent of fs.readdirSync(agentsSource)) {
    copyFile(
      path.join(agentsSource, agent),
      path.join(AGENTS_DIR, agent)
    );
    log(`agent: ${agent}`);
  }

  // 5. Copy tools
  const toolsSource = path.join(PLUGIN_ROOT, "tools");
  fs.mkdirSync(TOOLS_DIR, { recursive: true });
  for (const tool of fs.readdirSync(toolsSource)) {
    copyFile(
      path.join(toolsSource, tool),
      path.join(TOOLS_DIR, tool)
    );
    log(`tool: ${tool}`);
  }

  // 6. Copy examples
  const examplesSource = path.join(PLUGIN_ROOT, "examples");
  if (fs.existsSync(examplesSource)) {
    copyDir(examplesSource, EXAMPLES_DIR);
    log("examples: classifier");
  }

  console.log("\n  Installed successfully!\n");
  console.log("  Next steps:");
  console.log("    1. Copy an example:  cp -r ~/.harness-evolver/examples/classifier ./my-project");
  console.log("    2. cd my-project");
  console.log("    3. /harness-evolve-init --harness harness.py --eval eval.py --tasks tasks/");
  console.log("    4. /harness-evolve --iterations 5\n");
}

main();
```

- [ ] **Step 3: Make install.js executable**

```bash
chmod +x bin/install.js
```

- [ ] **Step 4: Test installer locally**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && node bin/install.js
```

Expected: copies files to `~/.claude/commands/harness-evolver/`, `~/.claude/agents/`, `~/.harness-evolver/tools/`.

- [ ] **Step 5: Commit**

```bash
git add package.json bin/install.js
git commit -m "feat: add npm package and installer for Claude Code"
```

---

### Task 11: Run All Tests

- [ ] **Step 1: Run full test suite**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest discover -s tests -v
```

Expected: All tests pass (trace_logger: 5, state: 10, evaluate: 6, init: 5, integration: 1 = **27 tests**).

- [ ] **Step 2: Fix any failures, re-run**

If any test fails, fix the issue and re-run. Do not proceed until all pass.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: all tests passing, MVP implementation complete"
```

---

---

# Phase 2: LangSmith Integration

> **Spec:** `docs/specs/2026-03-31-langsmith-integration.md`
> **Prerequisite:** Phase 1 (Tasks 1-11) complete and validated
> **Principle:** LangSmith is optional. The MVP loop continues working without it. This phase adds richness, not dependencies.

### Task 12: LangSmith API Client

**Files:**
- Create: `tools/langsmith_api.py`
- Create: `tests/test_langsmith_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_langsmith_api.py`:

```python
"""Tests for langsmith_api.py — REST API client (stdlib urllib)."""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from langsmith_api import get_runs, get_dataset_examples, create_project, get_feedback


class TestLangSmithAPI(unittest.TestCase):
    @patch("langsmith_api.urlopen")
    def test_get_runs_sends_correct_request(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"runs": []}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = get_runs("fake-key", "my-project")
        self.assertEqual(result, {"runs": []})

        # Verify the request was sent correctly
        call_args = mock_urlopen.call_args[0][0]
        self.assertIn("runs/query", call_args.full_url)
        self.assertEqual(call_args.get_header("X-api-key"), "fake-key")

    @patch("langsmith_api.urlopen")
    def test_get_dataset_examples(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([{"id": "ex1"}]).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = get_dataset_examples("fake-key", "ds-123")
        self.assertEqual(result, [{"id": "ex1"}])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_langsmith_api -v
```

Expected: `ModuleNotFoundError: No module named 'langsmith_api'`

- [ ] **Step 3: Write implementation**

Create `tools/langsmith_api.py`:

```python
#!/usr/bin/env python3
"""LangSmith REST API client. Stdlib-only (urllib + json).

Provides low-level API calls to LangSmith for trace export, dataset access,
and evaluator execution. Used by langsmith_adapter.py.
"""

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

LANGSMITH_BASE_URL = os.environ.get(
    "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
)


def _request(method, path, api_key, data=None):
    url = f"{LANGSMITH_BASE_URL}{path}"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"LangSmith API error {e.code}: {error_body}")


def get_runs(api_key, project_name, run_type=None, limit=100):
    params = {"project_name": project_name, "limit": limit}
    if run_type:
        params["run_type"] = run_type
    return _request("POST", "/api/v1/runs/query", api_key, params)


def get_dataset_examples(api_key, dataset_id, limit=1000):
    return _request(
        "GET", f"/api/v1/datasets/{dataset_id}/examples?limit={limit}", api_key
    )


def create_project(api_key, project_name):
    return _request("POST", "/api/v1/projects", api_key, {"name": project_name})


def get_feedback(api_key, project_name):
    runs = get_runs(api_key, project_name)
    run_ids = [r["id"] for r in runs.get("runs", [])]
    if not run_ids:
        return []
    return _request("POST", "/api/v1/feedback/query", api_key, {"run_ids": run_ids})


def run_evaluator(api_key, project_name, evaluator_name):
    return _request(
        "POST",
        "/api/v1/evaluators/run",
        api_key,
        {"project_name": project_name, "evaluator": evaluator_name},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest tests.test_langsmith_api -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/langsmith_api.py tests/test_langsmith_api.py
git commit -m "feat: add LangSmith REST API client (stdlib urllib)"
```

---

### Task 13: LangSmith Adapter (evaluate.py integration)

**Files:**
- Create: `tools/langsmith_adapter.py`
- Modify: `tools/evaluate.py`
- Create: `tests/test_langsmith_adapter.py`

- [ ] **Step 1: Write the adapter failing test**

Create `tests/test_langsmith_adapter.py`:

```python
"""Tests for langsmith_adapter.py — bridges evaluate.py with LangSmith."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from langsmith_adapter import (
    setup_tracing,
    export_traces,
    run_evaluators,
    is_enabled,
)


class TestIsEnabled(unittest.TestCase):
    def test_disabled_when_no_config(self):
        self.assertFalse(is_enabled({}))

    def test_disabled_when_explicitly_false(self):
        config = {"eval": {"langsmith": {"enabled": False}}}
        self.assertFalse(is_enabled(config))

    def test_enabled_when_true(self):
        config = {"eval": {"langsmith": {"enabled": True}}}
        self.assertTrue(is_enabled(config))


class TestSetupTracing(unittest.TestCase):
    def test_sets_env_vars(self):
        config = {
            "eval": {
                "langsmith": {
                    "enabled": True,
                    "api_key_env": "TEST_LS_KEY",
                    "project_prefix": "test-evolver",
                }
            }
        }
        with patch.dict(os.environ, {"TEST_LS_KEY": "fake-key"}):
            env = setup_tracing(config, "v003")
            self.assertEqual(env["LANGCHAIN_TRACING_V2"], "true")
            self.assertEqual(env["LANGCHAIN_API_KEY"], "fake-key")
            self.assertEqual(env["LANGCHAIN_PROJECT"], "test-evolver-v003")

    def test_returns_empty_when_no_api_key(self):
        config = {
            "eval": {
                "langsmith": {
                    "enabled": True,
                    "api_key_env": "NONEXISTENT_KEY",
                    "project_prefix": "test",
                }
            }
        }
        env = setup_tracing(config, "v001")
        self.assertEqual(env, {})


class TestExportTraces(unittest.TestCase):
    @patch("langsmith_adapter.langsmith_api")
    def test_export_creates_langsmith_dir(self, mock_api):
        mock_api.get_runs.return_value = {"runs": [
            {
                "id": "run1", "run_type": "llm", "name": "chat",
                "inputs": {"prompt": "hi"}, "outputs": {"text": "hello"},
                "error": None, "latency_ms": 500,
                "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30,
                "child_run_ids": [], "extra": {}, "feedback_stats": None,
            }
        ]}
        tmpdir = tempfile.mkdtemp()
        config = {
            "eval": {
                "langsmith": {
                    "enabled": True,
                    "api_key_env": "TEST_KEY",
                    "project_prefix": "test",
                    "export_traces": True,
                }
            }
        }
        with patch.dict(os.environ, {"TEST_KEY": "fake"}):
            export_traces(config, "v001", tmpdir)
        ls_dir = os.path.join(tmpdir, "langsmith")
        self.assertTrue(os.path.isdir(ls_dir))
        self.assertTrue(os.path.exists(os.path.join(ls_dir, "_summary.json")))
        self.assertTrue(os.path.exists(os.path.join(ls_dir, "run1.json")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Write the adapter implementation**

Create `tools/langsmith_adapter.py`:

```python
#!/usr/bin/env python3
"""LangSmith adapter for Harness Evolver.

Bridges evaluate.py with LangSmith for:
1. Auto-tracing setup (env vars for LangChain)
2. Trace export to filesystem (for proposer)
3. LLM-as-Judge evaluators

Stdlib-only. Uses langsmith_api.py for REST calls.
"""

import json
import os
import sys

# Import sibling module
sys.path.insert(0, os.path.dirname(__file__))
import langsmith_api


def is_enabled(config):
    return config.get("eval", {}).get("langsmith", {}).get("enabled", False)


def setup_tracing(config, version):
    """Return env vars dict to set before running harness. Empty dict if unavailable."""
    ls = config["eval"]["langsmith"]
    api_key = os.environ.get(ls.get("api_key_env", "LANGSMITH_API_KEY"), "")
    if not api_key:
        return {}
    return {
        "LANGCHAIN_TRACING_V2": "true",
        "LANGCHAIN_API_KEY": api_key,
        "LANGCHAIN_PROJECT": f"{ls['project_prefix']}-{version}",
    }


def export_traces(config, version, traces_dir):
    """Export LangSmith runs to traces/langsmith/ for the proposer to read."""
    ls = config["eval"]["langsmith"]
    if not ls.get("export_traces", True):
        return

    api_key = os.environ.get(ls.get("api_key_env", "LANGSMITH_API_KEY"), "")
    if not api_key:
        return

    project_name = f"{ls['project_prefix']}-{version}"
    try:
        response = langsmith_api.get_runs(api_key, project_name)
    except Exception as e:
        print(f"WARNING: Failed to export LangSmith traces: {e}", file=sys.stderr)
        return

    runs = response.get("runs", [])
    ls_dir = os.path.join(traces_dir, "langsmith")
    os.makedirs(ls_dir, exist_ok=True)

    for run in runs:
        run_file = os.path.join(ls_dir, f"{run['id']}.json")
        with open(run_file, "w") as f:
            json.dump(
                {
                    "run_id": run["id"],
                    "run_type": run.get("run_type"),
                    "name": run.get("name"),
                    "inputs": run.get("inputs"),
                    "outputs": run.get("outputs"),
                    "error": run.get("error"),
                    "latency_ms": run.get("latency_ms"),
                    "tokens": {
                        "prompt": run.get("prompt_tokens", 0),
                        "completion": run.get("completion_tokens", 0),
                        "total": run.get("total_tokens", 0),
                    },
                    "child_runs": len(run.get("child_run_ids", [])),
                    "feedback": run.get("feedback_stats"),
                },
                f,
                indent=2,
            )

    summary = {
        "total_runs": len(runs),
        "run_types": {},
        "errors": [],
        "total_tokens": 0,
        "avg_latency_ms": 0,
    }
    for r in runs:
        rt = r.get("run_type", "unknown")
        summary["run_types"][rt] = summary["run_types"].get(rt, 0) + 1
        summary["total_tokens"] += r.get("total_tokens", 0)
        if r.get("error"):
            summary["errors"].append({"run_id": r["id"], "error": r["error"]})
    if runs:
        summary["avg_latency_ms"] = round(
            sum(r.get("latency_ms", 0) for r in runs) / len(runs), 1
        )
    with open(os.path.join(ls_dir, "_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)


def run_evaluators(config, version):
    """Run LangSmith built-in evaluators, return scores dict."""
    ls = config["eval"]["langsmith"]
    evaluators = ls.get("evaluators", {})
    builtin = evaluators.get("builtin", [])
    if not builtin:
        return {}

    api_key = os.environ.get(ls.get("api_key_env", "LANGSMITH_API_KEY"), "")
    if not api_key:
        return {}

    project_name = f"{ls['project_prefix']}-{version}"
    scores = {}
    for name in builtin:
        try:
            result = langsmith_api.run_evaluator(api_key, project_name, name)
            scores[name] = result.get("aggregate_score", 0.0)
        except Exception as e:
            print(f"WARNING: LangSmith evaluator '{name}' failed: {e}", file=sys.stderr)
    return scores
```

- [ ] **Step 3: Modify evaluate.py to use the adapter**

Add these changes to `tools/evaluate.py`:

In `cmd_run`, after building the harness subprocess environment and before the task loop:

```python
# At the top of cmd_run, after parsing args:
    langsmith_env = {}
    project_config_path = os.path.join(os.path.dirname(traces_dir), "..", "config.json")
    project_config = {}
    if os.path.exists(project_config_path):
        project_config = json.load(open(project_config_path))

    try:
        from langsmith_adapter import is_enabled, setup_tracing, export_traces, run_evaluators
        if is_enabled(project_config):
            version = os.path.basename(os.path.dirname(traces_dir))
            langsmith_env = setup_tracing(project_config, version)
    except ImportError:
        pass
```

When calling `subprocess.run` for each task, merge `langsmith_env` into the environment:

```python
    env = {**os.environ, **langsmith_env} if langsmith_env else None
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
```

After running the user's eval script, add LangSmith evaluators and export:

```python
    # After user eval completes successfully:
    try:
        from langsmith_adapter import is_enabled, export_traces, run_evaluators
        if is_enabled(project_config):
            version = os.path.basename(os.path.dirname(traces_dir))
            export_traces(project_config, version, traces_dir)
            ls_scores = run_evaluators(project_config, version)
            if ls_scores and os.path.exists(scores_path):
                scores = json.load(open(scores_path))
                scores["langsmith"] = ls_scores
                json.dump(scores, open(scores_path, "w"), indent=2)
    except ImportError:
        pass
```

- [ ] **Step 4: Run all tests (Phase 1 + Phase 2)**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest discover -s tests -v
```

Expected: All tests pass. Phase 1 tests unaffected (LangSmith code paths are guarded by try/except ImportError and is_enabled checks).

- [ ] **Step 5: Commit**

```bash
git add tools/langsmith_adapter.py tools/evaluate.py tests/test_langsmith_adapter.py
git commit -m "feat: add LangSmith integration (auto-tracing, trace export, LLM-as-Judge)"
```

---

### Task 14: LangSmith Dataset Support + Init Detection

**Files:**
- Modify: `tools/init.py`
- Modify: `skills/harness-evolve-init/SKILL.md`
- Create: `tests/test_langsmith_init.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_langsmith_init.py`:

```python
"""Tests for LangSmith detection in init.py."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
EXAMPLE_DIR = os.path.join(REPO_ROOT, "examples", "classifier")


class TestLangSmithDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.tmpdir, ".harness-evolver")

    def test_init_detects_langsmith_api_key(self):
        """When LANGSMITH_API_KEY is set, config.json should have langsmith.enabled=true."""
        env = {**os.environ, "LANGSMITH_API_KEY": "lsv2_fake_key_for_test"}
        r = subprocess.run(
            [
                "python3", os.path.join(TOOLS_DIR, "init.py"),
                "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
                "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
                "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
                "--base-dir", self.base_dir,
                "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
                "--tools-dir", TOOLS_DIR,
            ],
            capture_output=True, text=True, timeout=120, env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        config = json.load(open(os.path.join(self.base_dir, "config.json")))
        self.assertTrue(config["eval"]["langsmith"]["enabled"])

    def test_init_no_langsmith_without_key(self):
        """When LANGSMITH_API_KEY is not set, langsmith.enabled should be false."""
        env = {k: v for k, v in os.environ.items() if k != "LANGSMITH_API_KEY"}
        r = subprocess.run(
            [
                "python3", os.path.join(TOOLS_DIR, "init.py"),
                "--harness", os.path.join(EXAMPLE_DIR, "harness.py"),
                "--eval", os.path.join(EXAMPLE_DIR, "eval.py"),
                "--tasks", os.path.join(EXAMPLE_DIR, "tasks"),
                "--base-dir", self.base_dir,
                "--harness-config", os.path.join(EXAMPLE_DIR, "config.json"),
                "--tools-dir", TOOLS_DIR,
            ],
            capture_output=True, text=True, timeout=120, env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        config = json.load(open(os.path.join(self.base_dir, "config.json")))
        self.assertFalse(config["eval"]["langsmith"]["enabled"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Modify init.py to detect LangSmith**

Add this function to `tools/init.py`:

```python
def _detect_langsmith():
    """Auto-detect LangSmith API key and return config section."""
    if os.environ.get("LANGSMITH_API_KEY"):
        return {
            "enabled": True,
            "api_key_env": "LANGSMITH_API_KEY",
            "project_prefix": "harness-evolver",
            "evaluators": {"builtin": ["correctness"], "custom": []},
            "export_traces": True,
            "trace_format": "jsonl",
        }
    return {"enabled": False}
```

In the config generation section of `main()`, add the langsmith section:

```python
    config = {
        ...
        "eval": {
            ...
            "langsmith": _detect_langsmith(),
        },
        ...
    }
```

- [ ] **Step 3: Update init skill for --langsmith-dataset flag**

Add to `skills/harness-evolve-init/SKILL.md`:

```markdown
## LangSmith Dataset (optional)

If the user provides `--langsmith-dataset <dataset_id>`:

```bash
python3 ~/.harness-evolver/tools/init.py \
    --harness {harness} \
    --eval {eval} \
    --tasks {tasks} \
    --base-dir .harness-evolver \
    --langsmith-dataset {dataset_id}
```

This pulls examples from a LangSmith dataset to use as tasks.
Requires `LANGSMITH_API_KEY` in the environment.
```

- [ ] **Step 4: Run all tests**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver && python3 -m unittest discover -s tests -v
```

Expected: All tests pass including new LangSmith tests.

- [ ] **Step 5: Update proposer agent with LangSmith hint**

Append to the Phase 2 section in `agents/harness-evolver-proposer.md`:

```markdown
## LangSmith Traces (when available)

If `traces/langsmith/` exists in a version's traces directory, it contains exported LangSmith runs
with rich diagnostic data (every LLM call, tool call, retriever call with inputs/outputs/tokens/latency).

- Read `traces/langsmith/_summary.json` first for an overview (total runs, errors, token usage).
- Then grep or cat specific run files for deep diagnosis.
- These traces are much richer than stdout/stderr — prefer them when available.
```

- [ ] **Step 6: Commit**

```bash
git add tools/init.py skills/ agents/ tests/test_langsmith_init.py
git commit -m "feat: add LangSmith auto-detection in init + dataset support"
```

---

## File Summary

| File | Purpose | Lines (est.) |
|------|---------|--------------|
| `tools/trace_logger.py` | Structured trace recording helper | ~40 |
| `tools/state.py` | Manages summary.json, STATE.md, PROPOSER_HISTORY.md | ~200 |
| `tools/evaluate.py` | Orchestrates harness evaluation with trace capture | ~220 |
| `tools/init.py` | Creates .harness-evolver/ project structure | ~120 |
| `examples/classifier/harness.py` | Naive medical classifier (mock + LLM) | ~90 |
| `examples/classifier/eval.py` | Exact match accuracy scorer | ~50 |
| `examples/classifier/tasks/*.json` | 10 medical symptom tasks | 10 files |
| `agents/harness-evolver-proposer.md` | Proposer agent definition | ~150 |
| `skills/harness-evolve-init/SKILL.md` | Init skill | ~40 |
| `skills/harness-evolve/SKILL.md` | Evolution loop skill | ~100 |
| `skills/harness-evolve-status/SKILL.md` | Status skill | ~25 |
| `package.json` | npm package config | ~20 |
| `bin/install.js` | Node.js installer | ~100 |
| `tests/test_trace_logger.py` | Unit tests | ~50 |
| `tests/test_state.py` | Unit tests | ~120 |
| `tests/test_evaluate.py` | Unit tests | ~80 |
| `tests/test_init.py` | Unit tests | ~70 |
| `tests/test_integration.py` | Integration test | ~80 |
| **Phase 1 Total** | | **~1500 lines** |

### Phase 2: LangSmith Integration

| File | Purpose | Lines (est.) |
|------|---------|--------------|
| `tools/langsmith_api.py` | REST API client (stdlib urllib) | ~70 |
| `tools/langsmith_adapter.py` | Bridges evaluate.py ↔ LangSmith | ~120 |
| `tests/test_langsmith_api.py` | Unit tests (mocked API) | ~50 |
| `tests/test_langsmith_adapter.py` | Unit tests (mocked API) | ~80 |
| `tests/test_langsmith_init.py` | Init detection tests | ~50 |
| **Phase 2 Total** | | **~370 lines** |
| **Grand Total** | | **~1870 lines** |
