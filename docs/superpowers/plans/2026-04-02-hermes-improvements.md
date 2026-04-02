# Hermes-Inspired Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port 9 high-value techniques from the Hermes Agent Self-Evolution project to harden the harness-evolver's evaluation rigor, data safety, and decision quality.

**Architecture:** Each improvement is independent and ships as its own commit. Priority order: P0 (rubrics, constraints) → P1 (weights, feedback, secrets, holdout) → P2 (growth tracking, pareto) → P3 (session mining). All new tools are stdlib-only where possible, following the existing `tools/*.py` pattern.

**Tech Stack:** Python 3 stdlib, LangSmith SDK (where needed), existing `tools/` conventions (argparse, `ensure_langsmith_api_key()`, `--config`, `--output`).

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `tools/read_results.py` | Weighted scoring, feedback extraction, Pareto front |
| Modify | `agents/evolver-evaluator.md` | Rubric-aware judging |
| Modify | `agents/evolver-testgen.md` | Generate rubrics with test data |
| Modify | `skills/evolve/SKILL.md` | Constraint gates, holdout enforcement, feedback in prompts, growth tracking |
| Modify | `skills/setup/SKILL.md` | Weights config, rubric support in dataset |
| Modify | `tools/setup.py` | Support `expected_behavior` and `evaluator_weights` |
| Modify | `tools/dataset_health.py` | Secret detection check |
| Modify | `tools/seed_from_traces.py` | Secret filtering |
| Modify | `tools/evolution_chart.py` | LOC column |
| Create | `tools/constraint_check.py` | Hard constraint validation for proposals |
| Create | `tools/secret_filter.py` | Regex-based secret detection (stdlib-only) |
| Create | `tools/mine_sessions.py` | Claude Code session history mining |
| Modify | `CLAUDE.md` | Document new tools |

---

### Task 1: Evaluator Weights — weighted scoring instead of flat average (P1)

**Files:**
- Modify: `tools/read_results.py:110-122` (score calculation)
- Modify: `tools/setup.py:244-254` (write weights to config)
- Modify: `skills/setup/SKILL.md` (ask about weights)

Currently `read_results.py:111` does a flat average:
```python
"score": sum(scores.values()) / len(scores) if scores else 0.0
```

- [ ] **Step 1: Add weighted score calculation to `read_results.py`**

In `read_results.py`, add a helper function after `ensure_langsmith_api_key()` and modify `read_experiment()` to accept and use weights:

```python
def weighted_score(scores, weights=None):
    """Calculate weighted average of evaluator scores.
    
    If weights provided, use them. Otherwise flat average.
    Weights are normalized (don't need to sum to 1).
    """
    if not scores:
        return 0.0
    if not weights:
        return sum(scores.values()) / len(scores)
    
    total_weight = 0
    weighted_sum = 0
    for key, val in scores.items():
        w = weights.get(key, 1.0)
        weighted_sum += val * w
        total_weight += w
    
    return weighted_sum / total_weight if total_weight > 0 else 0.0
```

Then modify `read_experiment()` to accept `weights=None` parameter and use it at line 111:

```python
# Old:
"score": sum(scores.values()) / len(scores) if scores else 0.0,
# New:
"score": weighted_score(scores, weights),
```

And modify `main()` to load weights from config:

```python
# After loading config (around line 234):
weights = None
if os.path.exists(args.config):
    with open(args.config) as f:
        cfg = json.load(f)
    weights = cfg.get("evaluator_weights")
```

Pass `weights` to `read_experiment()` calls.

Also change `combined_score` calculation at line 122:

```python
# Old:
combined_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
# New:  
combined_score = sum(all_scores) / len(all_scores) if all_scores else 0.0  # already weighted per-example
```

- [ ] **Step 2: Add `evaluator_weights` to setup.py config output**

In `setup.py`, wherever `.evolver.json` is written (around line 350+), add:

```python
"evaluator_weights": None,  # Set via setup to weight evaluators (e.g., {"correctness": 0.5, "latency": 0.3})
```

- [ ] **Step 3: Test with mock weights**

```bash
# Create a test config with weights
python3 -c "
import json
c = json.load(open('playground/react-agent/.evolver.json'))
c['evaluator_weights'] = {'correctness': 0.5, 'latency': 0.3, 'token_efficiency': 0.2}
json.dump(c, open('/tmp/weighted.json', 'w'), indent=2)
"
# Run read_results with weighted config (will need langsmith)
python3 tools/read_results.py --experiment baseline-35ed1eb2 --config /tmp/weighted.json --format markdown 2>&1 | head -10
```

- [ ] **Step 4: Commit**

```bash
git add tools/read_results.py tools/setup.py
git commit -m "feat: evaluator weights — weighted scoring instead of flat average"
```

