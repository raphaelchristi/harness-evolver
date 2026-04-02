# ReAct Agent with Tools

LangGraph ReAct agent with 3 tools (calculator, lookup, date). Uses Gemini 2.0 Flash Lite. Deliberately poor tool descriptions and routing.

## Why it's bad

- Tool descriptions are too vague ("Do math.", "Look up information.") — model doesn't know when to use which
- System prompt gives no guidance on tool selection
- Lookup knowledge base is tiny (10 entries) — most lookups return "No information found"
- No error handling when tools fail
- No chain-of-thought before tool use
- Temperature 0.5 — not ideal for deterministic tool selection

## Expected scores

- **Baseline**: ~40% (misses tool calls, wrong tool choice, poor formatting)
- **Target after evolution**: ~70-75% (better tool descriptions, routing prompt, error handling)

## Evolution vectors

1. Tool descriptions (more specific, with examples)
2. System prompt (when to use each tool, format instructions)
3. Error handling (retry on tool failure, fallback)
4. Add more entries to lookup knowledge base
5. Lower temperature for more deterministic behavior

## Architecture

```
START → agent → [tool_calls?] → tools → agent → ... → END
```

LangGraph `StateGraph` with `ToolNode`. Topology: **ReAct loop**.

## Setup

```bash
export GOOGLE_API_KEY="your-key"
export LANGSMITH_API_KEY="your-key"
export LANGSMITH_TRACING=true

cd playground/react-agent
pip install -r ../requirements.txt
python agent.py test_inputs.json
```
