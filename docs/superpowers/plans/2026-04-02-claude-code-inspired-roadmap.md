# Claude Code-Inspired Evolution Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 12 features inspired by Claude Code's leaked architecture to make harness-evolver smarter, cheaper, and more autonomous.

**Architecture:** Five implementation phases ordered by dependency. Phase 1 builds foundation (state validation + smart gating). Phase 2 adds cross-iteration memory. Phase 3 optimizes proposer economics. Phase 4 upgrades agent intelligence. Phase 5 adds autonomous differentiators. Each phase produces working, testable software independently.

**Tech Stack:** Python 3.10+ (tools), Markdown (skills/agents), LangSmith SDK, langsmith-cli, git worktrees

---

## Dependency Graph

```
Phase 1: Foundation
  ├─ Task 1: State Validator (Feature 10)
  └─ Task 2: Three-Gate Triggers (Feature 4)
          │
Phase 2: Evolution Memory
  ├─ Task 3: Regression Tracker (Feature 7) ─── depends on Task 1
  └─ Task 4: autoConsolidate (Feature 1) ────── depends on Task 1, Task 2
          │
Phase 3: Proposer Optimization
  ├─ Task 5: KV Cache Prompts (Feature 2) ──── depends on Task 4
  ├─ Task 6: Tool Restrictions (Feature 8) ─── independent
  └─ Task 7: Compaction Pipeline (Feature 5) ── depends on Task 5
          │
Phase 4: Agent Intelligence
  ├─ Task 8: Coordinator Synthesis (Feature 6) ── depends on Task 4
  └─ Task 9: Active Critic (Feature 3) ────────── depends on Task 4, Task 8
          │
Phase 5: Autonomous Differentiators
  ├─ Task 10: ULTRAPLAN Architect (Feature 9) ── depends on Task 2
  ├─ Task 11: Self-Scheduling (Feature 11) ───── depends on Task 2
  └─ Task 12: Anti-Distillation (Feature 12) ── depends on Task 3
```

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `tools/validate_state.py` | Validate .evolver.json against LangSmith state |
| `tools/iteration_gate.py` | Three-gate check (score, cost, convergence) |
| `tools/regression_tracker.py` | Track failing→passing transitions, add regression examples |
| `tools/consolidate.py` | Cross-iteration memory consolidation (orient/gather/consolidate/prune) |
| `tools/synthesize_strategy.py` | Generate evolution strategy document from trace analysis |
| `tools/add_evaluator.py` | Programmatically add evaluators to .evolver.json and LangSmith |
| `tools/adversarial_inject.py` | Inject adversarial examples into dataset |
| `agents/evolver-consolidator.md` | Background agent for cross-iteration memory consolidation |

### Modified Files

| File | Changes |
|------|---------|
| `skills/evolve/SKILL.md` | All phases modify this — gating, validation, consolidation, synthesis, scheduling |
| `agents/evolver-critic.md` | Phase 4: add evaluator generation + auto-spawn capability |
| `agents/evolver-architect.md` | Phase 5: add remote session / ULTRAPLAN mode |
| `agents/evolver-proposer.md` | Phase 3: add compaction instructions, tool restriction docs |
| `agents/evolver-testgen.md` | Phase 5: add adversarial injection mode |
| `.evolver.json` schema | Phases 1-4: add `gate_config`, `evolution_memory_path`, `iteration_costs` |

---

## Phase 1: Foundation

### Task 1: State Validator (Feature 10 — Skeptical Memory)

Validate that `.evolver.json` hasn't diverged from LangSmith reality before each iteration.

**Files:**
- Create: `tools/validate_state.py`
- Modify: `skills/evolve/SKILL.md:69` (add validation before loop body)

- [ ] **Step 1: Create `tools/validate_state.py` with argument parsing**

```python
#!/usr/bin/env python3
"""Validate .evolver.json state against LangSmith reality.

Checks that referenced experiments, datasets, and projects still exist.
Returns JSON with validation results and any divergences found.

Usage:
    python3 validate_state.py --config .evolver.json --output validation.json
"""

import argparse
import json
import os
import platform
import sys


def ensure_langsmith_api_key():
    """Load LANGSMITH_API_KEY from credentials file or .env if not in env."""
    if os.environ.get("LANGSMITH_API_KEY"):
        return True
    if platform.system() == "Darwin":
        creds_path = os.path.expanduser("~/Library/Application Support/langsmith-cli/credentials")
    else:
        creds_path = os.path.expanduser("~/.config/langsmith-cli/credentials")
    if os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    if os.path.exists(".env"):
        try:
            with open(".env") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY=") and not line.startswith("#"):
                        key = line.split("=", 1)[1].strip().strip("'\"")
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    return False


def validate_dataset(client, config):
    """Check dataset exists and has expected example count."""
    issues = []
    dataset_name = config.get("dataset")
    dataset_id = config.get("dataset_id")
    if not dataset_name:
        issues.append({"field": "dataset", "severity": "critical", "message": "No dataset configured"})
        return issues, 0

    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
        if dataset_id and str(dataset.id) != dataset_id:
            issues.append({
                "field": "dataset_id",
                "severity": "warning",
                "message": f"dataset_id mismatch: config has {dataset_id}, LangSmith has {dataset.id}",
            })
        examples = list(client.list_examples(dataset_id=dataset.id, limit=1))
        count = len(list(client.list_examples(dataset_id=dataset.id, limit=500)))
        return issues, count
    except Exception as e:
        issues.append({"field": "dataset", "severity": "critical", "message": f"Dataset not found: {e}"})
        return issues, 0


def validate_best_experiment(client, config):
    """Check best_experiment still exists and score matches."""
    issues = []
    best = config.get("best_experiment")
    if not best:
        return issues

    try:
        runs = list(client.list_runs(project_name=best, is_root=True, limit=1))
        if not runs:
            issues.append({
                "field": "best_experiment",
                "severity": "critical",
                "message": f"Best experiment '{best}' has no runs in LangSmith",
            })
    except Exception as e:
        issues.append({
            "field": "best_experiment",
            "severity": "critical",
            "message": f"Best experiment '{best}' not accessible: {e}",
        })

    return issues


def validate_git_state(config):
    """Check that current git HEAD matches expected state."""
    import subprocess
    issues = []
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=10,
        )
        head = result.stdout.strip()
        if not head:
            issues.append({"field": "git", "severity": "warning", "message": "Could not read git HEAD"})
    except Exception as e:
        issues.append({"field": "git", "severity": "warning", "message": f"Git check failed: {e}"})
    return issues


def main():
    parser = argparse.ArgumentParser(description="Validate .evolver.json against LangSmith")
    parser.add_argument("--config", default=".evolver.json", help="Config path")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--fix", action="store_true", help="Auto-fix divergences where possible")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(json.dumps({"valid": False, "issues": [{"severity": "critical", "message": f"{args.config} not found"}]}))
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    ensure_langsmith_api_key()
    from langsmith import Client
    client = Client()

    all_issues = []

    # Validate dataset
    dataset_issues, example_count = validate_dataset(client, config)
    all_issues.extend(dataset_issues)

    # Validate best experiment
    experiment_issues = validate_best_experiment(client, config)
    all_issues.extend(experiment_issues)

    # Validate git state
    git_issues = validate_git_state(config)
    all_issues.extend(git_issues)

    # Check history consistency
    history = config.get("history", [])
    if history:
        last = history[-1]
        if last.get("experiment") != config.get("best_experiment"):
            best_score = config.get("best_score", 0)
            last_score = last.get("score", 0)
            if last_score >= best_score:
                all_issues.append({
                    "field": "history",
                    "severity": "warning",
                    "message": f"Last history entry ({last['experiment']}) differs from best_experiment ({config.get('best_experiment')})",
                })

    critical = [i for i in all_issues if i.get("severity") == "critical"]
    result = {
        "valid": len(critical) == 0,
        "issues": all_issues,
        "dataset_examples": example_count,
        "config_iterations": config.get("iterations", 0),
        "config_best_score": config.get("best_score", 0),
    }

    output = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    print(output)

    if critical:
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test validate_state.py runs without errors**

Run:
```bash
$EVOLVER_PY tools/validate_state.py --help
```
Expected: argparse help output showing `--config`, `--output`, `--fix` flags.

- [ ] **Step 3: Add validation step to evolve skill**

In `skills/evolve/SKILL.md`, insert after line 67 (after reading config, before the loop body):

```markdown
### 0.5. Validate State

Before starting the loop, verify `.evolver.json` matches LangSmith reality:

\`\`\`bash
VALIDATION=$($EVOLVER_PY $TOOLS/validate_state.py --config .evolver.json 2>/dev/null)
VALID=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin).get('valid', False))")
if [ "$VALID" = "False" ]; then
    echo "WARNING: State validation found issues:"
    echo "$VALIDATION" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for issue in data.get('issues', []):
    print(f'  [{issue[\"severity\"]}] {issue[\"message\"]}')
"
fi
\`\`\`

If critical issues found, ask user whether to continue or fix first via AskUserQuestion:
- "Continue anyway" — proceed with warnings
- "Fix and retry" — attempt auto-fix with `--fix` flag
- "Abort" — stop the evolution loop
```

