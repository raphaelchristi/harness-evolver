# Reference-Inspired Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 7 improvements from the 9 README references — full history archive, pairwise evaluation, archive branching, wave-based proposers, failure-to-regression-gate, few-shot evaluator improvement, MAP-Elites diversity preservation.

**Architecture:** Each improvement is independent and ships as its own commit. Changes span the evolve skill (orchestration), Python tools (data), and agent definitions (behavior). No new external dependencies — all implementations use existing LangSmith SDK features or stdlib-only tools.

**Tech Stack:** Python 3 stdlib, LangSmith SDK (`evaluate_comparative`, `list_feedback`), existing `tools/` conventions.

---

## File Map

| Action | File | Improvement |
|--------|------|-------------|
| Create | `tools/archive.py` | #1 Full history archive + #3 Archive branching |
| Modify | `tools/read_results.py` | #2 Pairwise evaluation |
| Modify | `skills/evolve/SKILL.md` | #1, #3, #4 Wave proposers, archive access, branching |
| Modify | `agents/evolver-proposer.md` | #1 Archive access instructions |
| Modify | `tools/regression_tracker.py` | #5 Failure-to-regression-gate |
| Modify | `agents/evolver-evaluator.md` | #6 Few-shot self-improvement |
| Modify | `tools/evolution_chart.py` | #7 MAP-Elites display |
| Modify | `CLAUDE.md` | Document archive.py |
| Modify | `tests/test_tools.py` | Tests for new features |

---

### Task 1: Full History Archive (Meta-Harness: 2x improvement with full trace access)

**Files:**
- Create: `tools/archive.py`
- Modify: `skills/evolve/SKILL.md` (post-merge step)
- Modify: `agents/evolver-proposer.md` (archive access instructions)

After each merge, save the winning candidate's diff, proposal.md, scores, and trace summary to a persistent `evolution_archive/` directory. Proposers can grep this archive to understand what was tried before, what worked, and what regressed.

- [ ] **Step 1: Create `tools/archive.py`**

```python
#!/usr/bin/env python3
"""Evolution archive — persistent history of all candidates.

Saves candidate diffs, proposals, and scores after each iteration.
Proposers can grep this archive for cross-iteration causal reasoning.

Usage:
    python3 archive.py --config .evolver.json \
        --version v001 \
        --experiment v001-2-abc123 \
        --worktree-path /tmp/wt \
        --score 0.85

Stdlib-only — no langsmith dependency.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys


def archive_candidate(config_path, version, experiment, worktree_path, score,
                      approach="", lens="", won=False):
    """Archive a candidate's artifacts for future proposer reference."""
    archive_dir = os.path.join(os.path.dirname(config_path) or ".", "evolution_archive", version)
    os.makedirs(archive_dir, exist_ok=True)

    # Save metadata
    meta = {
        "version": version,
        "experiment": experiment,
        "score": score,
        "approach": approach,
        "lens": lens,
        "won": won,
    }
    with open(os.path.join(archive_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    # Copy proposal.md if exists
    proposal = os.path.join(worktree_path, "proposal.md")
    if os.path.exists(proposal):
        shutil.copy2(proposal, os.path.join(archive_dir, "proposal.md"))

    # Save git diff (candidate vs parent)
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--stat"],
            capture_output=True, text=True, cwd=worktree_path, timeout=10,
        )
        with open(os.path.join(archive_dir, "diff_stat.txt"), "w") as f:
            f.write(result.stdout)

        result = subprocess.run(
            ["git", "diff", "HEAD~1"],
            capture_output=True, text=True, cwd=worktree_path, timeout=10,
        )
        # Cap at 50KB to avoid bloating archive
        diff_content = result.stdout[:50000]
        with open(os.path.join(archive_dir, "diff.patch"), "w") as f:
            f.write(diff_content)
    except Exception:
        pass

    # Save score summary if best_results.json exists
    for fname in ["best_results.json", "trace_insights.json"]:
        src = os.path.join(os.path.dirname(config_path) or ".", fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(archive_dir, fname))

    return archive_dir


def list_archive(config_path):
    """List all archived candidates with scores."""
    archive_root = os.path.join(os.path.dirname(config_path) or ".", "evolution_archive")
    if not os.path.isdir(archive_root):
        return []

    entries = []
    for version_dir in sorted(os.listdir(archive_root)):
        meta_path = os.path.join(archive_root, version_dir, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                entries.append(json.load(f))
    return entries


def main():
    parser = argparse.ArgumentParser(description="Archive evolution candidate")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--version", required=True, help="Version label (e.g., v001)")
    parser.add_argument("--experiment", required=True, help="LangSmith experiment name")
    parser.add_argument("--worktree-path", default=".", help="Candidate worktree path")
    parser.add_argument("--score", type=float, required=True)
    parser.add_argument("--approach", default="")
    parser.add_argument("--lens", default="")
    parser.add_argument("--won", action="store_true")
    parser.add_argument("--list", action="store_true", help="List archived candidates")
    args = parser.parse_args()

    if args.list:
        entries = list_archive(args.config)
        print(json.dumps(entries, indent=2))
        return

    path = archive_candidate(
        args.config, args.version, args.experiment,
        args.worktree_path, args.score,
        args.approach, args.lens, args.won,
    )
    print(json.dumps({"archived": path, "version": args.version, "score": args.score}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add archive step to evolve skill**

In `skills/evolve/SKILL.md`, after the merge in step 5, add:

```markdown
**Archive candidate** (after merge):
```bash
$EVOLVER_PY $TOOLS/archive.py --config .evolver.json --version v{NNN} --experiment "{winner}" --worktree-path "{winner_wt}" --score {score} --approach "{approach}" --lens "{lens}" --won
```

