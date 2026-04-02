# Dynamic Lenses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed proposer strategy assignments with data-driven investigation lenses that let proposers self-organize their approach.

**Architecture:** Extend `synthesize_strategy.py` to generate `lenses.json` alongside `strategy.md`. The evolve skill reads lenses and spawns a dynamic number of proposers, each receiving a `<lens>` block instead of a `<strategy>` block. Proposers decide their own approach and may self-abstain. Consolidation tracks emergent approaches from `proposal.md` instead of fixed labels.

**Tech Stack:** Python 3 (stdlib only), Claude Code plugin markdown (skills, agents)

**Spec:** `docs/superpowers/specs/2026-04-02-dynamic-lenses-design.md`

---

### Task 1: Add lens generation to `synthesize_strategy.py`

**Files:**
- Modify: `tools/synthesize_strategy.py`

- [ ] **Step 1: Add `generate_lenses()` function after `synthesize()` (after line 120)**

```python
def generate_lenses(strategy, config, insights, results, memory, production, max_lenses=5):
    """Generate investigation lenses from available data sources."""
    lenses = []
    lens_id = 0

    # Failure cluster lenses (one per distinct cluster, max 3)
    for cluster in strategy.get("failure_clusters", [])[:3]:
        lens_id += 1
        desc = cluster["description"]
        severity = cluster["severity"]
        examples = []
        for ex in strategy.get("failing_examples", []):
            if ex.get("error") and cluster.get("type", "") in str(ex.get("error", "")):
                examples.append(ex["example_id"])
        if not examples:
            examples = [ex["example_id"] for ex in strategy.get("failing_examples", [])[:3]]
        lenses.append({
            "id": lens_id,
            "question": f"{desc} — what code change would fix this?",
            "source": "failure_cluster",
            "severity": severity,
            "context": {"examples": examples[:5]},
        })

    # Architecture lens from trace insights
    if insights:
        for issue in insights.get("top_issues", []):
            if issue.get("severity") == "high" and issue.get("type") in (
                "architecture", "routing", "topology", "structure",
            ):
                lens_id += 1
                lenses.append({
                    "id": lens_id,
                    "question": f"Architectural issue: {issue['description']} — what structural change would help?",
                    "source": "architecture",
                    "severity": "high",
                    "context": {"issue_type": issue["type"]},
                })
                break  # at most 1 architecture lens

    # Production lens
    if production:
        prod_issues = []
        neg = production.get("negative_feedback_inputs", [])
        if neg:
            prod_issues.append(f"Users gave negative feedback on {len(neg)} queries")
        errors = production.get("error_patterns", production.get("errors", []))
        if errors and isinstance(errors, list) and len(errors) > 0:
            prod_issues.append(f"Production errors: {str(errors[0])[:100]}")
        slow = production.get("slow_queries", [])
        if slow:
            prod_issues.append(f"{len(slow)} slow queries detected")
        if prod_issues:
            lens_id += 1
            lenses.append({
                "id": lens_id,
                "question": f"Production data shows: {'; '.join(prod_issues)}. How should the agent handle these real-world patterns?",
                "source": "production",
                "severity": "high",
                "context": {},
            })

    # Evolution memory lens — winning patterns
    if memory:
        for insight in memory.get("insights", []):
            if insight.get("type") == "strategy_effectiveness" and insight.get("recurrence", 0) >= 2:
                lens_id += 1
                lenses.append({
                    "id": lens_id,
                    "question": f"{insight['insight']} — what further improvements in this direction are possible?",
                    "source": "evolution_memory",
                    "severity": "medium",
                    "context": {"recurrence": insight["recurrence"]},
                })
                break  # at most 1 memory lens

    # Evolution memory lens — persistent failures
    if memory:
        for insight in memory.get("insights", []):
            if insight.get("type") == "recurring_failure" and insight.get("recurrence", 0) >= 3:
                lens_id += 1
                lenses.append({
                    "id": lens_id,
                    "question": f"{insight['insight']} — this has persisted {insight['recurrence']} iterations. Why?",
                    "source": "persistent_failure",
                    "severity": "critical",
                    "context": {"recurrence": insight["recurrence"]},
                })
                break  # at most 1 persistent failure lens

    # Open lens (always included)
    lens_id += 1
    lenses.append({
        "id": lens_id,
        "question": "Open investigation — read all context and investigate what stands out most to you.",
        "source": "open",
        "severity": "medium",
        "context": {},
    })

    # Sort by severity, take top max_lenses
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    lenses.sort(key=lambda l: severity_order.get(l["severity"], 2))
    lenses = lenses[:max_lenses]

    # Reassign sequential IDs after sorting/truncating
    for i, lens in enumerate(lenses):
        lens["id"] = i + 1

    return lenses
```