- [ ] **Step 4: Commit**

```bash
git add tools/validate_state.py skills/evolve/SKILL.md
git commit -m "feat: add state validation before evolution iterations (skeptical memory pattern)"
```

---

### Task 2: Three-Gate Iteration Triggers (Feature 4)

Replace blind N-iteration loops with intelligent gating: score gate, cost gate, convergence gate.

**Files:**
- Create: `tools/iteration_gate.py`
- Modify: `skills/evolve/SKILL.md:371-375` (replace stop conditions)

- [ ] **Step 1: Create `tools/iteration_gate.py`**

```python
#!/usr/bin/env python3
"""Three-gate iteration trigger for Harness Evolver.

Evaluates whether the next evolution iteration should proceed based on:
1. Score gate: skip if no meaningful delta or no clustered failures
2. Cost gate: estimate token cost, stop if budget exceeded
3. Convergence gate: detect statistical plateau

Usage:
    python3 iteration_gate.py --config .evolver.json --output gate_result.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def score_gate(config, threshold=0.02):
    """Check if there's meaningful room for improvement."""
    history = config.get("history", [])
    if len(history) < 2:
        return {"pass": True, "reason": "Not enough history to evaluate"}

    recent = [h["score"] for h in history[-3:]]
    best = config.get("best_score", 0)
    target = config.get("target_score")

    # Already hit target
    if target and best >= target:
        return {"pass": False, "reason": f"Target reached: {best:.3f} >= {target}"}

    # Check if scores are plateauing (last 3 within threshold)
    if len(recent) >= 3:
        score_range = max(recent) - min(recent)
        if score_range < threshold:
            return {
                "pass": False,
                "reason": f"Plateau detected: last 3 scores within {score_range:.4f} (threshold: {threshold})",
                "suggest": "architect",
            }

    return {"pass": True, "reason": f"Score delta exists: range={max(recent)-min(recent):.4f}"}


def cost_gate(config, budget_tokens=None):
    """Estimate cost of next iteration and check against budget."""
    history = config.get("history", [])
    iterations = config.get("iterations", 0)
    estimated_cost = config.get("iteration_costs", {})

    if not estimated_cost and iterations == 0:
        return {"pass": True, "reason": "First iteration, no cost data yet"}

    total_spent = sum(estimated_cost.get("per_iteration", [0]))
    budget = budget_tokens or estimated_cost.get("budget_tokens")

    if not budget:
        return {"pass": True, "reason": "No budget configured"}

    avg_cost = total_spent / max(iterations, 1)
    remaining = budget - total_spent

    if remaining < avg_cost * 0.5:
        return {
            "pass": False,
            "reason": f"Budget nearly exhausted: {remaining:,} tokens remaining, avg iteration costs {avg_cost:,.0f}",
        }

    return {"pass": True, "reason": f"Budget OK: {remaining:,} tokens remaining"}


def convergence_gate(config, min_improvement=0.005, lookback=5):
    """Detect statistical convergence using diminishing returns."""
    history = config.get("history", [])
    if len(history) < 3:
        return {"pass": True, "reason": "Not enough iterations for convergence analysis"}

    recent = history[-lookback:] if len(history) >= lookback else history
    deltas = []
    for i in range(1, len(recent)):
        deltas.append(recent[i]["score"] - recent[i - 1]["score"])

    if not deltas:
        return {"pass": True, "reason": "No deltas to analyze"}

    avg_delta = sum(deltas) / len(deltas)
    positive_deltas = [d for d in deltas if d > 0]
    improvement_rate = len(positive_deltas) / len(deltas)

    if avg_delta < min_improvement and improvement_rate < 0.4:
        return {
            "pass": False,
            "reason": f"Converged: avg delta={avg_delta:.4f}, improvement rate={improvement_rate:.0%}",
            "suggest": "architect" if improvement_rate < 0.2 else "continue_cautious",
        }

    return {
        "pass": True,
        "reason": f"Still improving: avg delta={avg_delta:.4f}, improvement rate={improvement_rate:.0%}",
    }


def main():
    parser = argparse.ArgumentParser(description="Three-gate iteration trigger")
    parser.add_argument("--config", default=".evolver.json", help="Config path")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--score-threshold", type=float, default=0.02, help="Score plateau threshold")
    parser.add_argument("--budget-tokens", type=int, default=None, help="Token budget override")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    gates = {
        "score": score_gate(config, args.score_threshold),
        "cost": cost_gate(config, args.budget_tokens),
        "convergence": convergence_gate(config),
    }

    all_pass = all(g["pass"] for g in gates.values())
    suggestions = [g.get("suggest") for g in gates.values() if g.get("suggest")]

    result = {
        "proceed": all_pass,
        "gates": gates,
        "suggestions": suggestions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    output = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    print(output)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test iteration_gate.py runs**

Run:
```bash
$EVOLVER_PY tools/iteration_gate.py --help
```
Expected: help output with `--config`, `--output`, `--score-threshold`, `--budget-tokens`.

- [ ] **Step 3: Add gate check to evolve skill loop**

In `skills/evolve/SKILL.md`, replace the stop conditions at lines 371-375 with:

```markdown
### 8. Gate Check (Three-Gate Trigger)

Before starting the next iteration, run the gate check:

\`\`\`bash
GATE_RESULT=$($EVOLVER_PY $TOOLS/iteration_gate.py --config .evolver.json 2>/dev/null)
PROCEED=$(echo "$GATE_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('proceed', True))")
\`\`\`

If `PROCEED` is `False`, check suggestions:

\`\`\`bash
SUGGEST=$(echo "$GATE_RESULT" | python3 -c "import sys,json; s=json.load(sys.stdin).get('suggestions',[]); print(s[0] if s else '')")
\`\`\`

- If `$SUGGEST` is `architect`: auto-trigger architect agent (Step 7)
- If `$SUGGEST` is `continue_cautious`: ask user via AskUserQuestion whether to continue
- Otherwise: stop the loop and report final results

Legacy stop conditions still apply:
- **Target**: `score >= target_score` → stop
- **N reached**: all requested iterations done → stop
```

- [ ] **Step 4: Add target_score to .evolver.json during interactive config**

In `skills/evolve/SKILL.md`, after the interactive AskUserQuestion at lines 31-60, add logic to write the target score:

```markdown
Write the target to `.evolver.json` for gate checks:

\`\`\`bash
python3 -c "
import json
c = json.load(open('.evolver.json'))
c['target_score'] = {target_score_float}  # parsed from user selection, or None for 'No limit'
json.dump(c, open('.evolver.json', 'w'), indent=2)
"
\`\`\`
```

- [ ] **Step 5: Commit**

```bash
git add tools/iteration_gate.py skills/evolve/SKILL.md
git commit -m "feat: add three-gate iteration triggers (score, cost, convergence)"
```

---

## Phase 2: Evolution Memory

### Task 3: Regression Tracker (Feature 7)

Replace the stub at `skills/evolve/SKILL.md:301-319` with a real regression tracking tool.

**Files:**
- Create: `tools/regression_tracker.py`
- Modify: `skills/evolve/SKILL.md:301-319` (replace stub)

- [ ] **Step 1: Create `tools/regression_tracker.py`**

