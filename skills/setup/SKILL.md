---
name: evolver:setup
description: "Use when the user wants to set up the evolver in their project, optimize an LLM agent, improve agent performance, or mentions evolver for the first time in a project without .evolver.json."
argument-hint: "[directory]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion]
---

# /evolver:setup

Set up the Harness Evolver v3 in a project. Explores the codebase, configures LangSmith, runs baseline evaluation.

## Prerequisites

Check for LangSmith API key — it can be in the environment, the credentials file, or .env:

```bash
python3 -c "
import os, platform
key = os.environ.get('LANGSMITH_API_KEY', '')
if not key:
    creds = os.path.expanduser('~/Library/Application Support/langsmith-cli/credentials') if platform.system() == 'Darwin' else os.path.expanduser('~/.config/langsmith-cli/credentials')
    if os.path.exists(creds):
        for line in open(creds):
            if line.strip().startswith('LANGSMITH_API_KEY='):
                key = line.strip().split('=',1)[1].strip()
    if not key and os.path.exists('.env'):
        for line in open('.env'):
            if line.strip().startswith('LANGSMITH_API_KEY=') and not line.strip().startswith('#'):
                key = line.strip().split('=',1)[1].strip().strip('\"').strip(\"'\")
print('OK' if key else 'MISSING')
"
```

If `MISSING`: "Set your LangSmith API key: `export LANGSMITH_API_KEY=lsv2_pt_...` or run `npx harness-evolver@latest` to configure."

The tools auto-load the key from the credentials file, but the env var takes precedence.

## Resolve Tool Path and Python

```bash
# Prefer env vars set by plugin hook; fallback to legacy npx paths
TOOLS="${EVOLVER_TOOLS:-$([ -d ".evolver/tools" ] && echo ".evolver/tools" || echo "$HOME/.evolver/tools")}"
EVOLVER_PY="${EVOLVER_PY:-$([ -f "$HOME/.evolver/venv/bin/python" ] && echo "$HOME/.evolver/venv/bin/python" || echo "python3")}"
```

Use `$EVOLVER_PY` instead of `python3` for ALL tool invocations. This ensures the venv with langsmith is used.

**IMPORTANT: Never pass `LANGSMITH_API_KEY` inline in Bash commands.** The key is loaded automatically by the SessionStart hook (from credentials file or environment) and by each Python tool's `ensure_langsmith_api_key()`. Passing it inline exposes it in the output. If the key is missing, tell the user to run `export LANGSMITH_API_KEY=lsv2_pt_...` instead.

## Phase 1: Explore Project (automatic)

```bash
find . -maxdepth 3 -type f -name "*.py" -not -path "*/.venv/*" -not -path "*/node_modules/*" -not -path "*/__pycache__/*" | head -30
```

**Monorepo detection**: if the project root has multiple subdirectories with their own `main.py` or `pyproject.toml`, it's a monorepo. Use AskUserQuestion to ask WHICH app to optimize before proceeding — do NOT scan everything.

Look for:
- Entry points: files with `if __name__`, or named `main.py`, `app.py`, `agent.py`, `graph.py`, `pipeline.py`
- Existing LangSmith config: `LANGCHAIN_PROJECT` / `LANGSMITH_PROJECT` in env or `.env`
- Existing test data: JSON files with inputs, CSV files, etc.
- Dependencies: `requirements.txt`, `pyproject.toml`

To identify the **framework**, read the entry point file and its immediate imports. The proposer agents will use Context7 MCP for detailed documentation lookup — you don't need to detect every library, just identify the main framework (LangGraph, CrewAI, OpenAI Agents SDK, etc.) from the imports you see.

**Detect virtual environments** — check for venvs in the project or parent directories:
```bash
# Check common venv locations
for venv_dir in .venv venv ../.venv ../venv; do
    if [ -f "$venv_dir/bin/python" ]; then
        echo "VENV_FOUND: $venv_dir/bin/python"
        break
    fi
done
```

If a venv is found, **use it for the entry point** instead of bare `python`. The agent's dependencies are likely installed there, not in the system Python. For example: `../.venv/bin/python agent.py {input}` instead of `python agent.py {input}`.

Identify the **run command** — how to execute the agent. Use `{input}` as a placeholder for the JSON file path:
- `.venv/bin/python main.py {input}` — if venv detected (preferred)
- `python main.py {input}` — agent reads JSON file from positional arg
- `python main.py --input {input}` — agent reads JSON file from `--input` flag
- `python main.py --query {input_json}` — agent receives inline JSON string

The runner writes `{"input": "user question..."}` to a temp `.json` file and replaces `{input}` with the file path. If the entry point already contains `--input` (without placeholder), the runner appends the file path as the next argument.

If no placeholder and no `--input` flag detected, the runner appends `--input <path> --output <path>`.

## Phase 2: Confirm Configuration (interactive)

Present all detected configuration in one view with smart defaults and ask for confirmation.

Use AskUserQuestion:

```json
{
  "questions": [{
    "question": "Here's the configuration for your project:\n\n**Entry point**: {command}\n**Framework**: {framework}\n**Python**: {venv_path or 'system python3'}\n**Optimization goals**: accuracy (correctness evaluator)\n**Test data**: generate 30 examples with AI\n\nDoes this look good?",
    "header": "Setup Configuration",
    "multiSelect": false,
    "options": [
      {"label": "Looks good, proceed", "description": "Use these settings and start setup"},
      {"label": "Customize goals", "description": "Choose different optimization goals"},
      {"label": "I have test data", "description": "Use existing JSON file or LangSmith project"},
      {"label": "Let me adjust everything", "description": "Change entry point, framework, goals, and data source"}
    ]
  }]
}
```