- [ ] **Step 2: Add `--lenses` CLI flag and wire it into `main()`**

In the `main()` function, add the argument and call:

Replace the current `main()` function (lines 192-224) with:

```python
def main():
    parser = argparse.ArgumentParser(description="Synthesize evolution strategy")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--trace-insights", default="trace_insights.json")
    parser.add_argument("--best-results", default="best_results.json")
    parser.add_argument("--evolution-memory", default="evolution_memory.json")
    parser.add_argument("--production-seed", default="production_seed.json")
    parser.add_argument("--output", default="strategy.md")
    parser.add_argument("--lenses", default=None, help="Output path for lenses JSON")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    insights = load_json_safe(args.trace_insights)
    results = load_json_safe(args.best_results)
    memory = load_json_safe(args.evolution_memory)
    production = load_json_safe(args.production_seed)

    strategy = synthesize(config, insights, results, memory, production)

    md = format_strategy_md(strategy, config)
    with open(args.output, "w") as f:
        f.write(md)

    json_path = args.output.replace(".md", ".json")
    with open(json_path, "w") as f:
        json.dump(strategy, f, indent=2)

    # Generate lenses if requested
    if args.lenses:
        max_proposers = config.get("max_proposers", 5)
        lens_list = generate_lenses(
            strategy, config, insights, results, memory, production,
            max_lenses=max_proposers,
        )
        from datetime import datetime, timezone
        lenses_output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lens_count": len(lens_list),
            "lenses": lens_list,
        }
        with open(args.lenses, "w") as f:
            json.dump(lenses_output, f, indent=2)
        print(f"Generated {len(lens_list)} lenses → {args.lenses}", file=sys.stderr)

    print(md)
```

- [ ] **Step 3: Verify it runs without errors**

Run with no data files (first-iteration scenario):

```bash
mkdir -p /tmp/lens-test && cd /tmp/lens-test
echo '{"entry_point": "python main.py", "framework": "openai", "evaluators": ["correctness"], "best_experiment": null, "best_score": 0, "iterations": 0, "history": []}' > .evolver.json
python3 /home/rp/Desktop/meta-harness/harness-evolver/tools/synthesize_strategy.py \
    --config .evolver.json \
    --output strategy.md \
    --lenses lenses.json
cat lenses.json
```

Expected: `lenses.json` with 1 lens (just the open lens, since no failure data exists).

- [ ] **Step 4: Verify with rich data**

```bash
cd /tmp/lens-test
echo '{"top_issues": [{"type": "architecture", "severity": "high", "description": "Single-call pattern with no routing", "count": 12}]}' > trace_insights.json
echo '{"per_example": {"ex-1": {"score": 0.2, "input_preview": "multi-step query", "error": "timeout"}, "ex-2": {"score": 0.3, "input_preview": "long input", "error": "context_overflow"}}}' > best_results.json
echo '{"insights": [{"type": "strategy_effectiveness", "insight": "Prompt restructuring won 3 times", "recurrence": 3}]}' > evolution_memory.json
echo '{"negative_feedback_inputs": ["bad query 1"], "error_patterns": ["timeout on long input"]}' > production_seed.json
python3 /home/rp/Desktop/meta-harness/harness-evolver/tools/synthesize_strategy.py \
    --config .evolver.json \
    --output strategy.md \
    --lenses lenses.json
python3 -c "import json; d=json.load(open('lenses.json')); print(f'{d[\"lens_count\"]} lenses:'); [print(f'  {l[\"id\"]}. [{l[\"source\"]}] {l[\"question\"][:80]}') for l in d['lenses']]"
```

