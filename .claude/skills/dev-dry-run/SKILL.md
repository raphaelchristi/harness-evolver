---
name: dev:dry-run
description: "Use when the user wants to smoke-test the evolve pipeline, test tools, or verify the plugin works end-to-end. Also use when the user says 'dry run', 'smoke test', or 'test pipeline'."
allowed-tools: [Read, Bash, Glob, Grep]
---

# /dev:dry-run

Smoke-test the evolve pipeline. Two modes depending on whether LANGSMITH_API_KEY is available.

## Resolve Paths

```bash
TOOLS="${EVOLVER_TOOLS:-$([ -d "tools" ] && echo "tools" || echo "$HOME/.evolver/tools")}"
EVOLVER_PY="${EVOLVER_PY:-$([ -f "$HOME/.evolver/venv/bin/python" ] && echo "$HOME/.evolver/venv/bin/python" || echo "python3")}"
```

## Check: Online or Offline?

```bash
if [ -n "$LANGSMITH_API_KEY" ]; then
    echo "MODE: Online (LANGSMITH_API_KEY found)"
    MODE="online"
else
    echo "MODE: Offline (no LANGSMITH_API_KEY)"
    MODE="offline"
fi
```

## Offline Mode (no API key)

Validate tool syntax and argparse consistency:

```bash
echo "=== Tool Syntax Check ==="
for f in $TOOLS/*.py; do
    python3 -c "import ast; ast.parse(open('$f').read())" 2>&1
    if [ $? -eq 0 ]; then echo "OK: $(basename $f)"; else echo "FAIL: $(basename $f)"; fi
done

echo ""
echo "=== Argparse Flags Check ==="
for f in $TOOLS/*.py; do
    $EVOLVER_PY "$f" --help > /dev/null 2>&1
    if [ $? -eq 0 ]; then echo "OK: $(basename $f) --help"; else echo "FAIL: $(basename $f) --help"; fi
done

echo ""
echo "=== Skill Cross-Reference Check ==="
# Check every tool referenced in evolve skill exists
for TOOL in $(grep -oh '\$TOOLS/[a-z_]*.py' skills/evolve/SKILL.md | sed 's/\$TOOLS\///' | sort -u); do
    if [ -f "$TOOLS/$TOOL" ]; then
        echo "OK: $TOOL referenced and exists"
    else
        echo "FAIL: $TOOL referenced in evolve skill but not found"
    fi
done
```

## Online Mode (with API key)

Run the full pipeline with a mock agent:

### 1. Create temp directory with mock agent

```bash
TMPDIR=$(mktemp -d)
cat > "$TMPDIR/agent.py" << 'PYEOF'
import json, sys
input_path = sys.argv[1] if len(sys.argv) > 1 else None
if input_path:
    with open(input_path) as f:
        data = json.load(f)
    question = data.get("input", data.get("question", ""))
    print(json.dumps({"output": f"Mock answer to: {question}"}))
else:
    print(json.dumps({"output": "No input provided"}))
PYEOF

cat > "$TMPDIR/test_inputs.json" << 'JSONEOF'
[
    {"input": "What is 2+2?"},
    {"input": "Name a color"},
    {"input": "What is Python?"}
]
JSONEOF
echo "Mock agent created at $TMPDIR"
```

### 2. Run setup

```bash
$EVOLVER_PY $TOOLS/setup.py \
    --project-name "dry-run-test" \
    --entry-point "python3 $TMPDIR/agent.py {input}" \
    --framework "unknown" \
    --goals "accuracy" \
    --dataset-from-file "$TMPDIR/test_inputs.json" \
    --output "$TMPDIR/.evolver.json"
```

### 3. Run eval

```bash
$EVOLVER_PY $TOOLS/run_eval.py \
    --config "$TMPDIR/.evolver.json" \
    --worktree-path "$TMPDIR" \
    --experiment-prefix "dry-run-v001a"
```

### 4. Read results

```bash
$EVOLVER_PY $TOOLS/read_results.py \
    --experiment "dry-run-v001a" \
    --config "$TMPDIR/.evolver.json" \
    --format markdown
```

### 5. Trace insights

```bash
$EVOLVER_PY $TOOLS/trace_insights.py \
    --from-experiment "dry-run-v001a" \
    --output "$TMPDIR/trace_insights.json"
```

### 6. Cleanup

```bash
rm -rf "$TMPDIR"
echo "Dry run complete. Temp files cleaned up."
```

## Report

```
Dry Run Results ({MODE} mode):
  Tool syntax: {N}/{N} passed
  Argparse: {N}/{N} passed
  Cross-refs: {N}/{N} passed
  {If online: setup/eval/read/trace pipeline: PASS/FAIL}
```
