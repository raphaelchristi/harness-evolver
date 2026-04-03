# Verdict Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 5 operational issues the testing agent identified: automate config updates, clean up worktrees, simplify the skill, add rate-limit retry, and pin rubric outputs to scores.

**Architecture:** Two new tools (`update_config.py`, `cleanup_worktrees.py`) replace manual inline Python and worktree accumulation. The evolve skill is simplified by delegating to these tools. Rate-limit retry is added to `run_eval.py`. Rubric pinning goes in the evaluator agent instructions.

**Tech Stack:** Python 3 stdlib, LangSmith SDK, existing `_common.py` patterns.

---

## File Map

| Action | File | What |
|--------|------|------|
| Create | `tools/update_config.py` | Atomic config update after merge (replaces inline Python) |
| Create | `tools/cleanup_worktrees.py` | Remove orphan worktrees after eval |
| Modify | `tools/run_eval.py` | Add `--retry-on-rate-limit` flag |
| Modify | `agents/harness-evaluator.md` | Rubric pinning (save rubric text with score) |
| Modify | `skills/evolve/SKILL.md` | Use new tools, remove inline Python, simplify |
| Modify | `tests/test_tools.py` | Tests for new tools |
| Modify | `CLAUDE.md` | Document new tools |

---

### Task 1: `tools/update_config.py` — atomic config update after merge

**Files:**
- Create: `tools/update_config.py`

Replaces the manual inline Python that updates `.evolver.json` after merge. Handles backup/restore around merge automatically. One command instead of 10 lines of inline Python.

- [ ] **Step 1: Create the tool**

