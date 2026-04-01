---
name: evolver:status
description: "Use when the user asks about evolution progress, current scores, best version, how many iterations ran, or whether the loop is stagnating."
allowed-tools: [Read, Bash]
---

# /evolver:status

Show current evolution progress.

## What To Do

Read `.evolver.json` and report:

```bash
python3 -c "
import json
c = json.load(open('.evolver.json'))
print(f'Project: {c[\"project\"]}')
print(f'Dataset: {c[\"dataset\"]}')
print(f'Framework: {c[\"framework\"]}')
print(f'Evaluators: {c[\"evaluators\"]}')
print(f'Iterations: {c[\"iterations\"]}')
print(f'Best: {c[\"best_experiment\"]} (score: {c[\"best_score\"]:.3f})')
print(f'Baseline: {c[\"history\"][0][\"score\"]:.3f}' if c['history'] else 'No baseline')
print()
print('History:')
for h in c.get('history', []):
    print(f'  {h[\"version\"]}: {h[\"score\"]:.3f}')
"
```

Detect stagnation: if last 3 scores are within 1% of each other, warn.
Detect regression: if current best is lower than a previous best, warn.

Print LangSmith URL for the best experiment if available.
