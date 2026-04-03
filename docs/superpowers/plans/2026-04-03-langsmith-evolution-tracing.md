# LangSmith Evolution Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trace the evolution loop itself to LangSmith — each iteration as a run with score/approach/duration — and connect proposer traces via parent dotted_order for full hierarchical observability.

**Architecture:** New `tools/log_iteration.py` creates a LangSmith run per iteration. The evolve skill calls it post-merge. Proposers receive `CC_LANGSMITH_PARENT_DOTTED_ORDER` to nest their Claude Code traces under the iteration run. The langsmith-tracing companion plugin is recommended in docs.

**Tech Stack:** LangSmith Python SDK (`Client.create_run`, `Client.update_run`), existing `_common.py` patterns.

---

## File Map

| Action | File | What |
|--------|------|------|
| Create | `tools/log_iteration.py` | Logs iteration as LangSmith run |
| Modify | `skills/evolve/SKILL.md` | Call log_iteration post-merge + pass dotted_order to proposers |
| Modify | `README.md` | Recommend langsmith-tracing companion |
| Modify | `skills/setup/SKILL.md` | Mention companion plugin in setup |
| Modify | `CLAUDE.md` | Document log_iteration.py |
| Modify | `tests/test_tools.py` | Test for log_iteration --help |

---

### Task 1: Create `tools/log_iteration.py`

**Files:**
- Create: `tools/log_iteration.py`

Creates a LangSmith run representing one evolution iteration. Returns the run's `dotted_order` for child nesting.

- [ ] **Step 1: Create the tool**

```python
#!/usr/bin/env python3
"""Log an evolution iteration as a LangSmith run.

Creates a run in the evolution tracing project with iteration metadata
(score, approach, lens, duration, candidates). Returns the run ID and
dotted_order for nesting proposer traces as children.

Usage:
    # Start iteration (returns run_id + dotted_order for proposer nesting)
    python3 log_iteration.py --config .evolver.json --action start \
        --version v001 --project harness-evolution

    # End iteration (update with results)
    python3 log_iteration.py --config .evolver.json --action end \
        --run-id <run_id> --score 0.85 --merged true \
        --approach "inline KB" --lens "architecture" \
        --candidates 3 --duration 240

Requires: pip install langsmith
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_langsmith_api_key, load_config


def start_iteration(client, project_name, config, version):
    """Create a new LangSmith run for an iteration. Returns run_id and dotted_order."""
    from langsmith import RunTree

    run = RunTree(
        name=f"iteration-{version}",
        run_type="chain",
        project_name=project_name,
        inputs={
            "version": version,
            "best_score": config.get("best_score", 0),
            "iterations": config.get("iterations", 0),
            "mode": config.get("mode", "balanced"),
            "evaluators": config.get("evaluators", []),
        },
        extra={
            "metadata": {
                "evolver_version": version,
                "agent_project": config.get("project", "unknown"),
                "mode": config.get("mode", "balanced"),
            }
        },
    )
    run.post()

    return {
        "run_id": str(run.id),
        "dotted_order": run.dotted_order,
        "trace_id": str(run.trace_id),
    }


def end_iteration(client, run_id, score, merged, approach, lens, candidates, duration, project_name):
    """Update an existing iteration run with results."""
    outputs = {
        "score": score,
        "merged": merged,
        "approach": approach,
        "lens": lens,
        "candidates_evaluated": candidates,
    }

    client.update_run(
        run_id=run_id,
        outputs=outputs,
        end_time=datetime.now(timezone.utc),
        extra={
            "metadata": {
                "score": score,
                "merged": merged,
                "approach": approach,
                "lens": lens,
                "duration_seconds": duration,
            }
        },
    )

    # Also write feedback so LangSmith shows the score in the UI
    try:
        client.create_feedback(
            run_id=run_id,
            key="score",
            score=score,
            comment=f"{'Merged' if merged else 'Not merged'}: {approach}",
        )
    except Exception:
        pass

    return {"run_id": run_id, "score": score, "merged": merged}


def main():
    parser = argparse.ArgumentParser(description="Log evolution iteration to LangSmith")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--action", required=True, choices=["start", "end"])
    parser.add_argument("--version", default=None, help="Iteration version (e.g., v001)")
    parser.add_argument("--project", default=None, help="LangSmith project name for evolution traces")
    parser.add_argument("--run-id", default=None, help="Run ID to update (for --action end)")
    parser.add_argument("--score", type=float, default=0.0)
    parser.add_argument("--merged", type=lambda x: x.lower() == "true", default=False)
    parser.add_argument("--approach", default="")
    parser.add_argument("--lens", default="")
    parser.add_argument("--candidates", type=int, default=0)
    parser.add_argument("--duration", type=int, default=0, help="Duration in seconds")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    ensure_langsmith_api_key()

    config = load_config(args.config)
    if not config:
        print('{"error": "config not found"}')
        sys.exit(1)

    from langsmith import Client
    client = Client()

    # Default project name: harness-evolution-{agent_project}
    project_name = args.project or f"harness-evolution-{config.get('project', 'unknown')}"

    if args.action == "start":
        version = args.version or f"v{config.get('iterations', 0) + 1:03d}"
        result = start_iteration(client, project_name, config, version)
        output = json.dumps(result, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        print(output)

    elif args.action == "end":
        if not args.run_id:
            print('{"error": "--run-id required for --action end"}', file=sys.stderr)
            sys.exit(1)
        result = end_iteration(
            client, args.run_id, args.score, args.merged,
            args.approach, args.lens, args.candidates, args.duration,
            project_name,
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test**

```bash
python3 -c "import ast; ast.parse(open('tools/log_iteration.py').read()); print('OK')"
python3 tools/log_iteration.py --help
```

- [ ] **Step 3: Commit**

```bash
git add tools/log_iteration.py
git commit -m "feat: add log_iteration.py — trace evolution iterations to LangSmith"
```

---

### Task 2: Integrate into evolve skill

**Files:**
- Modify: `skills/evolve/SKILL.md`

Add `log_iteration.py` calls at iteration start and end. Pass `dotted_order` to proposers for trace nesting.

- [ ] **Step 1: Add iteration start at the beginning of the loop**

In `skills/evolve/SKILL.md`, at the beginning of "### 0. Read State" (the first step inside the loop), add:

```markdown
**Start iteration trace** (logs to LangSmith for observability):
```bash
ITER_TRACE=$($EVOLVER_PY $TOOLS/log_iteration.py --config .evolver.json --action start --version v{NNN})
ITER_RUN_ID=$(echo "$ITER_TRACE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('run_id',''))")
ITER_DOTTED_ORDER=$(echo "$ITER_TRACE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('dotted_order',''))")
```
```

- [ ] **Step 2: Pass dotted_order to proposers for trace nesting**

In the proposer spawn section, add `CC_LANGSMITH_PARENT_DOTTED_ORDER` to the shared context. In the `IMPORTANT` block where files are copied to worktrees, add:

```markdown
If the `langsmith-tracing` companion plugin is installed and `ITER_DOTTED_ORDER` is set, proposer traces will automatically nest under the iteration run in LangSmith. No extra configuration needed — the companion plugin reads `CC_LANGSMITH_PARENT_DOTTED_ORDER` from the environment.