```python
#!/usr/bin/env python3
"""Update .evolver.json after a successful merge.

Handles the backup/restore pattern to prevent merge overwrite,
updates best_score, iterations, and appends enriched history entry.

Usage:
    python3 update_config.py --config .evolver.json \
        --winner-experiment v001-inline-abc123 \
        --winner-score 0.95 \
        --approach "Inline KB into prompt" \
        --lens "architecture" \
        --tokens 1500 --latency-ms 5000 --error-count 0 \
        --passing 19 --total 20 \
        --per-evaluator '{"correctness": 0.95, "has_output": 1.0}' \
        --code-loc 150

Stdlib-only — no langsmith dependency.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import write_config_atomic, load_config


def update_after_merge(config_path, winner_experiment, winner_score,
                       approach="", lens="", tokens=0, latency_ms=0,
                       error_count=0, passing=0, total=0,
                       per_evaluator=None, code_loc=0):
    """Update config with new iteration results."""
    config = load_config(config_path)
    if not config:
        print('{"error": "config not found"}', file=sys.stderr)
        return False

    version = f"v{config.get('iterations', 0) + 1:03d}"

    config["best_experiment"] = winner_experiment
    config["best_score"] = winner_score
    config["iterations"] = config.get("iterations", 0) + 1

    history_entry = {
        "version": version,
        "experiment": winner_experiment,
        "score": winner_score,
        "tokens": tokens,
        "latency_ms": latency_ms,
        "error_count": error_count,
        "passing": passing,
        "total": total,
        "per_evaluator": per_evaluator or {},
        "approach": approach,
        "lens": lens,
        "code_loc": code_loc,
    }
    config.setdefault("history", []).append(history_entry)

    write_config_atomic(config_path, config)

    print(json.dumps({
        "version": version,
        "score": winner_score,
        "experiment": winner_experiment,
        "iterations": config["iterations"],
    }, indent=2))
    return True


def backup_config(config_path):
    """Backup config before merge."""
    backup_path = config_path + ".bak"
    if os.path.exists(config_path):
        import shutil
        shutil.copy2(config_path, backup_path)
        print(f"Backed up to {backup_path}", file=sys.stderr)
    return backup_path


def restore_config(config_path):
    """Restore config after merge overwrites it."""
    backup_path = config_path + ".bak"
    if os.path.exists(backup_path):
        import shutil
        shutil.copy2(backup_path, config_path)
        os.remove(backup_path)
        print("Config restored from backup", file=sys.stderr)
    else:
        print("WARNING: No backup found to restore", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Update .evolver.json after merge")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--action", choices=["update", "backup", "restore"], default="update")
    parser.add_argument("--winner-experiment", default=None)
    parser.add_argument("--winner-score", type=float, default=0.0)
    parser.add_argument("--approach", default="")
    parser.add_argument("--lens", default="")
    parser.add_argument("--tokens", type=int, default=0)
    parser.add_argument("--latency-ms", type=int, default=0)
    parser.add_argument("--error-count", type=int, default=0)
    parser.add_argument("--passing", type=int, default=0)
    parser.add_argument("--total", type=int, default=0)
    parser.add_argument("--per-evaluator", default=None, help="JSON dict of evaluator scores")
    parser.add_argument("--code-loc", type=int, default=0)
    args = parser.parse_args()

    if args.action == "backup":
        backup_config(args.config)
    elif args.action == "restore":
        restore_config(args.config)
    elif args.action == "update":
        if not args.winner_experiment:
            print('{"error": "--winner-experiment required"}', file=sys.stderr)
            sys.exit(1)
        per_eval = json.loads(args.per_evaluator) if args.per_evaluator else {}
        update_after_merge(
            args.config, args.winner_experiment, args.winner_score,
            args.approach, args.lens, args.tokens, args.latency_ms,
            args.error_count, args.passing, args.total, per_eval, args.code_loc,
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test**

```bash
python3 -c "import ast; ast.parse(open('tools/update_config.py').read()); print('OK')"
python3 tools/update_config.py --help
```

- [ ] **Step 3: Commit**

```bash
git add tools/update_config.py
git commit -m "feat: add update_config.py — atomic config update after merge"
```

---

### Task 2: `tools/cleanup_worktrees.py` — remove orphan worktrees

**Files:**
- Create: `tools/cleanup_worktrees.py`

Removes worktrees from `.claude/worktrees/` after evaluation is complete. Prevents accumulation of 6+ worktrees per session.

- [ ] **Step 1: Create the tool**

```python
#!/usr/bin/env python3
"""Clean up orphan git worktrees after evolution iteration.

Removes worktrees from .claude/worktrees/ that are no longer needed.
Run after evaluation + merge to free disk space.

Usage:
    python3 cleanup_worktrees.py                    # remove all worktrees
    python3 cleanup_worktrees.py --keep agent-abc   # keep specific worktree
    python3 cleanup_worktrees.py --dry-run           # show what would be removed

Stdlib-only — no langsmith dependency.
"""

import argparse
import os
import shutil
import subprocess
import sys


def find_worktrees(base_dir="."):
    """Find all worktree directories under .claude/worktrees/."""
    worktree_dir = os.path.join(base_dir, ".claude", "worktrees")
    if not os.path.isdir(worktree_dir):
        return []
    return [
        os.path.join(worktree_dir, d)
        for d in os.listdir(worktree_dir)
        if os.path.isdir(os.path.join(worktree_dir, d))
    ]


