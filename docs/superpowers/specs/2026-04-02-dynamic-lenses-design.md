# Dynamic Lenses: Self-Organizing Proposers for Harness Evolver

*Design spec for replacing fixed strategy assignments with data-driven investigation lenses.*

**Date**: 2026-04-02
**Branch**: `feat/dynamic-lenses`
**Based on**: Dochkina (2026), "Drop the Hierarchy and Roles: How Self-Organizing LLM Agents Outperform Designed Structures" (arxiv:2603.28990)
**Baseline**: harness-evolver v4.0.2

## Problem

The proposer system uses fixed strategy labels (exploit, explore, crossover, failure-targeted) assigned by the evolve skill. This creates five layers of rigidity:

1. **Fixed roles** — Proposer A is always "exploit", B is always "explore", regardless of what the data suggests
2. **Fixed count** — Always 5 candidates, even when fewer would suffice or more would help
3. **No self-abstention** — All 5 produce output even when redundant
4. **Prescribed workflow** — 4-phase Orient/Diagnose/Propose/Commit with fixed turn allocation
5. **Label-based tracking** — Consolidation maps suffix letters to strategy names, not to what proposers actually did

The paper (25,000-task experiment, 8 models, 4-256 agents) found that the Coordinator protocol (our current model — central agent assigns roles) underperforms the Sequential protocol (agents self-select roles based on predecessors' output) by 14%.

## Constraint

The user requires **parallel execution**. Sequential processing (5x slower) is not acceptable. This rules out the paper's Sequential protocol directly.

## Solution: Attentional Asymmetry via Dynamic Lenses

Replace fixed strategy labels with **investigation questions (lenses)** generated dynamically from the current iteration's data. Each proposer receives a different question as a starting point, creating **information asymmetry** in parallel — the same mechanism that makes Sequential work, adapted for concurrent execution.

### What changes

| Component | Before (v4.0.2) | After (lenses) |
|---|---|---|
| `synthesize_strategy.py` | Outputs strategy.md | Outputs strategy.md + lenses.json |
| `evolver-proposer.md` | Receives `<strategy>`, follows it | Receives `<lens>`, investigates, decides own approach |
| `evolve/SKILL.md` Step 2 | Fixed 5 candidates A-E with fixed roles | Dynamic N candidates from lenses.json |
| `consolidate.py` | Tracks by label (`a=exploit`) | Tracks by self-described approach from proposal.md |
| Reporting | "v001a (exploit): 0.78" | "v001-1 (restructured prompt routing): 0.78" |

### What stays the same

- Parallel execution (`run_in_background: true`, `isolation: "worktree"`)
- KV cache optimization (shared prefix byte-identical, lens block goes last)
- Evaluation flow (run_eval.py, evaluator agent, read_results.py)
- Winner selection (highest combined score)
- Critic and architect triggers
- Gate system (score, cost, convergence)
- strategy.md as shared context document
- evolution_memory.md as cross-iteration memory

## Design

### 1. Lens Generation (`synthesize_strategy.py`)

New function `generate_lenses()` produces investigation questions from available data sources:

| Source | Lens type | Generation logic |
|---|---|---|
| `best_results.json` failure clusters | Failure lens | One lens per distinct failure cluster (score < 0.5), max 3. Question: "Why do examples X, Y, Z fail with [pattern]?" |
| `trace_insights.json` top issues | Architecture lens | If severity=high issue relates to structure/topology. Question: "The [topology] has [bottleneck] — what structural change would help?" |
| `production_seed.json` patterns | Production lens | If negative feedback or error patterns exist. Question: "Production shows [pattern] — how should the agent handle this?" |
| `evolution_memory.json` recurring wins | Memory lens | If a strategy type won 2+ times. Question: "[Approach] has worked N times — what further improvements in this direction?" |
| `evolution_memory.json` persistent failures | Persistent lens | If a failure pattern recurred 3+ iterations. Question: "[Pattern] has persisted N iterations — why?" |
| Always included | Open lens | "Read all context and investigate what stands out most to you." |

**Lens count**: Dynamic. Minimum 2 (1 data-driven + 1 open), maximum from `.evolver.json` field `max_proposers` (default 5). Lenses sorted by severity; top N selected.

**Output format** (`lenses.json`):
```json
{
  "generated_at": "2026-04-02T15:30:00Z",
  "lens_count": 4,
  "lenses": [
    {
      "id": 1,
      "question": "Examples 7, 12, 23 fail with context overflow on multi-paragraph inputs. How can the agent handle long inputs?",
      "source": "failure_cluster",
      "severity": "critical",
      "context": {"examples": ["ex-7", "ex-12", "ex-23"], "error_pattern": "context_overflow"}
    },
    {
      "id": 2,
      "question": "Production traces show 23% of queries are multi-step reasoning but agent has no routing. Would a query classifier help?",
      "source": "production",
      "severity": "high",
      "context": {"traffic_pct": 0.23, "category": "multi_step"}
    },
    {
      "id": 3,
      "question": "Prompt restructuring won 3 of 5 iterations. What further prompt improvements are possible?",
      "source": "evolution_memory",
      "severity": "high",
      "context": {"win_count": 3, "approach": "prompt_restructuring"}
    },
    {
      "id": 4,
      "question": "Open investigation — what does the data tell you that the other lenses missed?",
      "source": "open",
      "severity": "medium",
      "context": {}
    }
  ]
}
```

**First iteration** (no historical data): Generate lenses from code analysis only — entry point structure, error handling gaps, prompt specificity. Typically 2-3 lenses.

### 2. Proposer Agent (`evolver-proposer.md`)

Replace the "Strategy Injection" section with a "Lens Protocol" section.

**Remove:**
- Strategy injection section (lines 37-46 current)
- Fixed 4-phase workflow with turn allocations (lines 25-31 current)
- Strategy-specific Return Protocol fields

**Add — Lens Protocol:**

The proposer receives a `<lens>` block with an investigation question. The protocol:

1. **Read** strategy.md, evolution_memory.md, and the lens question
2. **Investigate** — dig into the data relevant to the lens (trace insights, failing examples, code)
3. **Hypothesize** — form your own theory about what to change
4. **Decide** — choose your approach freely. The lens is a starting point, not a mandate. You may end up solving something different than the question suggests.
5. **Implement or Abstain** — if you can add value, implement and commit. If not, abstain.

**Self-abstention protocol:**

If the proposer concludes it cannot add meaningful value, it writes in proposal.md:

```markdown
## ABSTAIN
- **Lens**: {the question investigated}
- **Finding**: {what was discovered during investigation}
- **Reason**: {why abstaining — e.g., already handled, infrastructure issue, not a code problem}
- **Suggested focus**: {optional pointer for future iterations}
```

Abstained candidates skip evaluation (no run_eval.py, no evaluator agent scoring).

**Turn budget:**

Keep the 16-turn maximum as a resource constraint, but remove the fixed phase allocation. The proposer decides how to allocate turns. Keep the guidance: "If past turn 12 and haven't started implementing, simplify."

**proposal.md format change:**

```markdown
## PROPOSAL COMPLETE
- **Version**: v{NNN}-{id}
- **Lens**: {the question investigated}
- **Approach**: {self-described — what you chose to do and why}
- **Changes**: {files changed}
- **Expected impact**: {which evaluators/examples should improve}
```

The "Approach" field replaces the old "Strategy" field. It's free-text, written by the proposer, describing what it actually did.

### 3. Evolve Skill (`evolve/SKILL.md`)

**Step 1.8a** — Add `--lenses` flag:

```bash
$EVOLVER_PY $TOOLS/synthesize_strategy.py \
    --config .evolver.json \
    --trace-insights trace_insights.json \
    --best-results best_results.json \
    --evolution-memory evolution_memory.json \
    --production-seed production_seed.json \
    --output strategy.md \
    --lenses lenses.json
```

**Step 1.9** — Shared prefix unchanged in structure. The `<lens>` block replaces `<strategy>` at the end for cache sharing.

**Step 2** — Replace fixed 5-candidate spawn:

```
Read lenses.json → N lenses (typically 2-5)

For each lens:
  Agent(
    subagent_type: "evolver-proposer",
    description: "Proposer {id}: {lens.source} lens",
    isolation: "worktree",
    run_in_background: true,
    prompt: |
      {SHARED_OBJECTIVE}
      {SHARED_FILES_BLOCK}
      {SHARED_CONTEXT_BLOCK}

      <lens>
      Investigation question: {lens.question}

      This is your STARTING POINT, not your mandate. Investigate, form your
      own hypothesis, and implement whatever you conclude will help most.
      You may solve something entirely different — that's fine.
      If you cannot add meaningful value, ABSTAIN.

      Source data: {lens.source}
      {lens.context as additional detail if relevant}
      </lens>

      <output>
      1. Investigate the lens question
      2. Decide your approach (or abstain)
      3. If proceeding: modify code, commit, write proposal.md
      4. proposal.md must include: what you chose to do, why, how it relates to the lens
      </output>
  )
```

After all complete, check which committed and which abstained:

```bash
for WORKTREE in {worktree_paths}; do
    if grep -q "## ABSTAIN" "$WORKTREE/proposal.md" 2>/dev/null; then
        echo "Proposer abstained — skipping evaluation"
    elif [ $(cd "$WORKTREE" && git log --oneline -1 --since="10 minutes ago" | wc -l) -eq 0 ]; then
        echo "Proposer made no commits — skipping"
    fi
done
```

Only evaluate proposers that committed changes (not abstained, not stuck).

**Candidate naming**: Change from `v{NNN}a`, `v{NNN}b` to `v{NNN}-1`, `v{NNN}-2` etc. (numeric, not tied to strategy letters).

**Step 6 reporting** — Use self-described approach:

```
Iteration 3/5 — 4 lenses, 3 candidates evaluated (1 abstained):
  v003-1 (restructured prompt routing):   0.82 — added query classifier
  v003-2 (added retry logic for timeouts): 0.78 — exponential backoff
  v003-3 (ABSTAINED):                     --   — lens target already handled
  v003-4 (few-shot examples for edge):     0.85 — 3 examples added

  Winner: v003-4 (0.85) — merged into main
```

### 4. Consolidation (`consolidate.py`)

**Remove** the `strategy_map` dictionary (line 99).

**Add** approach extraction from proposal.md:

```python
def extract_approach(proposal_content):
    """Extract self-described approach from proposal.md."""
    for line in proposal_content.split("\n"):
        if line.strip().startswith("**Approach**:"):
            return line.split(":", 1)[1].strip()
    return "unknown"
```

**Track by emergent approach** instead of fixed label. The consolidation insight becomes:
- "Most winning approach type: prompt modifications (3 wins)" instead of "Most winning strategy: exploit (3 wins)"
- Approaches can be clustered by similarity for pattern detection

### 5. `.evolver.json` schema addition

Add optional field:

```json
{
  "max_proposers": 5
}
```

Default 5 if not present. Controls upper bound on lenses generated. User can set lower (3 for fast iterations) or higher (7 for thorough exploration).

## Mapping to Paper Concepts

| Paper finding | Our implementation |
|---|---|
| "Define mission and values, not role assignments" | strategy.md = mission context, lens = investigation starting point, not role |
| "Information asymmetry drives differentiation" | Each proposer starts investigating different data via unique lens |
| "5,006 unique roles from 8 agents" | Proposers write self-described approach in proposal.md, tracked in consolidation |
| "Self-abstention (8.6% in strong models)" | ABSTAIN protocol in proposal.md, skip evaluation |
| "Minimal scaffolding (fixed ordering only)" | Minimal scaffolding: lens as starting point only |
| "Coordinator < Sequential by 14%" | strategy.md remains as coordinator doc, but role assignment replaced with lens autonomy |
| "Scaling: quality stable 8-256 agents" | Dynamic proposer count (2-5) adapts to data, not fixed at 5 |

## Files to modify

1. `tools/synthesize_strategy.py` — Add `generate_lenses()` function, `--lenses` CLI flag, lens generation from all data sources
2. `agents/evolver-proposer.md` — Replace Strategy Injection with Lens Protocol, add self-abstention, remove fixed phases
3. `skills/evolve/SKILL.md` — Step 1.8a adds `--lenses`, Step 2 reads lenses.json and spawns dynamic count, update reporting
4. `tools/consolidate.py` — Remove `strategy_map`, add `extract_approach()`, track by emergent description
5. `CLAUDE.md` — Update architecture description

## Out of scope

- Sequential protocol (requires serial execution, rejected by user)
- Agent Teams (experimental Claude Code feature, not stable enough)
- Changes to evaluation flow (run_eval.py, evaluator agent, read_results.py)
- Changes to critic, architect, or gate system
- New agent types or tools beyond modifications listed
