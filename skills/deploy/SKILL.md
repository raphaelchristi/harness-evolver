---
name: deploy
description: "Use when the user wants to use the best evolved harness in their project, promote a version to production, copy the winning harness back, or is done evolving and wants to apply the result."
argument-hint: "[version]"
allowed-tools: [Read, Write, Bash, Glob]
---

# /harness-evolver:deploy

Promote the best (or specified) harness version back to the user's project.

## Arguments

- `version` — optional. If not given, deploys the best version from `summary.json`.

## What To Do

### 1. Identify Best Version

```bash
python3 -c "import json; s=json.load(open('.harness-evolver/summary.json')); print(s['best']['version'], s['best']['combined_score'])"
```

Or use the user-specified version.

### 2. Show What Will Be Deployed

```bash
cat .harness-evolver/harnesses/{version}/proposal.md
cat .harness-evolver/harnesses/{version}/scores.json
```

Report: version, score, improvement over baseline, what changed.

### 3. Ask for Confirmation

> Deploy `{version}` (score: {score}, +{delta} over baseline) to your project?
> This will copy `harness.py` and `config.json` to the project root.

### 4. Copy Files

```bash
cp .harness-evolver/harnesses/{version}/harness.py ./harness.py
cp .harness-evolver/harnesses/{version}/config.json ./config.json  # if exists
```

If the original entry point had a different name (e.g., `graph.py`), ask the user where to put it.

### 5. Report

- What was copied and where
- Score improvement: baseline → deployed version
- Suggest: review the diff before committing