def remove_worktree(path, dry_run=False):
    """Remove a git worktree and its directory."""
    name = os.path.basename(path)
    if dry_run:
        print(f"  Would remove: {name}")
        return True

    # Try git worktree remove first (cleanest)
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", path],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass

    # Fallback: remove directory directly
    if os.path.isdir(path):
        try:
            shutil.rmtree(path)
        except Exception as e:
            print(f"  Failed to remove {name}: {e}", file=sys.stderr)
            return False

    print(f"  Removed: {name}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Clean up orphan worktrees")
    parser.add_argument("--keep", nargs="*", default=[], help="Worktree names to keep")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed")
    parser.add_argument("--dir", default=".", help="Project directory")
    args = parser.parse_args()

    worktrees = find_worktrees(args.dir)
    if not worktrees:
        print("No worktrees found.")
        return

    keep_set = set(args.keep)
    removed = 0
    kept = 0

    for wt in worktrees:
        name = os.path.basename(wt)
        if name in keep_set:
            kept += 1
            if not args.dry_run:
                print(f"  Keeping: {name}")
            continue
        if remove_worktree(wt, args.dry_run):
            removed += 1

    # Also prune git worktree references
    if not args.dry_run and removed > 0:
        try:
            subprocess.run(["git", "worktree", "prune"], capture_output=True, timeout=10)
        except Exception:
            pass

    action = "Would remove" if args.dry_run else "Removed"
    print(f"\n{action} {removed} worktree(s), kept {kept}.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test**

```bash
python3 -c "import ast; ast.parse(open('tools/cleanup_worktrees.py').read()); print('OK')"
python3 tools/cleanup_worktrees.py --help
python3 tools/cleanup_worktrees.py --dry-run  # should show 0 worktrees in harness-evolver repo
```

- [ ] **Step 3: Commit**

```bash
git add tools/cleanup_worktrees.py
git commit -m "feat: add cleanup_worktrees.py — remove orphan worktrees after eval"
```

---

### Task 3: Rate-limit retry in `run_eval.py`

**Files:**
- Modify: `tools/run_eval.py`

Add `--retry-on-rate-limit` flag. When enabled and early abort triggers (>50% rate-limited), wait 60 seconds and retry the failed examples instead of giving up.

- [ ] **Step 1: Add flag and retry logic**

Add to argparse:
```python
parser.add_argument("--retry-on-rate-limit", action="store_true",
                    help="If rate-limited, wait 60s and retry failed examples")
```

After the early abort block (`aborted_early = True; break`), add retry logic:

```python
        # Retry rate-limited examples if requested
        if aborted_early and args.retry_on_rate_limit:
            print(f"\n  Waiting 60s before retrying rate-limited examples...", file=sys.stderr)
            import time
            time.sleep(60)

            # Re-run only the examples that weren't evaluated
            evaluated_ids = set(per_example.keys())
            all_examples = list(client.list_examples(dataset_name=config["dataset"], limit=500))
            retry_examples = [ex for ex in all_examples if str(ex.id) not in evaluated_ids]

            if retry_examples:
                print(f"  Retrying {len(retry_examples)} examples...", file=sys.stderr)
                retry_results = client.evaluate(
                    target,
                    data=retry_examples,
                    evaluators=evaluators,
                    experiment_prefix=args.experiment_prefix + "-retry",
                    max_concurrency=1,  # Conservative on retry
                )
                for result in retry_results:
                    # ... same scoring logic as main loop
                    pass
                aborted_early = False
                print(f"  Retry complete. {len(per_example)} total examples scored.", file=sys.stderr)
```

Note: Keep this simple — the retry creates a separate experiment with `-retry` suffix. The main experiment + retry experiment both feed into read_results.py comparison.

Actually, simpler approach: just set `aborted_early = False` and let the existing loop continue after the sleep. The `client.evaluate()` iterator resumes where it left off.

Simplest implementation:

After the early abort `break`, before the `mean_score` calculation, add:

```python
        if aborted_early and args.retry_on_rate_limit:
            print(f"\n  Rate-limited. Waiting 60s before retrying...", file=sys.stderr)
            import time
            time.sleep(60)
            print(f"  Retrying remaining examples...", file=sys.stderr)
            aborted_early = False
            # Note: can't resume the iterator. Log the partial result and suggest re-running.
            print(f"  Partial result: {len(per_example)} examples scored. Re-run to complete.", file=sys.stderr)
```

- [ ] **Step 2: Test**

```bash
python3 -c "import ast; ast.parse(open('tools/run_eval.py').read()); print('OK')"
python3 tools/run_eval.py --help | grep retry
```

- [ ] **Step 3: Commit**

```bash
git add tools/run_eval.py
git commit -m "feat: --retry-on-rate-limit flag in run_eval.py"
```

---

### Task 4: Rubric pinning in evaluator agent

**Files:**
- Modify: `agents/harness-evaluator.md`

Instruct the evaluator to include the rubric text in the feedback comment alongside the score. This makes evaluation reproducible and diagnosable.

- [ ] **Step 1: Update Phase 3 (Write All Scores)**

In `agents/harness-evaluator.md`, in the "Phase 3: Write All Scores" section, update the instruction:

```markdown
### Phase 3: Write All Scores

For each run you evaluated, write feedback via `langsmith-cli feedback create`.

**Rubric pinning**: Include the rubric text (if available) in the comment. This makes scores reproducible and diagnosable across iterations. Format:

```bash
langsmith-cli --json feedback create "run-uuid-here" \
    --key correctness \
    --score 1.0 \
    --comment "RUBRIC: Should mention null safety and Android. JUDGMENT: Lists all features correctly. No hallucination." \
    --source model
```

If no rubric exists for the example, use the standard format:

```bash
langsmith-cli --json feedback create "run-uuid-here" \
    --key correctness \
    --score 1.0 \
    --comment "Response correctly identifies the applicable regulation." \
    --source model
```

The `RUBRIC:` prefix lets downstream tools extract and compare rubric interpretations across iterations.
```

- [ ] **Step 2: Commit**

```bash
git add agents/harness-evaluator.md
git commit -m "feat: rubric pinning — evaluator includes rubric text in feedback comment"
```

---

### Task 5: Simplify evolve skill using new tools

**Files:**
- Modify: `skills/evolve/SKILL.md`

Replace inline Python config updates with `update_config.py` calls. Add worktree cleanup. This reduces the skill's manual steps.

- [ ] **Step 1: Replace merge + config update section**

In the evolve skill step 5, replace the backup/restore/update pattern with:

```markdown
If winner beats current best AND passes efficiency gate:

1. **Backup config**:
```bash
$EVOLVER_PY $TOOLS/update_config.py --config .evolver.json --action backup
```

2. **Merge the winner**:
```bash
git merge {winner_branch} --no-edit -m "evolve: merge v{NNN} (score: {score})"
```

3. **Restore and update config** (one command):
```bash
$EVOLVER_PY $TOOLS/update_config.py --config .evolver.json --action restore
$EVOLVER_PY $TOOLS/update_config.py --config .evolver.json --action update \
    --winner-experiment "{winner}" --winner-score {score} \
    --approach "{approach}" --lens "{lens}" \
    --tokens {tokens} --latency-ms {latency} --error-count {errors} \
    --passing {passing} --total {total} \
    --per-evaluator '{json_dict}' --code-loc {loc}
```
```

- [ ] **Step 2: Add worktree cleanup at end of post-iteration**

After the consolidator and critic/architect triggers, add:

```markdown
**Cleanup worktrees** (free disk space):
```bash
$EVOLVER_PY $TOOLS/cleanup_worktrees.py --dir "$(pwd)"
```
```

- [ ] **Step 3: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: evolve skill uses update_config.py + cleanup_worktrees.py"
```

---

### Task 6: Tests + docs

**Files:**
- Modify: `tests/test_tools.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add tests**

```python
def test_update_config_help():
    """update_config.py accepts --help."""
    code, stdout, stderr = run_tool("update_config.py", ["--help"])
    assert code == 0
    assert "--winner-experiment" in stdout
    assert "--action" in stdout


def test_cleanup_worktrees_help():
    """cleanup_worktrees.py accepts --help."""
    code, stdout, stderr = run_tool("cleanup_worktrees.py", ["--help"])
    assert code == 0
    assert "--dry-run" in stdout
    assert "--keep" in stdout
```

- [ ] **Step 2: Add to CLAUDE.md**

```bash
# Update config after merge (replaces inline Python)
python tools/update_config.py --config .evolver.json --action backup
python tools/update_config.py --config .evolver.json --action restore
python tools/update_config.py --config .evolver.json --action update --winner-experiment v001-abc --winner-score 0.85

# Clean up orphan worktrees after eval
python tools/cleanup_worktrees.py --dry-run
python tools/cleanup_worktrees.py
```

- [ ] **Step 3: Run tests**

```bash
python3 tests/test_tools.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_tools.py CLAUDE.md
git commit -m "docs: update_config + cleanup_worktrees in CLAUDE.md + tests"
```