```python
#!/usr/bin/env python3
"""Track regression examples across evolution iterations.

Compares per-example scores between consecutive iterations.
When an example transitions from failing (<0.5) to passing (>0.8),
adds a variation to the dataset as a regression guard.

Usage:
    python3 regression_tracker.py \
        --config .evolver.json \
        --previous-experiment v001a \
        --current-experiment v002c \
        --output regression_report.json
"""

import argparse
import json
import os
import platform
import sys


def ensure_langsmith_api_key():
    """Load LANGSMITH_API_KEY from credentials file or .env if not in env."""
    if os.environ.get("LANGSMITH_API_KEY"):
        return True
    if platform.system() == "Darwin":
        creds_path = os.path.expanduser("~/Library/Application Support/langsmith-cli/credentials")
    else:
        creds_path = os.path.expanduser("~/.config/langsmith-cli/credentials")
    if os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    if os.path.exists(".env"):
        try:
            with open(".env") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY=") and not line.startswith("#"):
                        key = line.split("=", 1)[1].strip().strip("'\"")
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    return False


def get_per_example_scores(client, experiment_name):
    """Get per-example scores from an experiment."""
    scores = {}
    try:
        runs = list(client.list_runs(project_name=experiment_name, is_root=True, limit=200))
        for run in runs:
            example_id = str(run.reference_example_id or run.id)
            feedbacks = list(client.list_feedback(run_ids=[run.id]))
            fb_scores = {}
            for fb in feedbacks:
                if fb.score is not None:
                    fb_scores[fb.key] = fb.score
            avg = sum(fb_scores.values()) / len(fb_scores) if fb_scores else 0.0
            scores[example_id] = {
                "score": avg,
                "input": str(run.inputs)[:500] if run.inputs else "",
                "output": str(run.outputs)[:500] if run.outputs else "",
            }
    except Exception as e:
        print(f"Error reading {experiment_name}: {e}", file=sys.stderr)
    return scores


def find_transitions(prev_scores, curr_scores, fail_threshold=0.5, pass_threshold=0.8):
    """Find examples that transitioned from failing to passing."""
    transitions = []
    regressions = []

    for example_id in set(prev_scores) & set(curr_scores):
        prev = prev_scores[example_id]["score"]
        curr = curr_scores[example_id]["score"]

        if prev < fail_threshold and curr >= pass_threshold:
            transitions.append({
                "example_id": example_id,
                "prev_score": prev,
                "curr_score": curr,
                "type": "fixed",
                "input": curr_scores[example_id]["input"],
            })
        elif prev >= pass_threshold and curr < fail_threshold:
            regressions.append({
                "example_id": example_id,
                "prev_score": prev,
                "curr_score": curr,
                "type": "regressed",
                "input": curr_scores[example_id]["input"],
            })

    return transitions, regressions


def add_regression_guards(client, dataset_id, transitions, max_guards=5):
    """Add regression guard examples to the dataset."""
    added = 0
    for t in transitions[:max_guards]:
        try:
            input_data = json.loads(t["input"]) if t["input"].startswith("{") else {"input": t["input"]}
            client.create_example(
                inputs=input_data,
                dataset_id=dataset_id,
                metadata={"source": "regression_guard", "original_example_id": t["example_id"]},
            )
            added += 1
        except Exception as e:
            print(f"Failed to add guard for {t['example_id']}: {e}", file=sys.stderr)
    return added


def main():
    parser = argparse.ArgumentParser(description="Track regressions across iterations")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--previous-experiment", required=True, help="Previous iteration experiment name")
    parser.add_argument("--current-experiment", required=True, help="Current iteration experiment name")
    parser.add_argument("--output", default=None, help="Output JSON report")
    parser.add_argument("--add-guards", action="store_true", help="Add regression guard examples to dataset")
    parser.add_argument("--max-guards", type=int, default=5, help="Max guard examples to add")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    ensure_langsmith_api_key()
    from langsmith import Client
    client = Client()

    prev_scores = get_per_example_scores(client, args.previous_experiment)
    curr_scores = get_per_example_scores(client, args.current_experiment)

    transitions, regressions = find_transitions(prev_scores, curr_scores)

    added = 0
    if args.add_guards and transitions:
        added = add_regression_guards(client, config["dataset_id"], transitions, args.max_guards)

    result = {
        "previous": args.previous_experiment,
        "current": args.current_experiment,
        "fixed_count": len(transitions),
        "regression_count": len(regressions),
        "guards_added": added,
        "fixed": transitions,
        "regressions": regressions,
    }

    output = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    print(output)

    if regressions:
        print(f"\nWARNING: {len(regressions)} regressions detected!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test regression_tracker.py runs**

Run:
```bash
$EVOLVER_PY tools/regression_tracker.py --help
```
Expected: help output with all flags.

- [ ] **Step 3: Replace stub in evolve skill**

In `skills/evolve/SKILL.md`, replace lines 301-319 (the `### 5.5. Test Suite Growth` section) with:

```markdown
### 5.5. Regression Tracking & Test Suite Growth

If this is not the first iteration (previous experiment exists), track regressions and auto-add guards:

\`\`\`bash
PREV_EXP=$(python3 -c "
import json
h = json.load(open('.evolver.json')).get('history', [])
print(h[-2]['experiment'] if len(h) >= 2 else '')
")
if [ -n "$PREV_EXP" ]; then
    $EVOLVER_PY $TOOLS/regression_tracker.py \
        --config .evolver.json \
        --previous-experiment "$PREV_EXP" \
        --current-experiment "{winner_experiment}" \
        --add-guards --max-guards 5 \
        --output regression_report.json 2>/dev/null
    
    # Report regressions
    python3 -c "
import json, os
if os.path.exists('regression_report.json'):
    r = json.load(open('regression_report.json'))
    if r['regression_count'] > 0:
        print(f'⚠ {r[\"regression_count\"]} regressions detected')
    if r['guards_added'] > 0:
        print(f'  Added {r[\"guards_added\"]} regression guard examples to dataset')
    if r['fixed_count'] > 0:
        print(f'  {r[\"fixed_count\"]} previously-failing examples now pass')
" 2>/dev/null
fi
\`\`\`
```

- [ ] **Step 4: Commit**

```bash
git add tools/regression_tracker.py skills/evolve/SKILL.md
git commit -m "feat: add regression tracking with auto-guard example injection"
```

---

### Task 4: autoConsolidate (Feature 1)

Cross-iteration memory consolidation inspired by Claude Code's autoDream. Four phases: orient → gather → consolidate → prune.

**Files:**
- Create: `tools/consolidate.py`
- Create: `agents/evolver-consolidator.md`
- Modify: `skills/evolve/SKILL.md` (add consolidation after each iteration)

- [ ] **Step 1: Create `tools/consolidate.py`**

```python
#!/usr/bin/env python3
"""Cross-iteration memory consolidation for Harness Evolver.

Inspired by Claude Code's autoDream pattern. Analyzes evolution history
to identify recurring patterns, successful strategies, and wasted approaches.
Produces evolution_memory.md for proposer briefings.

Usage:
    python3 consolidate.py --config .evolver.json --output evolution_memory.md
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def orient(config):
    """Phase 1: Scan current state and history."""
    history = config.get("history", [])
    iterations = config.get("iterations", 0)
    best_score = config.get("best_score", 0)
    baseline_score = history[0]["score"] if history else 0

    return {
        "iterations": iterations,
        "best_score": best_score,
        "baseline_score": baseline_score,
        "improvement": best_score - baseline_score,
        "history": history,
    }


def gather(config, comparison_files):
    """Phase 2: Extract signals from trace insights and comparisons."""
    signals = {
        "winning_strategies": [],
        "losing_strategies": [],
        "recurring_failures": {},
        "score_deltas": [],
    }

    for comp_file in comparison_files:
        if not os.path.exists(comp_file):
            continue
        try:
            with open(comp_file) as f:
                data = json.load(f)
            comparison = data.get("comparison", data)

            winner = comparison.get("winner", {})
            if winner:
                signals["winning_strategies"].append({
                    "experiment": winner.get("experiment", ""),
                    "score": winner.get("score", 0),
                })

            for candidate in comparison.get("all_candidates", []):
                if candidate.get("experiment") != winner.get("experiment"):
                    signals["losing_strategies"].append({
                        "experiment": candidate.get("experiment", ""),
                        "score": candidate.get("score", 0),
                    })
        except (json.JSONDecodeError, OSError):
            continue

    # Compute score deltas from history
    history = config.get("history", [])
    for i in range(1, len(history)):
        signals["score_deltas"].append({
            "version": history[i]["version"],
            "delta": history[i]["score"] - history[i - 1]["score"],
            "score": history[i]["score"],
        })

    # Read trace insights for recurring patterns
    if os.path.exists("trace_insights.json"):
        try:
            with open("trace_insights.json") as f:
                insights = json.load(f)
            for issue in insights.get("top_issues", []):
                pattern = issue.get("pattern", issue.get("description", "unknown"))
                if pattern not in signals["recurring_failures"]:
                    signals["recurring_failures"][pattern] = 0
                signals["recurring_failures"][pattern] += 1
        except (json.JSONDecodeError, OSError):
            pass

    return signals


def consolidate(orientation, signals, existing_memory=None):
    """Phase 3: Merge signals into consolidated memory."""
    insights = []

    # Strategy effectiveness
    winning = signals.get("winning_strategies", [])
    losing = signals.get("losing_strategies", [])

    win_suffixes = [w["experiment"][-1] for w in winning if w.get("experiment")]
    strategy_map = {"a": "exploit", "b": "explore", "c": "crossover", "d": "failure-targeted-1", "e": "failure-targeted-2"}
    win_counts = {}
    for s in win_suffixes:
        name = strategy_map.get(s, s)
        win_counts[name] = win_counts.get(name, 0) + 1

    if win_counts:
        best_strategy = max(win_counts, key=win_counts.get)
        insights.append({
            "type": "strategy_effectiveness",
            "insight": f"Most winning strategy: {best_strategy} ({win_counts[best_strategy]} wins)",
            "recurrence": win_counts[best_strategy],
            "data": win_counts,
        })

    # Recurring failures (only promote if seen 2+ times)
    recurring = {k: v for k, v in signals.get("recurring_failures", {}).items() if v >= 2}
    for pattern, count in sorted(recurring.items(), key=lambda x: -x[1]):
        insights.append({
            "type": "recurring_failure",
            "insight": f"Recurring failure ({count}x): {pattern}",
            "recurrence": count,
        })

    # Score trajectory
    deltas = signals.get("score_deltas", [])
    if deltas:
        positive = [d for d in deltas if d["delta"] > 0]
        negative = [d for d in deltas if d["delta"] < 0]
        stagnant = [d for d in deltas if abs(d["delta"]) < 0.01]
        insights.append({
            "type": "trajectory",
            "insight": f"Score trajectory: {len(positive)} improvements, {len(negative)} regressions, {len(stagnant)} stagnant",
            "recurrence": len(deltas),
        })

    # Merge with existing memory (update recurrence counts)
    if existing_memory:
        for existing in existing_memory.get("insights", []):
            found = False
            for new in insights:
                if new["type"] == existing["type"] and new["insight"] == existing["insight"]:
                    new["recurrence"] = max(new["recurrence"], existing.get("recurrence", 1)) + 1
                    found = True
                    break
            if not found and existing.get("recurrence", 1) >= 2:
                insights.append(existing)

    return insights


def prune(insights, max_insights=20):
    """Phase 4: Cap size, remove stale entries."""
    # Sort by recurrence (higher = more important)
    sorted_insights = sorted(insights, key=lambda x: -x.get("recurrence", 1))
    return sorted_insights[:max_insights]


def format_memory(orientation, insights):
    """Format consolidated memory as markdown."""
    lines = [
        "# Evolution Memory",
        "",
        f"*Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        f"*Iterations: {orientation['iterations']} | Best: {orientation['best_score']:.3f} | Baseline: {orientation['baseline_score']:.3f} | Improvement: +{orientation['improvement']:.3f}*",
        "",
        "## Key Insights (promoted after 2+ recurrences)",
        "",
    ]

    promoted = [i for i in insights if i.get("recurrence", 1) >= 2]
    other = [i for i in insights if i.get("recurrence", 1) < 2]

    if promoted:
        for insight in promoted:
            lines.append(f"- **[{insight['type']}]** {insight['insight']} (seen {insight['recurrence']}x)")
    else:
        lines.append("- No insights promoted yet (need 2+ recurrences)")

    if other:
        lines.append("")
        lines.append("## Observations (1 recurrence, pending promotion)")
        lines.append("")
        for insight in other:
            lines.append(f"- [{insight['type']}] {insight['insight']}")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Cross-iteration memory consolidation")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--output", default="evolution_memory.md", help="Output markdown path")
    parser.add_argument("--output-json", default="evolution_memory.json", help="Output JSON path")
    parser.add_argument("--comparison-files", nargs="*", default=[], help="Past comparison.json files")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    # Load existing memory if present
    existing = None
    if os.path.exists(args.output_json):
        try:
            with open(args.output_json) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Four-phase consolidation
    orientation = orient(config)
    signals = gather(config, args.comparison_files or ["comparison.json"])
    insights = consolidate(orientation, signals, existing)
    insights = prune(insights)

    # Write markdown
    memory_md = format_memory(orientation, insights)
    with open(args.output, "w") as f:
        f.write(memory_md)

    # Write JSON for programmatic access
    memory_json = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "orientation": orientation,
        "insights": insights,
    }
    with open(args.output_json, "w") as f:
        json.dump(memory_json, f, indent=2)

    print(memory_md)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test consolidate.py runs**

Run:
```bash
$EVOLVER_PY tools/consolidate.py --help
```
Expected: help output with `--config`, `--output`, `--output-json`, `--comparison-files`.

- [ ] **Step 3: Create `agents/evolver-consolidator.md`**

```markdown
---
name: evolver-consolidator
description: |
  Background agent for cross-iteration memory consolidation.
  Runs after each iteration to extract learnings and update evolution_memory.md.
  Read-only analysis — does not modify agent code.