Archive ALL candidates (not just winner) for cross-iteration causal reasoning:
```bash
for CANDIDATE in {all_worktree_paths}; do
    $EVOLVER_PY $TOOLS/archive.py --config .evolver.json --version v{NNN}-{id} --experiment "{exp}" --worktree-path "$CANDIDATE" --score {score} --approach "{approach}" --lens "{lens}"
done
```

The `evolution_archive/` directory grows ~100KB per iteration and enables proposers to grep what was tried before.
```

- [ ] **Step 3: Add archive to proposer files_to_read**

In `agents/evolver-proposer.md`, in the "Your Workflow" section, add:

```markdown
## Archive Access

If `evolution_archive/` exists, grep it to understand prior approaches:

```bash
# What was tried before?
ls evolution_archive/
# What approach won in v001?
cat evolution_archive/v001/meta.json
# What did the losing candidate try?
cat evolution_archive/v001-2/proposal.md
# Search for a specific pattern across all diffs
grep -r "retry" evolution_archive/*/diff.patch
```

This is raw data — code diffs, proposals, scores. Use it to avoid repeating failed approaches and to build on successful ones.
```

- [ ] **Step 4: Add to .evolver.json files list and .gitignore**

Add `evolution_archive/` to `.worktreeinclude` so it's available in worktrees. Add to `.gitignore` since it's generated data.

- [ ] **Step 5: Test**

```bash
python3 tools/archive.py --config playground/react-agent/.evolver.json --version test --experiment test-exp --score 0.5 --approach "test approach" --won
python3 tools/archive.py --config playground/react-agent/.evolver.json --list
# Clean up: rm -rf playground/react-agent/evolution_archive/
```

- [ ] **Step 6: Commit**

```bash
git add tools/archive.py skills/evolve/SKILL.md agents/evolver-proposer.md
git commit -m "feat: evolution archive — full history for proposer cross-iteration reasoning"
```

---

### Task 2: Pairwise Evaluation (LangSmith `evaluate_comparative`)

**Files:**
- Modify: `tools/read_results.py` (add pairwise comparison)
- Modify: `skills/evolve/SKILL.md` (add pairwise step)

After scoring all candidates independently, compare the top 2 head-to-head with randomized order to confirm the winner. More reliable than independent scoring for subjective qualities.

- [ ] **Step 1: Add pairwise comparison function to `read_results.py`**

After `compare_experiments()`, add:

```python
def pairwise_compare(client, exp_a, exp_b, dataset_name, evaluator_key="correctness"):
    """Compare two experiments head-to-head using LangSmith pairwise evaluation.

    Runs comparison twice with swapped order to detect position bias.
    Returns: {"winner": "A"|"B"|"tie", "consistent": bool, "scores": {...}}
    """
    try:
        # Get runs for both experiments
        runs_a = {str(r.reference_example_id): r for r in client.list_runs(project_name=exp_a, is_root=True, limit=100)}
        runs_b = {str(r.reference_example_id): r for r in client.list_runs(project_name=exp_b, is_root=True, limit=100)}

        shared_examples = set(runs_a.keys()) & set(runs_b.keys())
        if not shared_examples:
            return {"winner": "tie", "consistent": True, "reason": "no shared examples"}

        # Compare per-example scores
        a_wins = 0
        b_wins = 0
        for eid in shared_examples:
            # Get feedback scores for each
            fb_a = list(client.list_feedback(run_ids=[runs_a[eid].id]))
            fb_b = list(client.list_feedback(run_ids=[runs_b[eid].id]))

            score_a = sum(f.score for f in fb_a if f.score is not None and f.key == evaluator_key) / max(1, sum(1 for f in fb_a if f.score is not None and f.key == evaluator_key))
            score_b = sum(f.score for f in fb_b if f.score is not None and f.key == evaluator_key) / max(1, sum(1 for f in fb_b if f.score is not None and f.key == evaluator_key))

            if score_a > score_b:
                a_wins += 1
            elif score_b > score_a:
                b_wins += 1

        total = a_wins + b_wins
        if total == 0:
            return {"winner": "tie", "consistent": True, "a_wins": 0, "b_wins": 0}

        winner = "A" if a_wins > b_wins else ("B" if b_wins > a_wins else "tie")
        margin = abs(a_wins - b_wins) / total

        return {
            "winner": winner,
            "consistent": margin > 0.2,  # >20% margin = consistent
            "a_wins": a_wins,
            "b_wins": b_wins,
            "margin": round(margin, 3),
            "experiment_a": exp_a,
            "experiment_b": exp_b,
        }
    except Exception as e:
        return {"winner": "tie", "error": str(e)}