---

### Task 2: Rubric-Based Evaluation — `expected_behavior` field in dataset (P0)

**Files:**
- Modify: `tools/setup.py:149-199` (support `expected_behavior` in dataset examples)
- Modify: `agents/evolver-evaluator.md:85-98` (use rubrics when available)
- Modify: `agents/evolver-testgen.md` (generate rubrics alongside inputs)
- Modify: `skills/evolve/SKILL.md:370-377` (pass rubric data to evaluator)

This is the highest-impact improvement. Hermes evaluates against rubrics ("should explain null safety and Android use cases"), not exact text. Our LLM judge currently scores with no criteria.

- [ ] **Step 1: Update `setup.py` to support `expected_behavior` in dataset creation**

In `create_dataset_from_file()` (line 149), add support for the `expected_behavior` field. Modify the metadata handling block (lines 177-192):

```python
            # Include expected outputs if present
            if "outputs" in item:
                ex["outputs"] = item["outputs"]
            elif "expected" in item:
                ex["outputs"] = {"expected": item["expected"]}

            # Include rubric/expected behavior in metadata
            if "expected_behavior" in item:
                if "metadata" not in ex:
                    ex["metadata"] = {}
                ex["metadata"]["expected_behavior"] = item["expected_behavior"]

            if "metadata" not in ex:
                ex["metadata"] = {}
            ex["metadata"].setdefault("source", "file")
            ex["metadata"].setdefault("added_at_iteration", 0)
```

- [ ] **Step 2: Update `evolver-evaluator.md` to use rubrics**

In `agents/evolver-evaluator.md`, add a new section after the "Reading experiment outputs" section (after line 49), before "Phase 2":

```markdown
### Rubric-Aware Scoring

When evaluating a run, check if the dataset example has an `expected_behavior` rubric in its metadata. You can retrieve example metadata via:

```bash
langsmith-cli --json examples list \
    --dataset "{dataset_name}" \
    --fields id,metadata \
    --limit 200 \
    --output example_metadata.jsonl
```

Parse `example_metadata.jsonl` to build a map of `example_id → expected_behavior`.

When scoring a run with `reference_example_id`, look up the rubric. If a rubric exists, use it as the primary evaluation criteria:

**With rubric:**
- `1.0` — Response satisfies all criteria in the rubric
- `0.5` — Response partially satisfies the rubric (some criteria met, others missing)
- `0.0` — Response fails to meet the rubric criteria

**Without rubric:** Fall back to the existing correctness criteria (Phase 2 below).

Rubrics describe WHAT a good response covers, not the exact text. A response can use different wording and still score 1.0 if it covers all rubric points.
```

Also update the correctness section (lines 85-97) to note:

```markdown
#### correctness
Judge: **Is the output a correct, accurate, and complete response to the input?**

**If a rubric exists for this example** (from `expected_behavior` metadata), evaluate against the rubric criteria specifically. The rubric takes precedence over generic correctness judgment.

**If no rubric exists**, use generic scoring:
```

- [ ] **Step 3: Update `evolver-testgen.md` to generate rubrics**

In `agents/evolver-testgen.md`, add to the output format section:

```markdown
## Output Format

Each test example must include:
- `input` — the user query/request
- `expected_behavior` — a rubric describing what a good response should cover (NOT exact expected text). Write 1-3 specific, verifiable criteria. Example: "Should explain that Kotlin is a JVM language, mention null safety as a key feature, and reference Android development"
- `difficulty` — easy, medium, or hard
- `category` — which aspect of the agent this tests (e.g., "knowledge", "tool_use", "error_handling")

Example:
```json
{
  "input": "What is Kotlin?",
  "expected_behavior": "Should explain Kotlin is a JVM language by JetBrains, mention null safety, and reference Android development as primary use case",
  "difficulty": "easy",
  "category": "knowledge"
}
```
```

- [ ] **Step 4: Update evolve skill to pass rubrics to evaluator agent**

In `skills/evolve/SKILL.md`, modify step 3.5 (line ~370-377) to include rubric data in the evaluator prompt:

```
Agent(
  subagent_type: "evolver-evaluator",
  description: "Evaluate all candidates for iteration v{NNN}",
  prompt: "Experiments to evaluate: {experiment_names}. Evaluators: {llm_evaluator_list}. Framework: {framework}. Entry point: {entry_point}. Dataset: {dataset_name}. NOTE: Some examples have expected_behavior rubrics in their metadata — fetch example metadata and use rubrics for scoring when available."
)
```

- [ ] **Step 5: Commit**

```bash
git add tools/setup.py agents/evolver-evaluator.md agents/evolver-testgen.md skills/evolve/SKILL.md
git commit -m "feat: rubric-based evaluation — expected_behavior field for targeted LLM judging"
```