**If "Looks good, proceed"**: Use defaults — goals=accuracy, data=generate 30 with testgen. Skip straight to Phase 3.

**If "Customize goals"**: Ask the goals question, then proceed to Phase 3 with testgen as default data source.

  Use AskUserQuestion:

  ```json
  {
    "questions": [{
      "question": "What do you want to optimize?",
      "header": "Goals",
      "multiSelect": true,
      "options": [
        {"label": "Accuracy", "description": "Correctness of outputs — LLM-as-judge evaluator"},
        {"label": "Latency", "description": "Response time — track and minimize"},
        {"label": "Token efficiency", "description": "Fewer tokens for same quality"},
        {"label": "Error handling", "description": "Reduce failures, timeouts, crashes"}
      ]
    }]
  }
  ```

  Map selections to evaluator configuration for setup.py.

### Phase 2.5: Mode Selection

```json
{
  "questions": [{
    "question": "Evolution mode?",
    "header": "Mode",
    "multiSelect": false,
    "options": [
      {"label": "light", "description": "20 examples, 2 proposers, ~2 min/iter. Good for testing."},
      {"label": "balanced (Recommended)", "description": "30 examples, 3 proposers, ~8 min/iter. Best trade-off."},
      {"label": "heavy", "description": "50 examples, 5 proposers, ~25 min/iter. Maximum quality."}
    ]
  }]
}
```

Pass selection to setup.py as `--mode light|balanced|heavy`.

The mode determines testgen count:
- `light`: generate 20 examples
- `balanced`: generate 30 examples (default, current behavior)
- `heavy`: generate 50 examples

**If "I have test data"**: Ask the data source question, then proceed to Phase 3 with accuracy as default goal.

  Use AskUserQuestion with **preview**:

  ```json
  {
    "questions": [{
      "question": "Where should test inputs come from?",
      "header": "Test data",
      "multiSelect": false,
      "options": [
        {
          "label": "Import from LangSmith",
          "description": "Use real production traces as test inputs",
          "preview": "## Import from LangSmith\n\nFetches up to 100 recent traces from your production project.\nPrioritizes traces with negative feedback.\nCreates a LangSmith Dataset with real user inputs.\n\nRequires: an existing LangSmith project with traces."
        },
        {
          "label": "I have a file",
          "description": "Point to an existing file with test inputs",
          "preview": "## Provide Test Data\n\nSupported formats:\n- JSON array of inputs\n- JSON with {\"inputs\": {...}} objects\n- CSV with input columns\n\nExample:\n```json\n[\n  {\"input\": \"What is Python?\"},\n  {\"input\": \"Explain quantum computing\"}\n]\n```"
        }
      ]
    }]
  }
  ```

  If "Import from LangSmith": discover projects and ask which one (same as v2 Phase 1.9).
  If "I have a file": ask for file path.

**If "Let me adjust everything"**: Ask all three original questions in sequence — confirm detection (entry point, framework, run command), then goals, then data source — using the question formats above.

## Phase 3: Run Setup

Build the setup.py command based on all gathered information:

```bash
$EVOLVER_PY $TOOLS/setup.py \
    --project-name "{project_name}" \
    --entry-point "{run_command}" \
    --framework "{framework}" \
    --goals "{goals_csv}" \
    ${DATASET_FROM_FILE:+--dataset-from-file "$DATASET_FROM_FILE"} \
    ${DATASET_FROM_LANGSMITH:+--dataset-from-langsmith "$DATASET_FROM_LANGSMITH"} \
    ${PRODUCTION_PROJECT:+--production-project "$PRODUCTION_PROJECT"}
```

If "Generate from code" was selected AND no test data file exists, first spawn the testgen agent to generate inputs, then pass the generated file to setup.py.

## Phase 4: Generate Test Data (if needed)

If testgen is needed, spawn it:

```
Agent(
  subagent_type: "evolver-testgen",
  description: "TestGen: generate test inputs",
  prompt: |
    <objective>
    Generate 30 diverse test inputs for this project.
    Write them as a JSON array to test_inputs.json.
    </objective>

    <files_to_read>
    {all .py files discovered in Phase 1}
    </files_to_read>

    <output>
    Create test_inputs.json with format:
    [{"input": "..."}, {"input": "..."}, ...]
    </output>
)
```

Then pass `--dataset-from-file test_inputs.json` to setup.py.

## Phase 5: Report

```
Setup complete!
  Project: evolver-{name}
  Dataset: {name}-eval-v1 ({N} examples)
  Evaluators: {list}
  Baseline score: {score}
  Config: .evolver.json

Next: run /evolver:evolve to start optimizing.
```

## Gotchas

- If `.evolver.json` already exists, ask before overwriting.
- If the agent needs a venv, the run command should activate it: `cd {dir} && .venv/bin/python main.py`
- If LangSmith connection fails, check API key and network.
- The setup requires `langsmith` (Python SDK) and `langsmith-cli` (for evaluator agent).
- **Eval concurrency** defaults to 3 (runs 3 examples in parallel). If the agent can't handle parallel execution (writes to shared files, uses a fixed port, holds a DB lock), set `eval_concurrency: 1` in `.evolver.json` after setup.