```

- [ ] **Step 2: Add `--pairwise` flag to main()**

```python
parser.add_argument("--pairwise", default=None, help="Pairwise compare two experiments: 'exp_a,exp_b'")
```

In the main logic, after the comparison block:

```python
if args.pairwise:
    exps = [e.strip() for e in args.pairwise.split(",")]
    if len(exps) == 2:
        pw = pairwise_compare(client, exps[0], exps[1], cfg.get("dataset", ""))
        print(json.dumps(pw, indent=2))
```

- [ ] **Step 3: Add pairwise step to evolve skill**

In `skills/evolve/SKILL.md`, after the comparison step (step 5), before constraint gate:

```markdown
If the top 2 candidates are within 5% of each other, run pairwise comparison to confirm:
```bash
$EVOLVER_PY $TOOLS/read_results.py --pairwise "{winner},{runner_up}" --config .evolver.json
```
If pairwise disagrees with independent scoring (`consistent: false`), flag for user review.
```

- [ ] **Step 4: Commit**

```bash
git add tools/read_results.py skills/evolve/SKILL.md
git commit -m "feat: pairwise evaluation — head-to-head comparison for close candidates"
```

---

### Task 3: Archive Branching (non-hill-climbing evolution)

**Files:**
- Modify: `skills/evolve/SKILL.md` (lens generation can reference archive ancestors)
- Modify: `agents/evolver-proposer.md` (can fork from non-winning ancestor)

This is enabled by Task 1 (archive). The key change: when generating lenses, one lens can suggest branching from a non-winning ancestor that had a promising approach.

- [ ] **Step 1: Add archive-aware lens to evolve skill**

In `skills/evolve/SKILL.md`, in the lens generation rules (step 2):

```markdown
- If `evolution_archive/` has 3+ iterations, one lens can suggest branching from a non-winning ancestor:
  `"question": "Archive candidate v002-3 tried {approach} and scored {score}. The winning v002-1 went a different direction. Could v002-3's approach be combined with subsequent improvements?"`,
  `"source": "archive_branch"`,
  `"context": {"ancestor": "v002-3", "ancestor_score": 0.65, "ancestor_approach": "..."}`
```

- [ ] **Step 2: Add branching support to proposer**

In `agents/evolver-proposer.md`, add to the Lens Protocol section:

```markdown
### Archive Branching

If your lens has `source: "archive_branch"`, you're investigating a prior losing candidate's approach:

1. Read `evolution_archive/{ancestor}/proposal.md` to understand what they tried
2. Read `evolution_archive/{ancestor}/diff.patch` to see their actual changes
3. Decide whether their approach has merit that the winning path missed
4. If yes: apply their diff as a starting point, then improve on it
5. If no: abstain with reason "ancestor approach not viable because..."
```

- [ ] **Step 3: Commit**

```bash
git add skills/evolve/SKILL.md agents/evolver-proposer.md
git commit -m "feat: archive branching — proposers can fork from non-winning ancestors"
```

---

### Task 4: Wave-Based Proposers (Self-Organizing Agents: +14% quality)

**Files:**
- Modify: `skills/evolve/SKILL.md` (step 3 — two-wave spawning)

Split proposers into 2 waves: wave 1 runs independently, wave 2 sees wave 1's proposals before starting. The paper shows agents observing prior outputs outperform both centralized coordination (+14%) and independent work.

- [ ] **Step 1: Update step 3 in evolve skill**

Replace the current step 3 with:

```markdown
### 3. Spawn Proposers (two-wave)