---

### Task 3: Constraint Gates — reject invalid proposals before merge (P0)

**Files:**
- Create: `tools/constraint_check.py`
- Modify: `skills/evolve/SKILL.md` (add constraint gate between Step 4 and Step 5)

Hermes rejects any candidate that violates hard constraints (size growth, structural integrity, test pass). Currently the evolver accepts anything that scores higher.

- [ ] **Step 1: Create `tools/constraint_check.py`**

```python
#!/usr/bin/env python3
"""Constraint checker for evolution proposals.

Validates that a candidate proposal doesn't violate hard constraints
before it's merged. Inspired by Hermes Agent Self-Evolution.

Usage:
    python3 constraint_check.py \
        --config .evolver.json \
        --worktree-path /tmp/worktree \
        --baseline-path /path/to/main \
        --output constraint_result.json

Stdlib-only — no langsmith dependency.
"""

import argparse
import json
import os
import subprocess
import sys


def count_loc(directory, extensions=(".py", ".js", ".ts", ".jsx", ".tsx")):
    """Count lines of code in a directory, excluding venvs and node_modules."""
    total = 0
    skip_dirs = {".venv", "venv", "node_modules", "__pycache__", ".git"}
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if any(f.endswith(ext) for ext in extensions):
                try:
                    with open(os.path.join(root, f)) as fh:
                        total += sum(1 for _ in fh)
                except (OSError, UnicodeDecodeError):
                    pass
    return total


def check_growth(baseline_loc, candidate_loc, max_growth_pct=30):
    """Check code didn't grow beyond threshold."""
    if baseline_loc == 0:
        return {"pass": True, "reason": "no baseline LOC"}
    growth = ((candidate_loc - baseline_loc) / baseline_loc) * 100
    passed = growth <= max_growth_pct
    return {
        "pass": passed,
        "baseline_loc": baseline_loc,
        "candidate_loc": candidate_loc,
        "growth_pct": round(growth, 1),
        "max_growth_pct": max_growth_pct,
        "reason": f"Code growth {growth:.1f}% {'<=' if passed else '>'} {max_growth_pct}% limit",
    }


def check_entry_point(worktree_path, entry_point):
    """Check that the entry point is still runnable (syntax check)."""
    # Extract the Python/script file from the entry_point command
    parts = entry_point.split()
    script_file = None
    for part in parts:
        if part.endswith((".py", ".js", ".ts", ".sh")):
            script_file = part
            break

    if not script_file:
        return {"pass": True, "reason": "no script file detected in entry_point"}

    full_path = os.path.join(worktree_path, script_file)
    if not os.path.exists(full_path):
        return {"pass": False, "reason": f"entry point file missing: {script_file}"}

    # Python syntax check
    if script_file.endswith(".py"):
        result = subprocess.run(
            ["python3", "-m", "py_compile", full_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return {"pass": False, "reason": f"syntax error: {result.stderr[:200]}"}

    return {"pass": True, "reason": "entry point exists and has valid syntax"}


def check_tests(worktree_path):
    """Run test suite if it exists. Returns pass if no tests found."""
    test_dirs = ["tests", "test"]
    has_tests = False
    for td in test_dirs:
        test_path = os.path.join(worktree_path, td)
        if os.path.isdir(test_path):
            # Check if there are actual test files (not just __pycache__)
            for f in os.listdir(test_path):
                if f.startswith("test_") and f.endswith(".py"):
                    has_tests = True
                    break

    if not has_tests:
        return {"pass": True, "reason": "no test suite found (skipped)", "skipped": True}

    result = subprocess.run(
        ["python3", "-m", "pytest", "-q", "--tb=no"],
        capture_output=True, text=True,
        cwd=worktree_path, timeout=120,
    )
    passed = result.returncode == 0
    return {
        "pass": passed,
        "reason": result.stdout.strip()[:200] if passed else result.stderr.strip()[:200],
        "skipped": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Check constraints on a proposal")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--worktree-path", required=True, help="Candidate worktree path")
    parser.add_argument("--baseline-path", default=".", help="Baseline (main) path")
    parser.add_argument("--max-growth", type=int, default=30, help="Max code growth %% (default 30)")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    entry_point = config.get("entry_point", "")
    # Strip python path prefix for file detection
    ep_for_check = entry_point.split("python ")[-1].split("python3 ")[-1]

    results = {
        "growth": check_growth(
            count_loc(args.baseline_path),
            count_loc(args.worktree_path),
            args.max_growth,
        ),
        "entry_point": check_entry_point(args.worktree_path, ep_for_check),
        "tests": check_tests(args.worktree_path),
    }

    all_pass = all(r["pass"] for r in results.values())
    output = {"all_pass": all_pass, "constraints": results}

    out_str = json.dumps(output, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(out_str)
    print(out_str)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test the constraint checker**

```bash
# Test on playground/react-agent (should pass — no growth, entry point exists)
python3 tools/constraint_check.py \
    --config playground/react-agent/.evolver.json \
    --worktree-path playground/react-agent \
    --baseline-path playground/react-agent