Expected: 4-5 lenses from different sources (failure_cluster, architecture, production, evolution_memory, open).

- [ ] **Step 5: Clean up and commit**

```bash
rm -rf /tmp/lens-test
cd /home/rp/Desktop/meta-harness/harness-evolver
git add tools/synthesize_strategy.py
git commit -m "feat: add dynamic lens generation to synthesize_strategy.py"
```

---

### Task 2: Rewrite proposer agent for lens protocol

**Files:**
- Modify: `agents/evolver-proposer.md`

- [ ] **Step 1: Update frontmatter description**

Replace lines 1-10:

```markdown
---
name: evolver-proposer
description: |
  Self-organizing agent optimizer. Investigates a data-driven lens (question),
  decides its own approach, and modifies real code in an isolated git worktree.
  May self-abstain if it cannot add meaningful value.
tools: Read, Write, Edit, Bash, Glob, Grep
color: green
permissionMode: acceptEdits
---
```

- [ ] **Step 2: Replace title and Bootstrap section**

Replace lines 12-22 (the title through Bootstrap) with:

```markdown
# Evolver — Self-Organizing Proposer (v4)

You are an LLM agent optimizer. Your job is to improve the user's agent code to score higher on the evaluation dataset. You work in an **isolated git worktree** — you can modify any file freely without affecting the main branch.

## Bootstrap

Your prompt contains `<files_to_read>`, `<context>`, and `<lens>` blocks. You MUST:
1. Read every file listed in `<files_to_read>` using the Read tool
2. Parse the `<context>` block for current scores, failing examples, and framework info
3. Read the `<lens>` block — this is your investigation starting point
```

- [ ] **Step 3: Replace Turn Budget section**

Replace lines 24-34 (Turn Budget) with:

```markdown
## Turn Budget

You have a maximum of **16 turns**. You decide how to allocate them. General guidance:
- Spend early turns reading context and investigating your lens question
- Spend middle turns implementing changes and consulting documentation
- Reserve final turns for committing and writing proposal.md

**If you're past turn 12 and haven't started implementing**, simplify your approach. A small, focused change that works is better than an ambitious change that's incomplete.

**Context management**: After turn 8, avoid re-reading files you've already read. Reference your earlier analysis instead of re-running Glob/Grep searches.
```

- [ ] **Step 4: Replace Strategy Injection section with Lens Protocol**

Replace lines 36-46 (Strategy Injection section) with:

```markdown
## Lens Protocol

Your prompt contains a `<lens>` block with an **investigation question**. This is your starting point, not your mandate.

1. **Investigate** — dig into the data relevant to the lens question (trace insights, failing examples, code)
2. **Hypothesize** — form your own theory about what to change
3. **Decide** — choose your approach freely. You may end up solving something completely different from what the lens asks. That's fine.
4. **Implement or Abstain** — if you can add meaningful value, implement and commit. If not, abstain.

You are NOT constrained to the lens topic. The lens gives you a starting perspective. Your actual approach is yours to decide.
```

- [ ] **Step 5: Replace Phase 1-3 workflow with flexible workflow**

Replace lines 48-78 (Phase 1: Orient through Phase 3: Propose Changes) with:

```markdown
## Your Workflow

There are no fixed phases. Use your judgment to allocate turns. A typical flow:

**Orient** — Read .evolver.json, strategy.md, evolution_memory.md. Understand the framework, entry point, evaluators, current score, and what has been tried before.

**Investigate** — Read trace_insights.json and best_results.json. Understand which examples fail and why. If production_seed.json exists, understand real-world usage patterns. Focus on data relevant to your lens question.

**Decide** — Based on investigation, decide what to change. Consider:
- **Prompts**: system prompts, few-shot examples, output format instructions
- **Routing**: how queries are dispatched to different handlers
- **Tools**: tool definitions, tool selection logic
- **Architecture**: agent topology, chain structure, graph edges
- **Error handling**: retry logic, fallback strategies, timeout handling
- **Model selection**: which model for which task
```

- [ ] **Step 6: Add self-abstention section before Phase 3.5 (Context7)**

Insert before the "Phase 3.5: Consult Documentation" section:

```markdown
## Self-Abstention

If after investigating your lens you conclude you cannot add meaningful value, you may **abstain**. This is a valued contribution — it saves evaluation tokens and signals confidence that the current code handles the lens topic adequately.

To abstain, skip implementation and write only a `proposal.md`:

```markdown
## ABSTAIN
- **Lens**: {the question you investigated}
- **Finding**: {what you discovered during investigation}
- **Reason**: {why you're abstaining}
- **Suggested focus**: {optional — what future iterations should look at}
```

Then end with the return protocol using `ABSTAIN` as your approach.
```

- [ ] **Step 7: Update Rules section**

Replace line 148 (`2. **Minimal changes** — change only what's needed for your strategy`) with:

```markdown
2. **Focused changes** — change what's needed based on your investigation. Don't scatter changes across unrelated files.
```

- [ ] **Step 8: Update Return Protocol**

Replace lines 153-160 (Return Protocol) with:

```markdown
## Return Protocol

When done, end your response with:

## PROPOSAL COMPLETE
- **Version**: v{NNN}-{id}
- **Lens**: {the investigation question}
- **Approach**: {what you chose to do and why — free text, your own words}
- **Changes**: {brief list of files changed}
- **Expected impact**: {which evaluators/examples should improve}
- **Files modified**: {count}
```

- [ ] **Step 9: Commit**

```bash
git add agents/evolver-proposer.md
git commit -m "feat: rewrite proposer for lens protocol with self-abstention"
```

---

### Task 3: Update evolve skill for dynamic lens spawning

**Files:**
- Modify: `skills/evolve/SKILL.md`

- [ ] **Step 1: Update Step 1.8a to pass `--lenses` flag**

In `skills/evolve/SKILL.md`, find the synthesize_strategy.py invocation (around line 186) and replace it:

Find:
```bash
$EVOLVER_PY $TOOLS/synthesize_strategy.py \
    --config .evolver.json \
    --trace-insights trace_insights.json \
    --best-results best_results.json \
    --evolution-memory evolution_memory.json \
    --production-seed production_seed.json \
    --output strategy.md 2>/dev/null
```

Replace with:
```bash
$EVOLVER_PY $TOOLS/synthesize_strategy.py \
    --config .evolver.json \
    --trace-insights trace_insights.json \
    --best-results best_results.json \
    --evolution-memory evolution_memory.json \
    --production-seed production_seed.json \
    --output strategy.md \
    --lenses lenses.json 2>/dev/null
```

- [ ] **Step 2: Update the description paragraph after the command**

Find:
```
The `strategy.md` file is included in the proposer `<files_to_read>` block via the shared context (Step 1.9). It synthesizes trace analysis, evolution memory, and production data into an actionable document. Proposers also receive `production_seed.json` directly for access to raw production traces.
```

Replace with:
```
The `strategy.md` file is included in the proposer `<files_to_read>` block via the shared context (Step 1.9). The `lenses.json` file contains dynamically generated investigation questions — one per proposer. Each lens directs a proposer's attention to a different aspect of the problem (failure cluster, architecture, production data, evolution memory, or open investigation).
```

- [ ] **Step 3: Update Step 1.9 cache sharing note**

Find:
```
**CRITICAL for cache sharing**: The `<objective>`, `<files_to_read>`, and `<context>` blocks MUST be byte-identical across all 5 proposer prompts. Only the `<strategy>` block differs. Place the strategy block LAST in the prompt so the shared prefix is maximized.
```

Replace with:
```
**CRITICAL for cache sharing**: The `<objective>`, `<files_to_read>`, and `<context>` blocks MUST be byte-identical across all proposer prompts. Only the `<lens>` block differs. Place the lens block LAST in the prompt so the shared prefix is maximized.
```

- [ ] **Step 4: Replace Step 2 header and intro**

Find:
```
### 2. Spawn 5 Proposers in Parallel

Each proposer receives the IDENTICAL prefix (objective + files + context) followed by its unique strategy suffix.

**All 5 candidates** — `run_in_background: true, isolation: "worktree"`:

The prompt for EACH proposer follows this structure:
```

Replace with:
```
### 2. Spawn Proposers in Parallel (Dynamic Lenses)

Read `lenses.json` to get the list of investigation lenses:

```bash
LENS_COUNT=$(python3 -c "import json; print(json.load(open('lenses.json'))['lens_count'])")
```

Each proposer receives the IDENTICAL prefix (objective + files + context) followed by its unique lens.

**For each lens** — `run_in_background: true, isolation: "worktree"`:

The prompt for EACH proposer follows this structure:
```

- [ ] **Step 5: Replace the prompt template and all candidate strategy blocks**

Find the entire block from the prompt template through Candidate E (the `{SHARED_OBJECTIVE}` template through `{adaptive_briefing_e}` closing backticks). Replace with:

```markdown
```
{SHARED_OBJECTIVE}

{SHARED_FILES_BLOCK}

{SHARED_CONTEXT_BLOCK}

<lens>
Investigation question: {lens.question}

This is your STARTING POINT, not your mandate. Investigate, form your
own hypothesis, and implement whatever you conclude will help most.
You may solve something entirely different — that's fine.
If you cannot add meaningful value, ABSTAIN.

Source: {lens.source}
</lens>

<output>
1. Investigate the lens question
2. Decide your approach (or abstain)
3. If proceeding: modify code, commit, write proposal.md
4. proposal.md must include: what you chose to do, why, how it relates to the lens
</output>
```

For each lens in `lenses.json`, spawn one proposer agent:

```
Agent(
  subagent_type: "evolver-proposer",
  description: "Proposer {lens.id}: {lens.source} lens",
  isolation: "worktree",
  run_in_background: true,
  prompt: {SHARED_PREFIX + LENS_BLOCK above, with lens fields filled in}
)
```
```

- [ ] **Step 6: Update stuck detection to handle abstention**

Find:
```bash
for WORKTREE in {worktree_paths}; do
    CHANGES=$(cd "$WORKTREE" && git log --oneline -1 --since="10 minutes ago" 2>/dev/null | wc -l)
    if [ "$CHANGES" -eq 0 ]; then
        echo "Proposer in $WORKTREE made no commits — skipping"
    fi
done
```

Replace with:
```bash
for WORKTREE in {worktree_paths}; do
    if [ -f "$WORKTREE/proposal.md" ] && grep -q "## ABSTAIN" "$WORKTREE/proposal.md" 2>/dev/null; then
        echo "Proposer in $WORKTREE abstained — skipping evaluation"
    elif [ $(cd "$WORKTREE" && git log --oneline -1 --since="10 minutes ago" 2>/dev/null | wc -l) -eq 0 ]; then
        echo "Proposer in $WORKTREE made no commits — skipping"
    fi
done
```

- [ ] **Step 7: Update Step 3 experiment naming**

Find:
```bash
    --experiment-prefix v{NNN}{suffix} \
```

Replace with:
```bash
    --experiment-prefix v{NNN}-{lens_id} \
```

Where `{lens_id}` is the numeric lens ID (1, 2, 3...) instead of a letter suffix.

- [ ] **Step 8: Update Step 3.5 evaluator experiment list**

Find the evaluator agent prompt's experiment list:
```
    - {experiment_name_a}
    - {experiment_name_b}
    - {experiment_name_c}
    - {experiment_name_d}
    - {experiment_name_e}
```

Replace with:
```
    {list all experiment names from proposers that committed changes — skip abstained}
```

- [ ] **Step 9: Update Step 4 comparison command**

Find:
```bash
$EVOLVER_PY $TOOLS/read_results.py \
    --experiments "v{NNN}a,v{NNN}b,v{NNN}c,v{NNN}d,v{NNN}e" \
```

Replace with:
```bash
$EVOLVER_PY $TOOLS/read_results.py \
    --experiments "{comma-separated list of experiment names from non-abstained proposers}" \
```

- [ ] **Step 10: Update Step 6 reporting format**

Find:
```
Iteration {i}/{N} — 5 candidates evaluated:
  v{NNN}a (exploit):     {score_a} — {summary}
  v{NNN}b (explore):     {score_b} — {summary}
  v{NNN}c (crossover):   {score_c} — {summary}
  v{NNN}d ({strategy}):  {score_d} — {summary}
  v{NNN}e ({strategy}):  {score_e} — {summary}

  Winner: v{NNN}{suffix} ({score}) — merged into main
  Per-task champion: {champion} (beats winner on {N} tasks)
```

Replace with:
```
Iteration {i}/{N} — {lens_count} lenses, {evaluated_count} candidates evaluated ({abstained_count} abstained):
  {For each proposer, read proposal.md and extract the Approach field}
  v{NNN}-1 ({approach from proposal.md}):  {score} — {summary}
  v{NNN}-2 ({approach from proposal.md}):  {score} — {summary}
  v{NNN}-3 (ABSTAINED):                    --    — {reason from proposal.md}
  ...

  Winner: v{NNN}-{id} ({score}) — merged into main
  Per-task champion: {champion} (beats winner on {N} tasks)
```

- [ ] **Step 11: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: replace fixed strategy spawning with dynamic lens protocol"
```

---

### Task 4: Update consolidation to track emergent approaches

**Files:**
- Modify: `tools/consolidate.py`

- [ ] **Step 1: Replace `strategy_map` with approach extraction**

Find and remove lines 99 (the `strategy_map` dict and surrounding code that uses it). Replace the `consolidate()` function's strategy effectiveness section.

Find (lines 97-115):
```python
    # Strategy effectiveness
    winning = signals.get("winning_strategies", [])
    strategy_map = {"a": "exploit", "b": "explore", "c": "crossover", "d": "failure-targeted-1", "e": "failure-targeted-2"}
    win_counts = {}
    for w in winning:
        exp = w.get("experiment", "")
        if exp:
            suffix = exp[-1]
            name = strategy_map.get(suffix, suffix)
            win_counts[name] = win_counts.get(name, 0) + 1

    if win_counts:
        best_strategy = max(win_counts, key=win_counts.get)
        insights.append({
            "type": "strategy_effectiveness",
            "insight": f"Most winning strategy: {best_strategy} ({win_counts[best_strategy]} wins)",
            "recurrence": win_counts[best_strategy],
            "data": win_counts,
        })
```

Replace with:
```python
    # Winning approach tracking (from comparison data)
    winning = signals.get("winning_strategies", [])
    if winning:
        win_count = len(winning)
        best_score = max(w.get("score", 0) for w in winning)
        insights.append({
            "type": "strategy_effectiveness",
            "insight": f"Best candidate score: {best_score:.3f} across {win_count} iterations",
            "recurrence": win_count,
            "data": {"win_count": win_count, "best_score": best_score},
        })
```

- [ ] **Step 2: Verify consolidate.py still runs**

```bash
mkdir -p /tmp/consol-test && cd /tmp/consol-test
echo '{"best_experiment": "v001-1", "best_score": 0.75, "iterations": 2, "history": [{"version": "v001", "experiment": "v001-1", "score": 0.6}, {"version": "v002", "experiment": "v002-3", "score": 0.75}]}' > .evolver.json
echo '{"comparison": {"winner": {"experiment": "v002-3", "score": 0.75}, "all_candidates": [{"experiment": "v002-1", "score": 0.65}, {"experiment": "v002-3", "score": 0.75}]}}' > comparison.json
python3 /home/rp/Desktop/meta-harness/harness-evolver/tools/consolidate.py \
    --config .evolver.json \
    --comparison-files comparison.json \
    --output evolution_memory.md \
    --output-json evolution_memory.json
cat evolution_memory.json
```

Expected: JSON output with insights, no errors, no references to "exploit"/"explore" labels.

- [ ] **Step 3: Clean up and commit**

```bash
rm -rf /tmp/consol-test
cd /home/rp/Desktop/meta-harness/harness-evolver
git add tools/consolidate.py
git commit -m "feat: track emergent approaches instead of fixed strategy labels"
```

---

### Task 5: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the evolution loop description**

Find the section describing proposer spawning in the evolution loop (around line 89-93). Update any references to "5 proposers with strategies (exploit, explore, crossover, failure-targeted)" to reflect dynamic lenses.

Find text like:
```
Spawns 5 `evolver-proposer` agents in parallel (each in `isolation: "worktree"`, `run_in_background: true`) with strategies: exploit, explore, crossover, 2x failure-targeted
```

Replace with:
```
Spawns N `evolver-proposer` agents in parallel (each in `isolation: "worktree"`, `run_in_background: true`) with dynamic investigation lenses generated from failure clusters, architecture analysis, production data, and evolution memory
```

- [ ] **Step 2: Update the proposer agent description**

Find in the Architecture section (line 73):
```
`evolver-proposer` (green, runs in worktree with `acceptEdits`)
```

Replace with:
```
`evolver-proposer` (green, self-organizing with lens protocol, runs in worktree with `acceptEdits`)
```

- [ ] **Step 3: Update the synthesize_strategy.py description if present**

If CLAUDE.md mentions `synthesize_strategy.py`, add that it also generates `lenses.json`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for dynamic lenses architecture"
```

---

### Task 6: End-to-end verification

- [ ] **Step 1: Verify synthesize_strategy.py generates valid lenses**

```bash
cd /tmp && mkdir lens-e2e && cd lens-e2e
cat > .evolver.json << 'CONF'
{"entry_point": "python main.py", "framework": "openai", "evaluators": ["correctness", "conciseness"], "best_experiment": "v001-1", "best_score": 0.65, "iterations": 1, "history": [{"version": "v001", "experiment": "v001-1", "score": 0.65}], "max_proposers": 4}
CONF
cat > trace_insights.json << 'TI'
{"top_issues": [{"type": "architecture", "severity": "high", "description": "Single-call pattern with no error handling", "count": 8}, {"type": "prompt", "severity": "medium", "description": "System prompt too generic", "count": 5}]}
TI
cat > best_results.json << 'BR'
{"per_example": {"ex-1": {"score": 0.1, "input_preview": "multi-step reasoning query", "error": "timeout"}, "ex-2": {"score": 0.3, "input_preview": "ambiguous question", "error": null}, "ex-3": {"score": 0.9, "input_preview": "simple factual query", "error": null}}}
BR
echo '{"insights": [{"type": "strategy_effectiveness", "insight": "Prompt restructuring improved scores", "recurrence": 2}]}' > evolution_memory.json
echo '{"negative_feedback_inputs": ["bad response to X"], "error_patterns": ["rate limit exceeded"]}' > production_seed.json

python3 /home/rp/Desktop/meta-harness/harness-evolver/tools/synthesize_strategy.py \
    --config .evolver.json \
    --output strategy.md \
    --lenses lenses.json

echo "=== LENSES ==="
python3 -c "
import json
d = json.load(open('lenses.json'))
print(f'Count: {d[\"lens_count\"]}')
for l in d['lenses']:
    print(f'  {l[\"id\"]}. [{l[\"severity\"]}] ({l[\"source\"]}) {l[\"question\"][:90]}')
"
```

Expected: 4 lenses (respecting `max_proposers: 4`) from mixed sources.

- [ ] **Step 2: Verify proposer agent has no references to old strategy system**

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver
grep -n "strategy" agents/evolver-proposer.md || echo "No 'strategy' references — clean"
grep -n "exploit\|exploration\|crossover\|failure-targeted" agents/evolver-proposer.md || echo "No fixed strategy names — clean"
grep -n "lens" agents/evolver-proposer.md | head -10
```

Expected: No "strategy" references. Multiple "lens" references.

- [ ] **Step 3: Verify evolve skill references lenses, not strategies**

```bash
grep -n "strategy>" skills/evolve/SKILL.md || echo "No <strategy> tags — clean"
grep -n "lens" skills/evolve/SKILL.md | head -10
grep -n "lenses.json" skills/evolve/SKILL.md
```

Expected: No `<strategy>` tags. Multiple lens references. `lenses.json` referenced.

- [ ] **Step 4: Verify consolidate.py has no strategy_map**

```bash
grep -n "strategy_map" tools/consolidate.py || echo "No strategy_map — clean"
```

Expected: "No strategy_map — clean"

- [ ] **Step 5: Clean up**

```bash
rm -rf /tmp/lens-e2e
```

- [ ] **Step 6: Final commit with version note**

Only if all checks pass. No code changes — just a verification step.

```bash
cd /home/rp/Desktop/meta-harness/harness-evolver
git log --oneline feat/dynamic-lenses ^main
```

Expected: commits for tasks 1-5.