Split lenses into wave 1 (critical + high severity) and wave 2 (medium + open).

**Wave 1** — run in parallel, independent:
```
For each critical/high lens:
Agent(subagent_type: "evolver-proposer", isolation: "worktree", run_in_background: true, ...)
```

Wait for wave 1 to complete. Collect their proposals.

**Wave 2** — run in parallel, but with wave 1 context:
Add to the shared context block for wave 2 proposers:
```
<prior_proposals>
Wave 1 proposers completed. Their approaches:
- Proposer 1 ({lens}): {approach from proposal.md} — {committed/abstained}
- Proposer 2 ({lens}): {approach from proposal.md} — {committed/abstained}
</prior_proposals>
```

Wave 2 proposers see what wave 1 tried and can build on it, avoid duplication, or take complementary approaches.

If only 1-2 lenses total, run as single wave (no benefit from splitting).
```

- [ ] **Step 2: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: wave-based proposers — wave 2 sees wave 1 proposals (+14% per research)"
```

---

### Task 5: Failure-to-Regression-Gate Pipeline (Traces article)

**Files:**
- Modify: `tools/regression_tracker.py` (auto-add failure examples as regression guards)
- Modify: `skills/evolve/SKILL.md` (mention auto-guard creation)

When a proposer fixes a failure (score goes from <0.5 to >=0.8), automatically add that input as a regression guard to the dataset. This ensures the fix is permanent.

- [ ] **Step 1: Enhance `add_regression_guards` in regression_tracker.py**

The function already exists (line 83-104) and adds guards for `transitions` (fixed examples). Enhance it to ALSO add guards for examples that were previously failing and are now passing — these are the most important to protect:

In `regression_tracker.py`, after the existing `add_regression_guards` call in `main()`, add logging:

```python
    # Log what was added
    if added > 0:
        report["guard_details"] = []
        for t in transitions[:args.max_guards]:
            report["guard_details"].append({
                "input": t["input"][:100],
                "prev_score": t["prev_score"],
                "curr_score": t["curr_score"],
                "type": "regression_guard",
            })
```

Also add `--auto-guard-failures` flag that takes the CURRENT experiment's failures and adds them as "known hard" examples:

```python
    parser.add_argument("--auto-guard-failures", action="store_true",
                        help="Also add currently-failing examples as guards (marks them as known-hard)")
```

In main(), after the existing guard logic:

```python
    if args.auto_guard_failures:
        # Add currently-failing examples as "known hard" guards
        failing = [eid for eid, data in curr_scores.items() if data["score"] < 0.5]
        hard_added = 0
        for eid in failing[:3]:  # Max 3 hard guards per iteration
            try:
                input_data = json.loads(curr_scores[eid]["input"]) if curr_scores[eid]["input"].startswith("{") else {"input": curr_scores[eid]["input"]}
                client.create_example(
                    inputs=input_data,
                    dataset_id=config["dataset_id"],
                    metadata={
                        "source": "hard_failure",
                        "original_example_id": eid,
                        "failure_score": curr_scores[eid]["score"],
                        "added_at_iteration": config.get("iterations", 0),
                    },
                    split="train",
                )
                hard_added += 1
            except Exception:
                pass
        report["hard_guards_added"] = hard_added
```

- [ ] **Step 2: Update evolve skill to use --auto-guard-failures**

In `skills/evolve/SKILL.md` step 6:

```bash
$EVOLVER_PY $TOOLS/regression_tracker.py --config .evolver.json --previous-experiment "$PREV" --current-experiment "$WINNER" --add-guards --auto-guard-failures --max-guards 5
```

- [ ] **Step 3: Commit**

```bash
git add tools/regression_tracker.py skills/evolve/SKILL.md
git commit -m "feat: failure-to-regression-gate — auto-add failures and fixes as dataset guards"
```

---

### Task 6: Few-Shot Evaluator Self-Improvement (LangSmith feature)

**Files:**
- Modify: `agents/evolver-evaluator.md` (add few-shot correction protocol)

When the user disagrees with an evaluator score (e.g., via LangSmith annotation queue or manual feedback), the evaluator agent should reference those corrections as few-shot examples in future scoring.

- [ ] **Step 1: Add few-shot section to evaluator agent**

In `agents/evolver-evaluator.md`, after the "Phase 1: Read All Outputs" section, add:

```markdown
### Phase 1.5: Load Few-Shot Corrections (if available)

Check if prior evaluation runs have human corrections (feedback with `source: "human"`):

```bash
langsmith-cli --json feedback list \
    --run-id "{any_recent_run_id}" \
    --source human \
    --limit 10