```

Expected: `all_pass: true`

- [ ] **Step 3: Add constraint gate to evolve skill**

In `skills/evolve/SKILL.md`, add a new step 4.5 between "4. Compare All Candidates" and "5. Merge Winner":

```markdown
### 4.5. Constraint Gate

Before merging, validate the winner passes hard constraints:

```bash
$EVOLVER_PY $TOOLS/constraint_check.py \
    --config .evolver.json \
    --worktree-path "{winner_worktree_path}" \
    --baseline-path "." \
    --output constraint_result.json
```

If `all_pass` is false, skip this candidate and try the next-best from `comparison.all_candidates`. If NO candidates pass constraints, log a warning and proceed to next iteration without merging:

```
WARNING: No candidates passed constraint gates. Skipping merge.
  growth: {growth_pct}% (limit: 30%)
  entry_point: {pass/fail}
  tests: {pass/fail}
```
```

- [ ] **Step 4: Commit**

```bash
git add tools/constraint_check.py skills/evolve/SKILL.md
git commit -m "feat: constraint gates — reject proposals that break size/tests/entry-point"
```

---

### Task 4: Secret Detection — filter sensitive data from datasets (P1)

**Files:**
- Create: `tools/secret_filter.py`
- Modify: `tools/seed_from_traces.py` (filter secrets from production data)
- Modify: `tools/dataset_health.py` (check for secrets in existing datasets)

- [ ] **Step 1: Create `tools/secret_filter.py`**

```python
#!/usr/bin/env python3
"""Secret detection and filtering for eval datasets.

Detects API keys, tokens, passwords, and other sensitive data in text.
Used by seed_from_traces.py and dataset_health.py.

Stdlib-only — no external dependencies.
"""

import re
import sys


# Patterns from Hermes Agent Self-Evolution + additions
SECRET_PATTERNS = re.compile(
    r'('
    r'sk-ant-api\S{20,}'         # Anthropic API keys
    r'|sk-or-v1-\S{20,}'         # OpenRouter keys
    r'|sk-\S{20,}'               # OpenAI keys
    r'|ghp_\S{20,}'              # GitHub personal access tokens
    r'|gho_\S{20,}'              # GitHub OAuth tokens
    r'|github_pat_\S{20,}'       # GitHub fine-grained PATs
    r'|xoxb-\S{20,}'             # Slack bot tokens
    r'|xapp-\S{20,}'             # Slack app tokens
    r'|ntn_\S{20,}'              # Notion tokens
    r'|AKIA[A-Z0-9]{16}'         # AWS access keys
    r'|Bearer\s+[A-Za-z0-9\-._~+/]{20,}'  # Bearer tokens
    r'|-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----'  # PEM keys
    r')',
    re.IGNORECASE,
)

# Environment variable assignment patterns
ENV_PATTERNS = re.compile(
    r'(?:ANTHROPIC_API_KEY|OPENAI_API_KEY|LANGSMITH_API_KEY|LANGCHAIN_API_KEY'
    r'|AWS_SECRET_ACCESS_KEY|DATABASE_URL|POSTGRES_PASSWORD'
    r'|SLACK_TOKEN|GITHUB_TOKEN|API_KEY|SECRET_KEY'
    r')\s*[=:]\s*["\']?\S{10,}',
    re.IGNORECASE,
)

# Password/secret assignment patterns
ASSIGN_PATTERNS = re.compile(
    r'(?:password|secret|token|api_key|apikey)\s*[=:]\s*["\']?\S{10,}',
    re.IGNORECASE,
)


def detect_secrets(text):
    """Return list of secret matches found in text.
    
    Returns list of dicts: [{"pattern": "type", "match": "redacted", "position": N}]
    """
    if not text:
        return []
    
    findings = []
    for pattern, name in [
        (SECRET_PATTERNS, "secret_key"),
        (ENV_PATTERNS, "env_variable"),
        (ASSIGN_PATTERNS, "assignment"),
    ]:
        for m in pattern.finditer(text):
            findings.append({
                "pattern": name,
                "match": m.group()[:10] + "..." + m.group()[-4:] if len(m.group()) > 20 else m.group(),
                "position": m.start(),
            })
    
    return findings


def has_secrets(text):
    """Quick boolean check — does text contain any secrets?"""
    if not text:
        return False
    return bool(SECRET_PATTERNS.search(text) or ENV_PATTERNS.search(text) or ASSIGN_PATTERNS.search(text))


