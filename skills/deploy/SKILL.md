---
name: harness-evolver:deploy
description: "Use when the user wants to use the best evolved harness in their project, promote a version to production, copy the winning harness back, or is done evolving and wants to apply the result."
argument-hint: "[version]"
allowed-tools: [Read, Write, Bash, Glob, AskUserQuestion]
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

### 3. Ask Deploy Options (Interactive)

Use AskUserQuestion with TWO questions:

```
Question 1: "Where should the evolved harness go?"
Header: "Deploy to"
Options:
  - "Overwrite original" — Replace {original_harness_path} with the evolved version
  - "Copy to new file" — Save as harness_evolved.py alongside the original
  - "Just show the diff" — Don't copy anything, just show what changed
```

```
Question 2 (ONLY if user chose "Overwrite original"):
"Back up the current harness before overwriting?"
Header: "Backup"
Options:
  - "Yes, backup first" — Save current as {harness}.bak before overwriting
  - "No, just overwrite" — Replace directly (git history has the original)
```

### 4. Copy Files

Based on the user's choices:

**If "Overwrite original"**:
- If backup: `cp {original_harness} {original_harness}.bak`
- Then: `cp .harness-evolver/harnesses/{version}/harness.py {original_harness}`
- Copy config.json if exists

**If "Copy to new file"**:
```bash
cp .harness-evolver/harnesses/{version}/harness.py ./harness_evolved.py
cp .harness-evolver/harnesses/{version}/config.json ./config_evolved.json  # if exists
```

**If "Just show the diff"**:
```bash
diff {original_harness} .harness-evolver/harnesses/{version}/harness.py
```
Do not copy anything.

### 5. Report

- What was copied and where
- Score improvement: baseline → deployed version
- Suggest: review the diff before committing