tools: Read, Bash, Glob, Grep
color: cyan
---

# Evolver — Consolidator Agent

You are a memory consolidation agent inspired by Claude Code's autoDream pattern. Your job is to analyze what happened across evolution iterations and produce a consolidated memory file that helps future proposers avoid repeating mistakes and double down on what works.

## Bootstrap

Read files listed in `<files_to_read>` before doing anything else.

## Four-Phase Process

### Phase 1: Orient
Read `.evolver.json` history and `evolution_memory.md` (if exists) to understand:
- How many iterations have run
- Score trajectory (improving, stagnating, regressing?)
- What insights already exist

### Phase 2: Gather
Read `comparison.json`, `trace_insights.json`, `regression_report.json`, and any `proposal.md` files in recent worktrees to extract:
- Which proposer strategy won this iteration (exploit/explore/crossover/failure-targeted)
- What failure patterns persist across iterations
- What approaches were tried and failed
- What regressions occurred

### Phase 3: Consolidate
Merge new signals with existing memory:
- Update recurrence counts for repeated patterns
- Resolve contradictions (newer information wins)
- Promote insights seen 2+ times to "Key Insights"
- Demote insights that haven't recurred

### Phase 4: Prune
- Cap at 20 insights max
- Remove insights with 0 recurrence after 3 iterations
- Keep the markdown under 2KB

## Constraints

- **Read-only**: Do not modify agent code, only produce `evolution_memory.md` and `evolution_memory.json`
- **No tool invocation**: Use Bash only for `cat`, `ls`, `grep` — read-only commands
- **Be concise**: Each insight should be one line, actionable

## Return Protocol

## CONSOLIDATION COMPLETE
- **Insights promoted**: {N} (seen 2+ times)
- **Observations pending**: {N} (seen 1 time)
- **Top insight**: {most impactful pattern}
```

- [ ] **Step 4: Add consolidation step to evolve skill**

In `skills/evolve/SKILL.md`, insert after Step 6 (Report) at line 323, before Step 6.5:

```markdown
### 6.2. Consolidate Evolution Memory

Run the consolidation tool to update cross-iteration memory:

\`\`\`bash
$EVOLVER_PY $TOOLS/consolidate.py \
    --config .evolver.json \
    --comparison-files comparison.json \
    --output evolution_memory.md \
    --output-json evolution_memory.json 2>/dev/null
\`\`\`

The `evolution_memory.md` file will be included in proposer briefings for subsequent iterations.
```

- [ ] **Step 5: Update proposer prompt to include evolution memory**

In `skills/evolve/SKILL.md`, in the proposer Agent() call at line 144 (`<files_to_read>` section), add:

```
    - evolution_memory.md (if exists)
```

So the `<files_to_read>` block becomes:
```
    <files_to_read>
    - .evolver.json
    - trace_insights.json (if exists)
    - production_seed.json (if exists)
    - best_results.json (if exists)
    - evolution_memory.md (if exists)
    - {entry point file from .evolver.json}
    </files_to_read>
```

- [ ] **Step 6: Commit**

```bash
git add tools/consolidate.py agents/evolver-consolidator.md skills/evolve/SKILL.md
git commit -m "feat: add autoConsolidate cross-iteration memory system"
```

---

## Phase 3: Proposer Optimization

### Task 5: KV Cache-Optimized Proposer Spawning (Feature 2)

Restructure the 5 proposer prompts to share a large common prefix, with only the strategy as differentiated suffix. This maximizes prompt cache hits.

**Files:**
- Modify: `skills/evolve/SKILL.md:120-179` (restructure proposer spawning)

- [ ] **Step 1: Extract shared context into a variable block**

In `skills/evolve/SKILL.md`, before the `### 2. Spawn 5 Proposers in Parallel` section (line 120), add a shared context preparation block:

```markdown
### 1.9. Prepare Shared Proposer Context

Build the shared context that ALL proposers will receive as an identical prefix. This enables KV cache sharing — spawning 5 proposers costs barely more than 1.

\`\`\`bash
# Build shared context block (identical for all 5 proposers)
SHARED_FILES_BLOCK="<files_to_read>
- .evolver.json
- trace_insights.json (if exists)
- production_seed.json (if exists)
- best_results.json (if exists)
- evolution_memory.md (if exists)
- {entry_point_file}
</files_to_read>"

SHARED_CONTEXT_BLOCK="<context>
Best experiment: {best_experiment} (score: {best_score})
Framework: {framework}
Entry point: {entry_point}
Evaluators: {evaluators}
Iteration: {iteration_number} of {total_iterations}
Score history: {score_history_summary}
</context>"

SHARED_OBJECTIVE="<objective>
Improve the agent code to score higher on the evaluation dataset.
You are working in an isolated git worktree — modify any file freely.
</objective>"
\`\`\`

**CRITICAL for cache sharing**: The `<objective>`, `<files_to_read>`, and `<context>` blocks MUST be byte-identical across all 5 proposer prompts. Only the `<strategy>` block differs. Place the strategy block LAST in the prompt so the shared prefix is maximized.
```

- [ ] **Step 2: Restructure proposer calls to use shared prefix**

Replace the proposer Agent() calls (lines 124-178) with this pattern where shared content comes first and strategy-specific content comes last:

```markdown
### 2. Spawn 5 Proposers in Parallel

Each proposer receives the IDENTICAL prefix (objective + files + context) followed by its unique strategy suffix.

**All 5 candidates** — `run_in_background: true, isolation: "worktree"`:

The prompt for EACH proposer follows this structure:
\`\`\`
{SHARED_OBJECTIVE}

{SHARED_FILES_BLOCK}

{SHARED_CONTEXT_BLOCK}

<strategy>
{UNIQUE PER CANDIDATE — see below}
</strategy>

<output>
1. Modify the code to improve performance
2. Commit your changes with a descriptive message
3. Write proposal.md explaining what you changed and why
</output>
\`\`\`

**Candidate A strategy block:**
\`\`\`
APPROACH: exploitation
Make targeted improvements to the current best version.
Focus on the specific failures identified in the results.
\`\`\`

**Candidate B strategy block:**
\`\`\`
APPROACH: exploration
Try a fundamentally different approach. Change algorithms, prompts, routing, architecture.
Don't be afraid to make big changes — this worktree is disposable.
\`\`\`

**Candidate C strategy block:**
\`\`\`
APPROACH: crossover
Combine strengths from previous iterations. Check git log for what was tried.
Recent changes: {git_log_last_5}
\`\`\`

**Candidate D strategy block:**
\`\`\`
APPROACH: {failure_targeted_or_creative}
{adaptive_briefing_d}
\`\`\`

**Candidate E strategy block:**
\`\`\`
APPROACH: {failure_targeted_or_efficiency}
{adaptive_briefing_e}
\`\`\`

Wait for all 5 to complete.
```

- [ ] **Step 3: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: restructure proposer prompts for KV cache sharing"
```

---

### Task 6: Per-Proposer Tool Restrictions (Feature 8)

Customize tool access per proposer strategy to prevent overreach.

**Files:**
- Modify: `skills/evolve/SKILL.md` (add tool restrictions to Agent() calls)
- Modify: `agents/evolver-proposer.md` (document restrictions)

- [ ] **Step 1: Add tool restriction rules to proposer Agent() calls**

In the evolve skill's proposer spawning section, add tool restriction comments per candidate:

```markdown
**Tool restrictions per strategy:**

| Strategy | Allowed Tools | Rationale |
|----------|--------------|-----------|
| Exploit (A) | Read, Edit, Bash, Glob, Grep | No Write — can't create new files, only edit existing |
| Explore (B) | Read, Write, Edit, Bash, Glob, Grep | Full access — may need new files for new architecture |
| Crossover (C) | Read, Edit, Bash, Glob, Grep | No Write — combines existing patterns, doesn't create |
| Failure-targeted (D, E) | Read, Edit, Bash, Glob, Grep | No Write — focused fixes on specific files |

Apply via the `tools` parameter in each Agent() call. Example for exploit:
\`\`\`
Agent(
  subagent_type: "evolver-proposer",
  tools: ["Read", "Edit", "Bash", "Glob", "Grep"],
  ...
)
\`\`\`

For explore:
\`\`\`
Agent(
  subagent_type: "evolver-proposer",
  tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
  ...
)
\`\`\`
```

- [ ] **Step 2: Document tool restrictions in proposer agent**

In `agents/evolver-proposer.md`, add after the Rules section (line 136):

```markdown
## Tool Restrictions

Your available tools may be restricted based on your strategy:
- **Exploit/Crossover/Failure-targeted**: Edit-only (no Write). Focus on modifying existing files.
- **Explore**: Full access including Write. You may create new files if your approach requires it.

If you need to create a file but only have Edit, restructure your approach to modify existing files instead.
```

- [ ] **Step 3: Commit**

```bash
git add skills/evolve/SKILL.md agents/evolver-proposer.md
git commit -m "feat: add per-proposer tool restrictions by strategy"
```

---

### Task 7: Proposer Compaction Pipeline (Feature 5)

Prevent context overflow in proposers working on large projects.

**Files:**
- Modify: `agents/evolver-proposer.md` (add turn limits and compaction instructions)
- Modify: `skills/evolve/SKILL.md` (add stuck proposer detection)

- [ ] **Step 1: Add turn management to proposer agent**

In `agents/evolver-proposer.md`, add after the Bootstrap section (after line 22):

```markdown
## Turn Budget

You have a maximum of **16 turns** to complete your proposal. Budget them:
- Turns 1-3: Orient (read files, understand codebase)
- Turns 4-6: Diagnose (read insights, identify targets)
- Turns 7-12: Implement (make changes, consult docs)
- Turns 13-14: Test (verify changes don't break the entry point)
- Turns 15-16: Commit and document

**If you're past turn 12 and haven't started implementing**, simplify your approach. A small, focused change that works is better than an ambitious change that's incomplete.

**Context management**: After turn 8, avoid re-reading files you've already read. Reference your earlier analysis instead of re-running Glob/Grep searches.
```

- [ ] **Step 2: Add stuck proposer detection to evolve skill**

In `skills/evolve/SKILL.md`, after "Wait for all 5 to complete" (line 179), add:

```markdown
**Stuck proposer detection**: If any proposer hasn't completed after 10 minutes, it may be stuck in a loop. The Claude Code runtime handles this via the agent's turn limit. If a proposer returns without committing changes, skip it — don't retry.

After all proposers complete, check which ones actually committed:

\`\`\`bash
for WORKTREE in {worktree_paths}; do
    CHANGES=$(cd "$WORKTREE" && git log --oneline -1 --since="10 minutes ago" 2>/dev/null | wc -l)
    if [ "$CHANGES" -eq 0 ]; then
        echo "Proposer in $WORKTREE made no commits — skipping"
    fi
done
\`\`\`

Only run evaluation (Step 3) for proposers that committed changes.
```

- [ ] **Step 3: Commit**

```bash
git add agents/evolver-proposer.md skills/evolve/SKILL.md
git commit -m "feat: add proposer turn budget and stuck detection"
```

---

## Phase 4: Agent Intelligence

### Task 8: Coordinator Synthesis Phase (Feature 6)

Add explicit synthesis step between trace analysis and proposer spawning. The evolve skill synthesizes specific implementation specs instead of delegating raw data to proposers.

**Files:**
- Create: `tools/synthesize_strategy.py`
- Modify: `skills/evolve/SKILL.md` (add synthesis step between 1.8 and 2)

- [ ] **Step 1: Create `tools/synthesize_strategy.py`**

```python
#!/usr/bin/env python3
"""Synthesize evolution strategy document from trace analysis.

Reads trace_insights.json, best_results.json, and evolution_memory.json
to produce a targeted strategy document with specific file paths,
line numbers, and concrete change recommendations for proposers.

Usage:
    python3 synthesize_strategy.py \
        --config .evolver.json \
        --trace-insights trace_insights.json \
        --best-results best_results.json \
        --evolution-memory evolution_memory.json \
        --output strategy.md
"""

import argparse
import json
import os
import sys


def load_json_safe(path):
    """Load JSON file, return None if missing or invalid."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def identify_target_files(config):
    """Identify which files proposers should focus on."""
    entry_point = config.get("entry_point", "")
    # Extract the file path from entry point command
    parts = entry_point.split()
    target_files = []
    for part in parts:
        if part.endswith(".py") and not part.startswith("-"):
            target_files.append(part)
    return target_files


def synthesize(config, insights, results, memory):
    """Produce strategy recommendations."""
    strategy = {
        "primary_targets": [],
        "failure_clusters": [],
        "recommended_approaches": [],
        "avoid": [],
    }

    # Primary targets from entry point
    target_files = identify_target_files(config)
    strategy["primary_targets"] = target_files

    # Failure clusters from trace insights
    if insights:
        for issue in insights.get("top_issues", [])[:5]:
            strategy["failure_clusters"].append({
                "type": issue.get("type", "unknown"),
                "severity": issue.get("severity", "medium"),
                "description": issue.get("description", ""),
                "count": issue.get("count", 0),
            })

    # Recommended approaches from evolution memory
    if memory:
        for insight in memory.get("insights", []):
            if insight.get("recurrence", 0) >= 2:
                if insight["type"] == "strategy_effectiveness":
                    strategy["recommended_approaches"].append(insight["insight"])
                elif insight["type"] == "recurring_failure":
                    strategy["failure_clusters"].append({
                        "type": "recurring",
                        "severity": "high",
                        "description": insight["insight"],
                        "count": insight["recurrence"],
                    })

    # What to avoid from memory
    if memory:
        for insight in memory.get("insights", []):
            if "losing" in insight.get("type", "") or "regression" in insight.get("type", ""):
                strategy["avoid"].append(insight["insight"])

    # Failing examples from results
    if results:
        per_example = results.get("per_example", {})
        failing = [(eid, data) for eid, data in per_example.items() if data.get("score", 0) < 0.5]
        failing.sort(key=lambda x: x[1].get("score", 0))
        strategy["failing_examples"] = [
            {
                "example_id": eid,
                "score": data["score"],
                "input_preview": data.get("input_preview", "")[:200],
                "error": data.get("error"),
            }
            for eid, data in failing[:10]
        ]

    return strategy


def format_strategy_md(strategy, config):
    """Format strategy as markdown document."""
    lines = [
        "# Evolution Strategy Document",
        "",
        f"*Framework: {config.get('framework', 'unknown')} | Entry point: {config.get('entry_point', 'N/A')}*",
        "",
    ]

    # Primary targets
    lines.append("## Target Files")
    for f in strategy.get("primary_targets", []):
        lines.append(f"- `{f}`")
    lines.append("")

    # Failure clusters
    clusters = strategy.get("failure_clusters", [])
    if clusters:
        lines.append("## Failure Clusters (prioritized)")
        for i, c in enumerate(clusters, 1):
            lines.append(f"{i}. **[{c['severity']}]** {c['description']} (count: {c['count']})")
        lines.append("")

    # Recommended approaches
    approaches = strategy.get("recommended_approaches", [])
    if approaches:
        lines.append("## Recommended Approaches (from evolution memory)")
        for a in approaches:
            lines.append(f"- {a}")
        lines.append("")

    # What to avoid
    avoid = strategy.get("avoid", [])
    if avoid:
        lines.append("## Avoid (previously unsuccessful)")
        for a in avoid:
            lines.append(f"- {a}")
        lines.append("")

    # Failing examples
    failing = strategy.get("failing_examples", [])
    if failing:
        lines.append(f"## Top Failing Examples ({len(failing)})")
        for ex in failing:
            score = ex["score"]
            preview = ex["input_preview"][:100]
            error = f" — Error: {ex['error'][:80]}" if ex.get("error") else ""
            lines.append(f"- `{ex['example_id']}` (score: {score:.2f}): {preview}{error}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Synthesize evolution strategy")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--trace-insights", default="trace_insights.json")
    parser.add_argument("--best-results", default="best_results.json")
    parser.add_argument("--evolution-memory", default="evolution_memory.json")
    parser.add_argument("--output", default="strategy.md")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    insights = load_json_safe(args.trace_insights)
    results = load_json_safe(args.best_results)
    memory = load_json_safe(args.evolution_memory)

    strategy = synthesize(config, insights, results, memory)

    md = format_strategy_md(strategy, config)
    with open(args.output, "w") as f:
        f.write(md)

    # Also output JSON for programmatic use
    json_path = args.output.replace(".md", ".json")
    with open(json_path, "w") as f:
        json.dump(strategy, f, indent=2)

    print(md)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test synthesize_strategy.py runs**

Run:
```bash
$EVOLVER_PY tools/synthesize_strategy.py --help
```
Expected: help output with all flags.

- [ ] **Step 3: Add synthesis step to evolve skill**

In `skills/evolve/SKILL.md`, insert between Step 1.8 (line 118) and Step 2 (line 120):

```markdown
### 1.9a. Synthesize Strategy