def redact_secrets(text):
    """Replace detected secrets with [REDACTED]."""
    if not text:
        return text
    text = SECRET_PATTERNS.sub("[REDACTED]", text)
    text = ENV_PATTERNS.sub("[REDACTED]", text)
    text = ASSIGN_PATTERNS.sub("[REDACTED]", text)
    return text


if __name__ == "__main__":
    # CLI: pipe text in, get findings out
    import json
    text = sys.stdin.read()
    findings = detect_secrets(text)
    if findings:
        print(json.dumps({"has_secrets": True, "count": len(findings), "findings": findings}, indent=2))
        sys.exit(1)
    else:
        print(json.dumps({"has_secrets": False, "count": 0}))
        sys.exit(0)
```

- [ ] **Step 2: Test secret detection**

```bash
echo 'My key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz and password=mysecretpass123' | python3 tools/secret_filter.py
```

Expected: `has_secrets: true`, 2 findings.

```bash
echo 'This is normal text about APIs and authentication' | python3 tools/secret_filter.py
```

Expected: `has_secrets: false`.

- [ ] **Step 3: Integrate into `seed_from_traces.py`**

In `seed_from_traces.py`, after extracting input/output from a run, filter secrets. Add at the top:

```python
# Import secret filter (relative import from same directory)
sys.path.insert(0, os.path.dirname(__file__))
from secret_filter import has_secrets, redact_secrets
```

Then in the main loop where examples are built, add:

```python
# Filter secrets from production data
input_text = extract_input(run)
output_text = extract_output(run)

if has_secrets(str(input_text)) or has_secrets(str(output_text)):
    secrets_filtered += 1
    continue  # Skip this example entirely
