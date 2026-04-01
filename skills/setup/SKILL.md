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

Identify the **run command** — how to execute the agent. Use `{input}` as a placeholder for the JSON file path:
- `python main.py {input}` — agent reads JSON file from positional arg
- `python main.py --input {input}` — agent reads JSON file from `--input` flag
- `python main.py --query {input_json}` — agent receives inline JSON string

The runner writes `{"input": "user question..."}` to a temp `.json` file and replaces `{input}` with the file path. If the entry point already contains `--input` (without placeholder), the runner appends the file path as the next argument.

If no placeholder and no `--input` flag detected, the runner appends `--input <path> --output <path>`.

## Phase 2: Confirm Detection (interactive)

Use AskUserQuestion:

```json
{
  "questions": [{
    "question": "Here's what I detected. Does this look right?\n\nEntry point: {path}\nFramework: {framework}\nRun command: {command}\nLangSmith: {status}",
    "header": "Confirm",
    "multiSelect": false,
    "options": [
      {"label": "Looks good, proceed", "description": "Continue with detected configuration"},
      {"label": "Let me adjust", "description": "I'll provide correct paths and commands"},
      {"label": "Wrong directory", "description": "I need to cd somewhere else first"}
    ]
  }]
}
```

## Phase 3: What to Optimize (interactive)

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

## Phase 4: Test Data Source (interactive)

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
        "label": "Generate from code",
        "description": "AI generates test inputs by analyzing your code",
        "preview": "## Generate from Code\n\nThe testgen agent reads your source code and generates\n30 diverse test inputs:\n- 40% standard cases\n- 20% edge cases\n- 20% cross-domain\n- 20% adversarial\n\nOutputs are scored by LLM-as-judge."
      },
      {
        "label": "I have test data",
        "description": "Point to an existing file with test inputs",
        "preview": "## Provide Test Data\n\nSupported formats:\n- JSON array of inputs\n- JSON with {\"inputs\": {...}} objects\n- CSV with input columns\n\nExample:\n```json\n[\n  {\"input\": \"What is Python?\"},\n  {\"input\": \"Explain quantum computing\"}\n]\n```"
      }
    ]
  }]
}
```

If "Import from LangSmith": discover projects and ask which one (same as v2 Phase 1.9).
If "I have test data": ask for file path.

## Phase 5: Run Setup

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

## Phase 6: Generate Test Data (if needed)

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

## Phase 7: Report

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
