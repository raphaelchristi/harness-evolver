# Classifier Example

Medical symptom classifier — deliberately naive, designed to be improved by the evolver.

## Quick Start (Mock Mode — No API Key)

```bash
/harness-evolve-init --harness harness.py --eval eval.py --tasks tasks/
/harness-evolve --iterations 5
```

## With LLM

Edit `config.json`:
```json
{
  "mock": false,
  "api_key": "sk-ant-...",
  "model": "claude-haiku-4-5-20251001"
}
```

## Categories

respiratory, cardiac, gastrointestinal, neurological, musculoskeletal, dermatological