```

- [ ] **Step 4: Add secret check to `dataset_health.py`**

In `dataset_health.py`, add a new check function:

```python
def check_secrets(examples):
    """Check for secrets in dataset examples."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from secret_filter import has_secrets
    except ImportError:
        return {"checked": False, "reason": "secret_filter.py not found"}
    
    flagged = []
    for ex in examples:
        text = str(ex.inputs) + str(getattr(ex, 'outputs', '') or '')
        if has_secrets(text):
            flagged.append(str(ex.id))
    
    return {
        "checked": True,
        "flagged_count": len(flagged),
        "flagged_ids": flagged[:10],  # First 10 only
        "clean": len(flagged) == 0,
    }
```

Call it in the main health check flow and include in the report.

- [ ] **Step 5: Commit**

```bash
git add tools/secret_filter.py tools/seed_from_traces.py tools/dataset_health.py
git commit -m "feat: secret detection — filter API keys/tokens from datasets"
```

---

### Task 5: Holdout Enforcement — score final winner on unseen data (P1)

**Files:**
- Modify: `skills/evolve/SKILL.md:382-388` (Step 4 — compare on holdout)

Currently Step 4 compares experiments using all data. The `--split` flag exists in `read_results.py` but isn't used for final comparison. The fix is minimal — change the comparison command to use `--split held_out`.

- [ ] **Step 1: Update Step 4 in evolve skill**

In `skills/evolve/SKILL.md`, replace Step 4 "Compare All Candidates" (lines ~382-388):

```markdown
### 4. Compare All Candidates

Compare on the **held_out** split — data never seen during optimization — for unbiased selection:

```bash
$EVOLVER_PY $TOOLS/read_results.py \
    --experiments "{comma-separated list of experiment names from non-abstained proposers}" \
    --config .evolver.json \
    --split held_out \
    --output comparison.json
```

Parse `comparison.json`:
- `comparison.winner` — highest combined score **on held-out data**
- `comparison.champion` — per-task champion (for next iteration's context)
- `comparison.all_candidates` — all scores for reporting

Note: Code-based evaluators (has_output, token_efficiency) scored on all data during Step 3. LLM-as-judge (correctness) scored on all data in Step 3.5. This step re-reads scores filtered to held_out split only for final comparison. The held_out split was assigned during setup and represents ~30% of the dataset.
```

- [ ] **Step 2: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: holdout enforcement — compare candidates on unseen data only"
```

---

### Task 6: Judge Feedback in Proposer Prompts — direct failure explanations (P1)

**Files:**
- Modify: `tools/read_results.py:103-118` (include feedback text in per_example)
- Modify: `skills/evolve/SKILL.md:229-258` (include feedback in proposer context)

Hermes feeds the judge's textual feedback directly to GEPA's mutation engine. Our evolver passes insights indirectly via strategy.md. The fix: include the actual judge comments in `best_results.json` and surface them in proposer prompts.

- [ ] **Step 1: Include feedback comment in `read_results.py` per_example**

In `read_results.py`, modify the feedback extraction loop (lines 103-118) to capture comments:

```python
            # Read feedback/scores from pre-fetched batch
            feedbacks = fb_map.get(str(run.id), [])
            scores = {}
            feedback_comments = {}
            for fb in feedbacks:
                if fb.score is not None:
                    scores[fb.key] = fb.score
                if fb.comment:
                    feedback_comments[fb.key] = fb.comment

            per_example[example_id] = {
                "score": weighted_score(scores, weights),
                "scores": scores,
                "feedback": feedback_comments,  # NEW: judge's textual feedback
                "tokens": tokens,
                "latency_ms": latency_ms,
                "error": run.error[:200] if run.error else None,
                "input_preview": str(run.inputs)[:200] if run.inputs else "",
                "output_preview": str(run.outputs)[:200] if run.outputs else "",
            }
```

- [ ] **Step 2: Surface feedback in proposer strategy context**

In `skills/evolve/SKILL.md`, after step 1.5 where `best_results.json` is parsed (around line 191), add guidance to include judge feedback in strategy generation:

```markdown
If `best_results.json` exists, parse it to find failing examples (score < 0.7). Group by metadata or error pattern.
**For each failing example, include the judge's feedback comment** (from the `feedback` field) in the strategy. This gives proposers specific, actionable information about WHY examples fail — not just that they fail.

Example for strategy.md:
```
## Failing Examples (with judge feedback)
- "What is Kotlin?" (score: 0.3) — Judge: "Response was factually correct but missed null safety and Android development use cases"
- "Calculate 2^32" (score: 0.0) — Judge: "Run failed with timeout error"
```
```

- [ ] **Step 3: Commit**

```bash
git add tools/read_results.py skills/evolve/SKILL.md
git commit -m "feat: surface judge feedback in proposer prompts for targeted mutations"
```

---

### Task 7: Code Growth Tracking — LOC column in evolution chart (P2)

**Files:**
- Modify: `skills/evolve/SKILL.md` (capture LOC in history entry)
- Modify: `tools/evolution_chart.py` (add LOC column + growth warning)

- [ ] **Step 1: Add LOC capture to evolve skill history entry**

In `skills/evolve/SKILL.md`, in the enriched history append (Step 5), add a `code_loc` field. Before the Python block that updates `.evolver.json`, capture LOC:

```bash
# Capture code size (lines of code) for growth tracking
CODE_LOC=$(find . -name "*.py" -not -path "./.venv/*" -not -path "./venv/*" -not -path "./__pycache__/*" | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}')
```

Then add to the history entry:

```python
    'code_loc': {CODE_LOC},
```

- [ ] **Step 2: Add LOC column to `evolution_chart.py` score table**

In `tools/evolution_chart.py`, modify `render_score_table()` to include LOC when available.

Add after the `latency` variable extraction (around line 114):

```python
        loc = h.get('code_loc')
```

Add to the header row:

```python
    # Only show LOC column if any entry has it
    has_loc = any(h.get('code_loc') for h in history)
    if has_loc:
        lines[2] = lines[2].rstrip() + f'{"LOC":>7}{c.RST}'  # extend header
```

Add to each row:

```python
        if has_loc:
            if loc:
                # Warn if growth > 30% vs baseline
                base_loc = history[0].get('code_loc', 0)
                if base_loc and loc > base_loc * 1.3:
                    loc_str = f'{c.R}{loc}{c.RST} ⚠'
                else:
                    loc_str = str(loc)
            else:
                loc_str = '—'
            # append to line
```

- [ ] **Step 3: Test with mock data**

```bash
python3 -c "
import json
c = {'project':'test','dataset':'test','evaluators':['correctness'],'history':[
    {'version':'baseline','score':0.5,'code_loc':120},
    {'version':'v001','score':0.7,'code_loc':135},
    {'version':'v002','score':0.8,'code_loc':180},
]}
json.dump(c,open('/tmp/loc_test.json','w'),indent=2)
"
python3 tools/evolution_chart.py --config /tmp/loc_test.json
```

Expected: LOC column visible, v002 shows warning if >30% growth.

- [ ] **Step 4: Commit**

```bash
git add tools/evolution_chart.py skills/evolve/SKILL.md
git commit -m "feat: code growth tracking — LOC column in evolution chart with growth warning"
```

---

### Task 8: Pareto Selection — multi-objective candidate ranking (P2)

**Files:**
- Modify: `tools/read_results.py:139-192` (add Pareto front calculation)
- Modify: `skills/evolve/SKILL.md` (report Pareto front)

Currently `compare_experiments()` picks the candidate with highest `combined_score`. When evaluators conflict (high correctness/low latency vs balanced), this loses information. Add Pareto-optimal detection.

- [ ] **Step 1: Add Pareto front calculation to `read_results.py`**

Add a new function after `compare_experiments()`:

```python
def pareto_front(candidates):
    """Find Pareto-optimal candidates (not dominated on any evaluator).
    
    A candidate is dominated if another candidate scores >= on ALL evaluators
    and strictly > on at least one.
    """
    if len(candidates) <= 1:
        return candidates
    
    front = []
    for i, ci in enumerate(candidates):
        dominated = False
        ci_scores = ci.get("evaluator_scores", {})
        if not ci_scores:
            continue
        
        for j, cj in enumerate(candidates):
            if i == j:
                continue
            cj_scores = cj.get("evaluator_scores", {})
            if not cj_scores:
                continue
            
            # Check if cj dominates ci
            all_geq = True
            any_gt = False
            for key in ci_scores:
                if key in cj_scores:
                    if cj_scores[key] < ci_scores[key]:
                        all_geq = False
                        break
                    if cj_scores[key] > ci_scores[key]:
                        any_gt = True
            
            if all_geq and any_gt:
                dominated = True
                break
        
        if not dominated:
            front.append(ci)
    
    return front if front else candidates[:1]
```

Then in `compare_experiments()`, after computing the winner, also compute per-evaluator averages and Pareto front:

```python
    # Compute per-evaluator averages for each candidate
    for result in valid:
        eval_avgs = {}
        for ex_data in result.get("per_example", {}).values():
            for ev_key, ev_score in ex_data.get("scores", {}).items():
                eval_avgs.setdefault(ev_key, []).append(ev_score)
        result["evaluator_scores"] = {k: sum(v)/len(v) for k, v in eval_avgs.items()}
    
    # Find Pareto front
    front = pareto_front(valid)
```

Add to the return dict:

```python
        "pareto_front": [
            {"experiment": r["experiment"], "score": r["combined_score"], "evaluator_scores": r.get("evaluator_scores", {})}
            for r in front
        ],
```

- [ ] **Step 2: Report Pareto front in evolve skill**

In `skills/evolve/SKILL.md`, after the winner report in Step 5, add:

```markdown
If `comparison.pareto_front` has more than 1 entry, report it:
```
Pareto front ({N} non-dominated candidates):
  v{NNN}-1: correctness=0.90, latency=0.50 (winner by combined score)
  v{NNN}-3: correctness=0.70, latency=0.85 (better latency tradeoff)
```
This informs the user when candidates offer genuinely different tradeoffs, not just different scores.
```

- [ ] **Step 3: Commit**

```bash
git add tools/read_results.py skills/evolve/SKILL.md
git commit -m "feat: Pareto front — surface multi-objective tradeoffs between candidates"
```

---

### Task 9: Session Mining — extract eval data from Claude Code history (P3)

**Files:**
- Create: `tools/mine_sessions.py`
- Modify: `skills/setup/SKILL.md` (offer session mining as data source option)

Hermes mines `~/.claude/history.jsonl` for real usage data. This tool extracts examples from Claude Code sessions where the user's agent was being used, creating high-quality eval data.

- [ ] **Step 1: Create `tools/mine_sessions.py`**

```python
#!/usr/bin/env python3
"""Mine Claude Code session history for eval dataset examples.