Generate a targeted strategy document from all available analysis:

\`\`\`bash
$EVOLVER_PY $TOOLS/synthesize_strategy.py \
    --config .evolver.json \
    --trace-insights trace_insights.json \
    --best-results best_results.json \
    --evolution-memory evolution_memory.json \
    --output strategy.md 2>/dev/null
\`\`\`

Include `strategy.md` in the proposer `<files_to_read>` block. This replaces raw data dumps with a synthesized, actionable document — proposers receive specific targets, not raw traces.
```

- [ ] **Step 4: Add strategy.md to proposer files_to_read**

In the proposer Agent() prompt's `<files_to_read>` block, add `strategy.md`:

```
    <files_to_read>
    - .evolver.json
    - strategy.md (if exists)
    - evolution_memory.md (if exists)
    - {entry point file from .evolver.json}
    </files_to_read>
```

Remove `trace_insights.json`, `production_seed.json`, and `best_results.json` from `<files_to_read>` — their content is now synthesized into `strategy.md`.

- [ ] **Step 5: Commit**

```bash
git add tools/synthesize_strategy.py skills/evolve/SKILL.md
git commit -m "feat: add coordinator synthesis phase with strategy document generation"
```

---

### Task 9: Active Critic (Feature 3)

Upgrade the critic from a passive reporter to an active agent that implements stricter evaluators when gaming is detected.

**Files:**
- Create: `tools/add_evaluator.py`
- Modify: `agents/evolver-critic.md` (add evaluator generation)
- Modify: `skills/evolve/SKILL.md:325-347` (change critic trigger to handle evaluator updates)

- [ ] **Step 1: Create `tools/add_evaluator.py`**

```python
#!/usr/bin/env python3
"""Add a new evaluator to .evolver.json configuration.

Used by the active critic to programmatically strengthen evaluation
when gaming is detected.

Usage:
    python3 add_evaluator.py --config .evolver.json --evaluator factual_accuracy --type llm
    python3 add_evaluator.py --config .evolver.json --evaluator regex_check --type code --pattern "\\d{4}"
"""

import argparse
import json
import sys


CODE_EVALUATOR_TEMPLATES = {
    "no_hallucination_markers": {
        "description": "Check output doesn't contain hallucination markers",
        "check": "not any(m in output for m in ['I think', 'probably', 'I believe', 'not sure'])",
    },
    "answer_not_question": {
        "description": "Check output doesn't just repeat the input question",
        "check": "output.strip().lower() != input_text.strip().lower()",
    },
    "min_length": {
        "description": "Check output meets minimum length",
        "check": "len(output.strip()) >= 20",
    },
    "no_repetition": {
        "description": "Check output doesn't have excessive repetition",
        "check": "len(set(output.split())) / max(len(output.split()), 1) > 0.3",
    },
}


def add_evaluator(config_path, evaluator_name, eval_type, pattern=None):
    """Add evaluator to config."""
    with open(config_path) as f:
        config = json.load(f)

    evaluators = config.get("evaluators", [])

    if evaluator_name in evaluators:
        print(f"Evaluator '{evaluator_name}' already exists", file=sys.stderr)
        return False

    evaluators.append(evaluator_name)
    config["evaluators"] = evaluators

    # Store code evaluator details if applicable
    if eval_type == "code" and pattern:
        code_evals = config.get("code_evaluators", {})
        code_evals[evaluator_name] = {"pattern": pattern, "type": "regex"}
        config["code_evaluators"] = code_evals
    elif eval_type == "code" and evaluator_name in CODE_EVALUATOR_TEMPLATES:
        code_evals = config.get("code_evaluators", {})
        code_evals[evaluator_name] = CODE_EVALUATOR_TEMPLATES[evaluator_name]
        config["code_evaluators"] = code_evals

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return True


def main():
    parser = argparse.ArgumentParser(description="Add evaluator to .evolver.json")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--evaluator", required=True, help="Evaluator name")
    parser.add_argument("--type", choices=["llm", "code"], default="llm", help="Evaluator type")
    parser.add_argument("--pattern", default=None, help="Regex pattern for code evaluators")
    parser.add_argument("--remove", action="store_true", help="Remove evaluator instead of adding")
    args = parser.parse_args()

    if args.remove:
        with open(args.config) as f:
            config = json.load(f)
        evaluators = config.get("evaluators", [])
        if args.evaluator in evaluators:
            evaluators.remove(args.evaluator)
            config["evaluators"] = evaluators
            with open(args.config, "w") as f:
                json.dump(config, f, indent=2)
            print(f"Removed evaluator: {args.evaluator}")
        else:
            print(f"Evaluator '{args.evaluator}' not found", file=sys.stderr)
        return

    added = add_evaluator(args.config, args.evaluator, args.type, args.pattern)
    if added:
        print(json.dumps({
            "added": args.evaluator,
            "type": args.type,
            "evaluators": json.load(open(args.config))["evaluators"],
        }, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test add_evaluator.py runs**

Run:
```bash
$EVOLVER_PY tools/add_evaluator.py --help
```
Expected: help output with `--config`, `--evaluator`, `--type`, `--pattern`, `--remove`.

- [ ] **Step 3: Upgrade critic agent to be active**

Replace the entire content of `agents/evolver-critic.md` with:

```markdown
---
name: evolver-critic
description: |
  Use this agent when scores converge suspiciously fast, evaluator quality is questionable,
  or the agent reaches high scores in few iterations. Detects gaming AND implements fixes.
tools: Read, Write, Bash, Grep, Glob
color: red
---

# Evolver — Active Critic Agent (v3.1)

You are an evaluation quality auditor AND fixer. Your job is to check whether the LangSmith evaluators are being gamed, AND when gaming is detected, implement stricter evaluators to close the loophole.

## Bootstrap

Read files listed in `<files_to_read>` before doing anything else.

## Phase 1: Detect

1. **Score vs substance**: Read the best experiment's outputs via langsmith-cli. Do high-scoring outputs actually answer correctly?

2. **Evaluator blind spots**: Check for:
   - Hallucination that sounds confident
   - Correct format but wrong content
   - Copy-pasting the question back as the answer
   - Overly verbose responses scoring well on completeness

3. **Score inflation patterns**: Compare scores across iterations from `.evolver.json` history. If scores jumped >0.3, what changed?

## Phase 2: Act (if gaming detected)

When gaming is detected, you MUST implement fixes, not just report them:

### 2a. Add code-based evaluators

Use the add_evaluator tool to add deterministic checks:

\`\`\`bash
# Add evaluator that checks output isn't just repeating the question
$EVOLVER_PY $TOOLS/add_evaluator.py \
    --config .evolver.json \
    --evaluator answer_not_question \
    --type code

# Add evaluator that checks for hallucination markers
$EVOLVER_PY $TOOLS/add_evaluator.py \
    --config .evolver.json \
    --evaluator no_hallucination_markers \
    --type code

# Add evaluator that checks minimum response quality
$EVOLVER_PY $TOOLS/add_evaluator.py \
    --config .evolver.json \
    --evaluator min_length \
    --type code
\`\`\`

Choose evaluators based on the specific gaming pattern detected.

### 2b. Document findings

Write `critic_report.md` with:
- What gaming pattern was detected
- What evaluators were added and why
- Expected impact on next iteration scores

## Phase 3: Verify

After adding evaluators, verify the config is valid:

\`\`\`bash
python3 -c "import json; c=json.load(open('.evolver.json')); print(f'Evaluators: {c[\"evaluators\"]}')"
\`\`\`

## Return Protocol

## CRITIC REPORT COMPLETE
- **Gaming detected**: yes/no
- **Severity**: low/medium/high
- **Evaluators added**: {list of new evaluators}
- **Recommendations**: {any manual actions needed}
```

- [ ] **Step 4: Update critic trigger in evolve skill**

In `skills/evolve/SKILL.md`, update the critic section (lines 325-347) to include the tools path:

```markdown
### 6.5. Auto-trigger Active Critic

If score jumped >0.3 from previous iteration OR reached target in <3 iterations:

\`\`\`
Agent(
  subagent_type: "evolver-critic",
  description: "Active Critic: detect and fix evaluator gaming",
  prompt: |
    <objective>
    EVAL GAMING CHECK: Score jumped from {prev_score} to {score}.
    Check if the LangSmith evaluators are being gamed.
    If gaming detected, add stricter evaluators using $TOOLS/add_evaluator.py.
    </objective>

    <tools_path>
    TOOLS={tools_path}
    EVOLVER_PY={evolver_py_path}
    </tools_path>

    <files_to_read>
    - .evolver.json
    - comparison.json
    - trace_insights.json
    - evolution_memory.md (if exists)
    </files_to_read>
)
\`\`\`

If the critic added new evaluators, log it:
\`\`\`
Critic added evaluators: {new_evaluators}. Next iteration will use stricter evaluation.
\`\`\`
```

- [ ] **Step 5: Commit**

```bash
git add tools/add_evaluator.py agents/evolver-critic.md skills/evolve/SKILL.md
git commit -m "feat: upgrade critic to active agent that implements evaluator fixes"
```

---

## Phase 5: Autonomous Differentiators

### Task 10: ULTRAPLAN for Architect (Feature 9)

When stagnation is detected, delegate architecture analysis to a more powerful session with extended thinking time.

**Files:**
- Modify: `agents/evolver-architect.md` (add deep analysis mode)
- Modify: `skills/evolve/SKILL.md:349-369` (upgrade architect trigger)

- [ ] **Step 1: Upgrade architect agent for deep analysis**

Replace `agents/evolver-architect.md` with:

```markdown
---
name: evolver-architect
description: |
  Use this agent when the evolution loop stagnates or regresses. Analyzes the agent architecture
  and recommends topology changes (single-call → RAG, chain → ReAct, etc.).
tools: Read, Write, Bash, Grep, Glob
color: blue
model: opus
---

# Evolver — Architect Agent (v3.1 — ULTRAPLAN Mode)

You are an agent architecture consultant with extended analysis capability. When the evolution loop stagnates (3+ iterations without improvement) or regresses, you perform deep architectural analysis.

## Bootstrap

Read files listed in `<files_to_read>` before doing anything else.

## Deep Analysis Mode

You are running with the Opus model and should take your time for thorough analysis. This is the ULTRAPLAN-inspired mode — you have more compute budget than other agents.

### Step 1: Full Codebase Scan

Read ALL source files related to the agent, not just the entry point:
- Entry point and all imports
- Configuration files
- Tool definitions
- Prompt templates
- Any routing or orchestration logic

### Step 2: Topology Classification

Classify the current architecture:
- **Single-call**: one LLM invocation, no tools
- **Chain**: sequential LLM calls (A → B → C)
- **RAG**: retrieval + generation pipeline
- **ReAct loop**: tool use in a loop (observe → think → act)
- **Hierarchical**: router → specialized agents
- **Parallel**: concurrent agent execution

Use `$TOOLS/analyze_architecture.py` for AST-based classification:

\`\`\`bash
$EVOLVER_PY $TOOLS/analyze_architecture.py --harness {entry_point_file} -o architecture_analysis.json
\`\`\`

### Step 3: Performance Pattern Analysis

Read trace_insights.json and evolution_memory.json to identify:
- Where is latency concentrated?
- Which components fail most?
- Is the bottleneck in routing, retrieval, or generation?
- What has been tried and failed (from evolution memory)?
- Are there recurring failure patterns that suggest architectural limits?

### Step 4: Recommend Migration

Based on the topology + performance analysis:
- Single-call failing → suggest adding tools or RAG
- Chain slow → suggest parallelization
- ReAct looping excessively → suggest better stopping conditions or hierarchical routing
- Hierarchical misrouting → suggest router improvements
- Any topology hitting accuracy ceiling → suggest ensemble or verification layer

Each migration step must be implementable in ONE proposer iteration.

## Output

Write two files:
- `architecture.json` — structured recommendation with topology, confidence, migration steps
- `architecture.md` — detailed human-readable analysis with:
  - Current architecture diagram (ASCII)
  - Identified bottlenecks
  - Proposed architecture diagram
  - Step-by-step migration plan
  - Expected score impact per step

## Return Protocol

## ARCHITECTURE ANALYSIS COMPLETE
- **Current topology**: {type}
- **Recommended**: {type}
- **Confidence**: {low/medium/high}
- **Migration steps**: {count}
- **Analysis depth**: ULTRAPLAN (extended thinking)
```

- [ ] **Step 2: Update architect trigger in evolve skill**

In `skills/evolve/SKILL.md`, replace the architect trigger (lines 349-369) with:

```markdown
### 7. Auto-trigger Architect (ULTRAPLAN Mode)

If 3 consecutive iterations within 1% OR score dropped:

\`\`\`
Agent(
  subagent_type: "evolver-architect",
  model: "opus",
  description: "Architect ULTRAPLAN: deep topology analysis",
  prompt: |
    <objective>
    The evolution loop has stagnated after {iterations} iterations.
    Scores: {last_3_scores}.
    Perform deep architectural analysis and recommend structural changes.
    Use extended thinking — you have more compute budget than normal agents.
    </objective>

    <tools_path>
    TOOLS={tools_path}
    EVOLVER_PY={evolver_py_path}
    </tools_path>

    <files_to_read>
    - .evolver.json
    - trace_insights.json
    - evolution_memory.md (if exists)
    - evolution_memory.json (if exists)
    - strategy.md (if exists)
    - {entry point and all related source files}
    </files_to_read>
)
\`\`\`

After architect completes, include `architecture.md` in proposer `<files_to_read>` for next iteration.
```

- [ ] **Step 3: Commit**

```bash
git add agents/evolver-architect.md skills/evolve/SKILL.md
git commit -m "feat: upgrade architect to ULTRAPLAN mode with opus model and deep analysis"
```

---

### Task 11: Self-Scheduling Evolution (Feature 11)

Allow the evolution loop to schedule itself for unattended operation.

**Files:**
- Modify: `skills/evolve/SKILL.md` (add scheduling option to pre-loop config)

- [ ] **Step 1: Add scheduling option to interactive config**

In `skills/evolve/SKILL.md`, after the existing AskUserQuestion block (lines 31-60), add a third question:

```markdown
If iterations > 3, offer scheduling:

\`\`\`json
{
  "questions": [
    {
      "question": "Run mode?",
      "header": "Execution",
      "multiSelect": false,
      "options": [
        {"label": "Interactive", "description": "I'll watch. Show results after each iteration."},
        {"label": "Background", "description": "Run all iterations in background. Notify on completion or significant improvement."},
        {"label": "Scheduled", "description": "Schedule iterations to run on a cron (e.g., nightly optimization)."}
      ]
    }
  ]
}
\`\`\`

**If "Background" selected:**
Run the evolution loop as a background task. Use the `run_in_background` parameter on the main loop execution.

**If "Scheduled" selected:**
Ask for schedule via AskUserQuestion:
\`\`\`json
{
  "questions": [
    {
      "question": "Schedule?",
      "header": "Cron Schedule",
      "multiSelect": false,
      "options": [
        {"label": "Every 6 hours", "description": "Run 1 iteration every 6 hours"},
        {"label": "Nightly (2 AM)", "description": "Run iterations overnight"},
        {"label": "Custom", "description": "Enter a cron expression"}
      ]
    }
  ]
}
\`\`\`

Then create a cron trigger:
\`\`\`
Use CronCreate tool to schedule:
  - command: "/evolver:evolve --iterations 1"
  - schedule: {selected_cron}
  - description: "Harness Evolver: scheduled optimization iteration"
\`\`\`

Report: "Scheduled evolution iterations. Use `/evolver:status` to check progress. Cancel with CronDelete."
```

