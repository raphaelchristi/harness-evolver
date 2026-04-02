# Simple Q&A Agent

Single-call Q&A agent with a deliberately vague system prompt. Uses Gemini 2.0 Flash Lite via LangChain.

## Why it's bad

- System prompt is just "You are a helpful assistant" — no format instructions, no domain context, no examples
- Temperature 0.7 — too high for factual questions
- No output constraints — answers are unpredictably verbose or terse
- No chain-of-thought for math/logic questions

## Expected scores

- **Baseline**: ~35-40% (vague answers, wrong format, verbose)
- **Target after evolution**: ~70-80% (better prompt, lower temp, format instructions)

## Evolution vectors

The evolver should improve:
1. System prompt (add format instructions, examples, domain context)
2. Temperature (lower for factual, keep for creative)
3. Output parsing (structured responses)

## Setup

```bash
export GOOGLE_API_KEY="your-key"
export LANGSMITH_API_KEY="your-key"
export LANGSMITH_TRACING=true

cd playground/simple-qa
pip install -r ../requirements.txt
python agent.py test_inputs.json  # quick test
```

## Run with evolver

```bash
cd playground/simple-qa
/evolver:setup
/evolver:evolve
```
