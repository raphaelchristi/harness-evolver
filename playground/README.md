# Playground — Test Agents for Harness Evolver

Real LLM agent projects for testing the harness-evolver plugin end-to-end. Each project is a deliberately mediocre agent with known weaknesses that the evolver should be able to improve.

All agents use **Gemini 2.0 Flash Lite** (cheapest available) via `langchain-google-genai`.

## Projects

| Project | Topology | Framework | Baseline | Weakness |
|---------|----------|-----------|----------|----------|
| **simple-qa/** | Single-call | LangChain | ~35% | Vague prompt, no format, high temperature |
| **react-agent/** | ReAct loop | LangGraph | ~40% | Bad tool descriptions, no routing guidance |
| **rag-agent/** | RAG | LangChain | ~40% | Keyword retrieval, no reranking, top-2 only |

## Setup

```bash
# Create venv and install dependencies (shared across all projects)
cd playground
uv venv .venv            # or: python3 -m venv .venv
uv pip install -r requirements.txt   # or: .venv/bin/pip install -r requirements.txt

# Set API keys
cp .env.example .env
# Edit .env with your GOOGLE_API_KEY and LANGSMITH_API_KEY

# Source the env
export $(grep -v '^#' .env | xargs)
```

## Usage with Harness Evolver

```bash
# Pick a project
cd playground/simple-qa   # or react-agent, rag-agent

# Run the evolver
/evolver:setup
# IMPORTANT: When asked for entry point, use the venv Python:
#   ../. venv/bin/python agent.py {input}
# NOT: python agent.py {input}
/evolver:evolve
```

## Quick test (verify agent runs)

```bash
cd playground/simple-qa
echo '{"input": "What is 2+2?"}' > /tmp/test.json
../.venv/bin/python agent.py /tmp/test.json
```

## Cost estimate per evolution iteration

- **simple-qa**: ~$0.01 (no LLM in agent, only proposer/evaluator cost)
- **react-agent**: ~$0.05 (Gemini Flash Lite calls per eval, 20 inputs)
- **rag-agent**: ~$0.03 (Gemini Flash Lite calls per eval, 20 inputs)

The main cost is the proposer and evaluator agents (Claude), not the target agents (Gemini).