- [ ] **Step 2: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: add self-scheduling evolution mode (background + cron)"
```

---

### Task 12: Anti-Distillation for Evaluators (Feature 12)

Detect if the agent is memorizing expected outputs and inject adversarial examples.

**Files:**
- Create: `tools/adversarial_inject.py`
- Modify: `agents/evolver-testgen.md` (add adversarial mode)

- [ ] **Step 1: Create `tools/adversarial_inject.py`**

```python
#!/usr/bin/env python3
"""Inject adversarial examples into LangSmith dataset.

Detects potential memorization by checking if agent outputs are suspiciously
similar to reference outputs, then generates adversarial variations to test
generalization.

Usage:
    python3 adversarial_inject.py \
        --config .evolver.json \
        --experiment v003a \
        --output adversarial_report.json
"""

import argparse
import json
import os
import platform
import sys
import random


def ensure_langsmith_api_key():
    """Load LANGSMITH_API_KEY from credentials file or .env if not in env."""
    if os.environ.get("LANGSMITH_API_KEY"):
        return True
    if platform.system() == "Darwin":
        creds_path = os.path.expanduser("~/Library/Application Support/langsmith-cli/credentials")
    else:
        creds_path = os.path.expanduser("~/.config/langsmith-cli/credentials")
    if os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    if os.path.exists(".env"):
        try:
            with open(".env") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY=") and not line.startswith("#"):
                        key = line.split("=", 1)[1].strip().strip("'\"")
                        if key:
                            os.environ["LANGSMITH_API_KEY"] = key
                            return True
        except OSError:
            pass
    return False


def detect_memorization(client, experiment_name, dataset_name):
    """Check if agent outputs are suspiciously similar to reference outputs."""
    suspicious = []
    try:
        runs = list(client.list_runs(project_name=experiment_name, is_root=True, limit=200))
        examples = {str(e.id): e for e in client.list_examples(dataset_name=dataset_name, limit=500)}

        for run in runs:
            if not run.reference_example_id:
                continue
            example = examples.get(str(run.reference_example_id))
            if not example or not example.outputs:
                continue

            run_output = str(run.outputs or "").lower().strip()
            ref_output = str(example.outputs).lower().strip()

            if not run_output or not ref_output:
                continue

            # Check for exact or near-exact match (potential memorization)
            if run_output == ref_output:
                suspicious.append({
                    "example_id": str(run.reference_example_id),
                    "match_type": "exact",
                    "input": str(run.inputs)[:200],
                })
            elif len(run_output) > 50 and ref_output in run_output:
                suspicious.append({
                    "example_id": str(run.reference_example_id),
                    "match_type": "contains_reference",
                    "input": str(run.inputs)[:200],
                })

    except Exception as e:
        print(f"Error checking memorization: {e}", file=sys.stderr)

    return suspicious


def generate_adversarial_inputs(client, dataset_name, num_inputs=5):
    """Generate adversarial variations of existing examples."""
    examples = list(client.list_examples(dataset_name=dataset_name, limit=100))
    if not examples:
        return []

    adversarial = []
    sampled = random.sample(examples, min(num_inputs, len(examples)))

    for example in sampled:
        input_data = example.inputs or {}
        input_text = str(input_data.get("input", input_data))

        # Generate variations that test generalization
        adversarial.append({
            "inputs": {"input": f"[REPHRASE] {input_text}"},
            "metadata": {
                "source": "adversarial",
                "original_example_id": str(example.id),
                "variation_type": "rephrase",
            },
        })

    return adversarial


def inject_adversarial(client, dataset_id, adversarial_inputs):
    """Add adversarial examples to dataset."""
    added = 0
    for adv in adversarial_inputs:
        try:
            client.create_example(
                inputs=adv["inputs"],
                dataset_id=dataset_id,
                metadata=adv["metadata"],
            )
            added += 1
        except Exception as e:
            print(f"Failed to inject: {e}", file=sys.stderr)
    return added


def main():
    parser = argparse.ArgumentParser(description="Adversarial injection for evaluators")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--experiment", required=True, help="Experiment to check for memorization")
    parser.add_argument("--output", default=None, help="Output report path")
    parser.add_argument("--inject", action="store_true", help="Actually inject adversarial examples")
    parser.add_argument("--num-adversarial", type=int, default=5, help="Number of adversarial examples")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    ensure_langsmith_api_key()
    from langsmith import Client
    client = Client()

    # Detect memorization
    suspicious = detect_memorization(client, args.experiment, config["dataset"])

    # Generate adversarial inputs
    adversarial = generate_adversarial_inputs(client, config["dataset"], args.num_adversarial)

    injected = 0
    if args.inject and adversarial:
        injected = inject_adversarial(client, config["dataset_id"], adversarial)

    result = {
        "memorization_suspects": len(suspicious),
        "suspicious_examples": suspicious,
        "adversarial_generated": len(adversarial),
        "adversarial_injected": injected,
    }

    output = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    print(output)

    if suspicious:
        print(f"\nWARNING: {len(suspicious)} examples show potential memorization!", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test adversarial_inject.py runs**

Run:
```bash
$EVOLVER_PY tools/adversarial_inject.py --help
```
Expected: help output with all flags.

- [ ] **Step 3: Add adversarial mode to testgen agent**

In `agents/evolver-testgen.md`, add after Phase 3 (line 55):

```markdown
### Phase 3.5: Adversarial Injection (if requested)

If your prompt includes `<mode>adversarial</mode>`:

1. Read existing dataset examples
2. For each example, generate variations that test generalization:
   - Rephrase the question using different words
   - Add misleading context that shouldn't change the answer
   - Combine elements from different examples
   - Ask the same question in a roundabout way
3. Tag these as `source: adversarial` in metadata

Use the adversarial injection tool:

\`\`\`bash
$EVOLVER_PY $TOOLS/adversarial_inject.py \
    --config .evolver.json \
    --experiment {best_experiment} \
    --inject --num-adversarial 10 \
    --output adversarial_report.json
\`\`\`
```

- [ ] **Step 4: Commit**

```bash
git add tools/adversarial_inject.py agents/evolver-testgen.md
git commit -m "feat: add anti-distillation adversarial injection for evaluators"
```

---

## Version Bump

### Task 13: Update version and validate

- [ ] **Step 1: Bump version in package.json and plugin.json**

Update version from `3.3.1` to `4.0.0` in both files (major version bump due to significant new features).

In `package.json`, change `"version": "3.3.1"` to `"version": "4.0.0"`.
In `.claude-plugin/plugin.json`, change `"version": "3.3.1"` to `"version": "4.0.0"`.

- [ ] **Step 2: Update CLAUDE.md with new tools**

Add the new tools to the "Running tools locally" section:

```bash
# Validate state before evolution
python tools/validate_state.py --config .evolver.json --output validation.json

# Check iteration gates
python tools/iteration_gate.py --config .evolver.json --output gate_result.json

# Track regressions between iterations
python tools/regression_tracker.py --config .evolver.json --previous-experiment v001a --current-experiment v002c --output regression_report.json

# Consolidate cross-iteration memory
python tools/consolidate.py --config .evolver.json --output evolution_memory.md

# Synthesize evolution strategy document
python tools/synthesize_strategy.py --config .evolver.json --output strategy.md

# Add evaluator to config
python tools/add_evaluator.py --config .evolver.json --evaluator factual_accuracy --type llm

# Inject adversarial examples
python tools/adversarial_inject.py --config .evolver.json --experiment v003a --inject
```

- [ ] **Step 3: Run `/dev:validate` to check plugin integrity**

Run the dev validate skill to ensure all cross-references, frontmatter, and tool syntax are correct.

- [ ] **Step 4: Commit**

```bash
git add package.json .claude-plugin/plugin.json CLAUDE.md
git commit -m "chore: bump version to 4.0.0, update docs with new tools"
```

---

## Verification Criteria

### Phase 1 Complete When:
- [ ] `validate_state.py` runs against a real .evolver.json and reports valid/issues
- [ ] `iteration_gate.py` correctly identifies plateau from history with 3+ stagnant scores
- [ ] Evolve skill includes validation and gate checks

### Phase 2 Complete When:
- [ ] `regression_tracker.py` detects transitions between two experiments
- [ ] `consolidate.py` produces evolution_memory.md with promoted/pending insights
- [ ] Proposer prompts include evolution_memory.md in files_to_read

### Phase 3 Complete When:
- [ ] Proposer prompts share identical prefix with strategy-only suffix
- [ ] Exploit/crossover/failure-targeted proposers lack Write tool
- [ ] Proposer agent has turn budget documented (16 turns)

### Phase 4 Complete When:
- [ ] `synthesize_strategy.py` produces strategy.md from available analysis files
- [ ] Proposers receive strategy.md instead of raw trace/results files
- [ ] Critic adds evaluators to .evolver.json when gaming detected
- [ ] `add_evaluator.py` correctly modifies config

### Phase 5 Complete When:
- [ ] Architect uses `model: "opus"` in Agent() call
- [ ] Scheduling option appears in interactive config
- [ ] `adversarial_inject.py` detects memorization and injects variations