When spawning each proposer Agent(), include in the environment:
```bash
export CC_LANGSMITH_PARENT_DOTTED_ORDER="$ITER_DOTTED_ORDER"
```
```

- [ ] **Step 3: Add iteration end after post-iteration steps**

After the "Report" line in step 6, add:

```markdown
**End iteration trace**:
```bash
$EVOLVER_PY $TOOLS/log_iteration.py --config .evolver.json --action end \
    --run-id "$ITER_RUN_ID" \
    --score {winner_score} \
    --merged {true|false} \
    --approach "{approach}" \
    --lens "{lens}" \
    --candidates {num_evaluated} \
    --duration {seconds_elapsed}
```
```

- [ ] **Step 4: Commit**

```bash
git add skills/evolve/SKILL.md
git commit -m "feat: evolve skill logs iterations to LangSmith + passes dotted_order to proposers"
```

---

### Task 3: Recommend langsmith-tracing companion

**Files:**
- Modify: `README.md`
- Modify: `skills/setup/SKILL.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add companion section to README**

After the "Requirements" section, add:

```markdown
## Companion Plugin: LangSmith Tracing

For full observability into what each proposer does during evolution (every file read, edit, and commit), install the [LangSmith tracing plugin](https://github.com/langchain-ai/langsmith-claude-code-plugins):

```
/plugin marketplace add langchain-ai/langsmith-claude-code-plugins
/plugin install langsmith-tracing@langsmith-claude-code-plugins
```

With both plugins installed, the evolution loop traces to LangSmith as a hierarchy: iteration → proposers → tool calls. Debug any iteration by clicking through in the LangSmith UI.
```

- [ ] **Step 2: Add to setup skill gotchas**

In `skills/setup/SKILL.md`, in the Gotchas section, add:

```markdown
- **Companion plugin**: For full proposer observability, recommend installing `langsmith-tracing` from `langchain-ai/langsmith-claude-code-plugins`. Each proposer's file reads, edits, and commits become visible in LangSmith.
```

- [ ] **Step 3: Add log_iteration.py to CLAUDE.md**

In the "Running tools locally" section:

```bash
# Log evolution iteration to LangSmith (creates traceable run per iteration)
python tools/log_iteration.py --config .evolver.json --action start --version v001
python tools/log_iteration.py --config .evolver.json --action end --run-id <id> --score 0.85 --merged true
```

- [ ] **Step 4: Commit**

```bash
git add README.md skills/setup/SKILL.md CLAUDE.md
git commit -m "docs: recommend langsmith-tracing companion + document log_iteration.py"
```

---

### Task 4: Tests + docs update

**Files:**
- Modify: `tests/test_tools.py`
- Modify: `docs/FEATURES.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Add test for log_iteration --help**

```python
def test_log_iteration_help():
    """log_iteration.py accepts --help."""
    code, stdout, stderr = run_tool("log_iteration.py", ["--help"])
    assert code == 0
    assert "--action" in stdout
    assert "--run-id" in stdout
```

- [ ] **Step 2: Add to FEATURES.md**

In the Visualization section:

```markdown
| **Evolution Tracing** | Each iteration logged as a LangSmith run with score, approach, duration. With the langsmith-tracing companion, proposer tool calls nest hierarchically under iterations. Full evolution timeline in LangSmith UI. |
```

- [ ] **Step 3: Update ARCHITECTURE.md Mermaid diagram**

Add `log_iteration.py` to the Tools section in the tool categories Mermaid chart:

```
archive["archive.py"]
logiter["log_iteration.py"]
```

- [ ] **Step 4: Run tests**

```bash
python3 tests/test_tools.py
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_tools.py docs/FEATURES.md docs/ARCHITECTURE.md
git commit -m "docs: evolution tracing in FEATURES + ARCHITECTURE + test"
```