Reads ~/.claude/ session files to extract real user interactions
that can be used as evaluation data. Filters for relevance to the
agent being optimized, detects and skips secrets.

Usage:
    python3 mine_sessions.py \
        --agent-description "A ReAct agent that answers questions using tools" \
        --output session_examples.json \
        [--max-examples 50]

Stdlib-only except for secret_filter (local import).
"""

import argparse
import glob
import json
import os
import sys


def find_session_files():
    """Find Claude Code session history files."""
    candidates = [
        os.path.expanduser("~/.claude/history.jsonl"),
        os.path.expanduser("~/.claude/sessions/*/messages.jsonl"),
    ]
    
    found = []
    for pattern in candidates:
        found.extend(glob.glob(pattern))
    return found


def extract_messages(file_path):
    """Extract user→assistant message pairs from a session file."""
    pairs = []
    try:
        with open(file_path) as f:
            messages = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    messages.append(msg)
                except json.JSONDecodeError:
                    continue
            
            # Pair consecutive user/assistant messages
            for i in range(len(messages) - 1):
                if (messages[i].get("role") == "user" and 
                    messages[i + 1].get("role") == "assistant"):
                    user_text = messages[i].get("content", "")
                    if isinstance(user_text, list):
                        user_text = " ".join(
                            p.get("text", "") for p in user_text 
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    asst_text = messages[i + 1].get("content", "")
                    if isinstance(asst_text, list):
                        asst_text = " ".join(
                            p.get("text", "") for p in asst_text
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    
                    if user_text and len(user_text) > 10:
                        pairs.append({
                            "input": user_text[:500],
                            "output_preview": asst_text[:200] if asst_text else "",
                            "source_file": os.path.basename(file_path),
                        })
    except (OSError, UnicodeDecodeError):
        pass
    
    return pairs


def filter_relevant(pairs, agent_description, max_examples=50):
    """Simple keyword-based relevance filter.
    
    For a more sophisticated filter, the evolver-testgen agent
    can be used to score relevance via LLM.
    """
    # Extract keywords from agent description
    stop_words = {"a", "an", "the", "is", "are", "was", "were", "that", "this", "and", "or", "for", "to", "in", "on", "with", "using"}
    keywords = set(
        w.lower() for w in agent_description.split()
        if len(w) > 3 and w.lower() not in stop_words
    )
    
    scored = []
    for pair in pairs:
        input_words = set(pair["input"].lower().split())
        overlap = len(keywords & input_words)
        if overlap >= 1:
            scored.append((overlap, pair))
    
    scored.sort(key=lambda x: -x[0])
    return [pair for _, pair in scored[:max_examples]]


def main():
    parser = argparse.ArgumentParser(description="Mine Claude Code sessions for eval data")
    parser.add_argument("--agent-description", required=True, help="Description of the agent being optimized")
    parser.add_argument("--output", default="session_examples.json")
    parser.add_argument("--max-examples", type=int, default=50)
    args = parser.parse_args()
    
    # Import secret filter
    sys.path.insert(0, os.path.dirname(__file__))
    try:
        from secret_filter import has_secrets
    except ImportError:
        has_secrets = lambda text: False  # noqa: E731
    
    session_files = find_session_files()
    if not session_files:
        print("No Claude Code session files found.", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found {len(session_files)} session file(s)", file=sys.stderr)
    
    all_pairs = []
    secrets_skipped = 0
    for sf in session_files:
        pairs = extract_messages(sf)
        for p in pairs:
            if has_secrets(p["input"]) or has_secrets(p.get("output_preview", "")):
                secrets_skipped += 1
                continue
            all_pairs.append(p)
    
    print(f"Extracted {len(all_pairs)} message pairs ({secrets_skipped} skipped for secrets)", file=sys.stderr)
    
    relevant = filter_relevant(all_pairs, args.agent_description, args.max_examples)
    print(f"Filtered to {len(relevant)} relevant examples", file=sys.stderr)
    
    # Format for dataset consumption
    examples = []
    for p in relevant:
        examples.append({
            "input": p["input"],
            "metadata": {"source": "session_mining", "source_file": p["source_file"]},
        })
    
    output = {"examples": examples, "count": len(examples), "source": "claude_code_sessions"}
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    
    print(json.dumps({"mined": len(examples), "output": args.output}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test session mining**

```bash
# Test (will find 0 sessions if no Claude Code history exists — that's fine)
python3 tools/mine_sessions.py \
    --agent-description "A ReAct agent that answers questions using search and calculation tools" \
    --output /tmp/mined.json \
    --max-examples 10 2>&1
```

- [ ] **Step 3: Add session mining option to setup skill**

In `skills/setup/SKILL.md`, in the data source selection section, add an option:

```markdown
- **Session mining**: Extract examples from your Claude Code session history (`~/.claude/`). Run:
  ```bash
  $EVOLVER_PY $TOOLS/mine_sessions.py \
      --agent-description "{agent_description}" \
      --output session_examples.json \
      --max-examples 50
  ```
  Then use `session_examples.json` as `--dataset-from-file` in setup.
```

- [ ] **Step 4: Commit**

```bash
git add tools/mine_sessions.py skills/setup/SKILL.md
git commit -m "feat: session mining — extract eval data from Claude Code history"
```

---

### Task 10: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add new tools to "Running tools locally" section**

After the existing tool entries, add:

```bash
# Constraint validation for proposals (stdlib-only)
python tools/constraint_check.py --config .evolver.json --worktree-path /tmp/wt --baseline-path .

# Secret detection in text (stdlib-only, pipe text to stdin)
echo "my key is sk-ant-api..." | python tools/secret_filter.py

# Mine Claude Code sessions for eval data (stdlib-only)
python tools/mine_sessions.py --agent-description "my agent" --output mined.json
```

- [ ] **Step 2: Update Architecture section**

In the Tools description, add the new tools to the stdlib-only list:

```
`analyze_architecture.py`, `evolution_chart.py`, `constraint_check.py`, `secret_filter.py`, and `mine_sessions.py` are stdlib-only (no langsmith dependency).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add constraint_check, secret_filter, mine_sessions to CLAUDE.md"
```