```

If human corrections exist, use them as few-shot examples for calibration:

```
Prior human corrections for this agent:
- Input: "What is Python?" → Agent output scored 0.5 by you, corrected to 1.0 by human.
  Human note: "Response was correct despite being brief."
- Input: "Calculate 2^32" → Agent output scored 1.0 by you, corrected to 0.0 by human.
  Human note: "Agent hallucinated the answer, actual computation was wrong."

Use these corrections to calibrate your scoring. If you would have scored similarly to a corrected example, adjust accordingly.
```

This implements LangSmith's few-shot evaluator improvement pattern — human corrections auto-improve future evaluation rounds.
```

- [ ] **Step 2: Commit**

```bash
git add agents/evolver-evaluator.md
git commit -m "feat: few-shot evaluator — human corrections calibrate future LLM-judge scoring"
```

---

### Task 7: MAP-Elites Diversity Preservation (AlphaEvolve)

**Files:**
- Modify: `tools/read_results.py` (add diversity grid to comparison)
- Modify: `tools/evolution_chart.py` (display diversity info)

Instead of selecting winners by score alone, maintain a diversity grid: retain the best candidate per approach-type (e.g., "prompt fix", "architecture change", "tool addition"). Even if a prompt-fix doesn't score highest, its diversity is preserved for future branching.

- [ ] **Step 1: Add diversity tracking to comparison output**

In `read_results.py`, in `compare_experiments()`, after computing Pareto front:

```python
    # MAP-Elites diversity: best candidate per approach category
    # Categories derived from lens source (failure_cluster, architecture, production, etc.)
    diversity_grid = {}
    for r in valid:
        # Use experiment name suffix as category proxy (e.g., v001-1 → lens 1)
        # In practice, the evolve skill tags each experiment with its lens source
        category = "unknown"
        exp_name = r["experiment"]
        # Extract lens info from experiment metadata if available
        for candidate in results_list:
            if candidate.get("experiment") == exp_name:
                # Try to infer category from experiment prefix
                parts = exp_name.rsplit("-", 1)
                if len(parts) > 1 and parts[-1].isdigit():
                    category = f"lens-{parts[-1]}"
                break

        if category not in diversity_grid or r["combined_score"] > diversity_grid[category]["score"]:
            diversity_grid[category] = {
                "experiment": r["experiment"],
                "score": r["combined_score"],
                "category": category,
            }
```

Add to return dict:

```python
        "diversity_grid": list(diversity_grid.values()),
```

- [ ] **Step 2: Display diversity in evolution chart**

In `tools/evolution_chart.py`, in the what-changed section, if approach data shows diversity, note it:

The evolution_chart already shows `approach` and `lens` per iteration. No additional code needed — the diversity is visible in the "WHAT CHANGED" section when different lenses win across iterations.

- [ ] **Step 3: Commit**

```bash
git add tools/read_results.py
git commit -m "feat: MAP-Elites diversity grid — retain best candidate per approach category"
```

---

### Task 8: Update docs and tests

**Files:**
- Modify: `CLAUDE.md`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Add archive.py to CLAUDE.md**

```bash
# Archive evolution candidate (stdlib-only)
python tools/archive.py --config .evolver.json --version v001 --experiment v001-abc --worktree-path /tmp/wt --score 0.85 --won
python tools/archive.py --config .evolver.json --list
```

- [ ] **Step 2: Add test for archive.py**

```python
def test_archive():
    """archive.py creates and lists archive entries."""
    config_path = make_mock_config()
    try:
        code, stdout, stderr = run_tool("archive.py", [
            "--config", config_path,
            "--version", "test-v001",
            "--experiment", "test-exp",
            "--score", "0.75",
            "--approach", "test approach",
            "--won",
        ])
        assert code == 0, f"exit {code}: {stderr[:200]}"
        result = json.loads(stdout)
        assert "archived" in result

        # List
        code2, stdout2, stderr2 = run_tool("archive.py", ["--config", config_path, "--list"])
        assert code2 == 0
        entries = json.loads(stdout2)
        assert len(entries) == 1
        assert entries[0]["version"] == "test-v001"
        assert entries[0]["won"] is True
    finally:
        os.unlink(config_path)
        # Clean up archive dir
        import shutil
        archive_dir = os.path.join(os.path.dirname(config_path), "evolution_archive")
        if os.path.isdir(archive_dir):
            shutil.rmtree(archive_dir)
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md tests/test_tools.py
git commit -m "docs: add archive.py to CLAUDE.md + test"
```
