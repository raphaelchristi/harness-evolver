#!/usr/bin/env python3
"""Medical symptom classifier — deliberately naive, with room for improvement.

Mock mode (default): keyword matching, ~40% accuracy.
LLM mode: calls API, ~50-60% accuracy (no few-shot, no retry, no structured output).
"""

import argparse
import json
import os
import sys

CATEGORIES = [
    "respiratory", "cardiac", "gastrointestinal",
    "neurological", "musculoskeletal", "dermatological",
]

KEYWORDS = {
    "respiratory": ["cough", "breath", "lung", "wheeze", "sputum"],
    "cardiac": ["chest pain", "heart", "blood pressure", "palpitation"],
    "gastrointestinal": ["nausea", "vomit", "abdominal", "diarrhea", "stomach"],
    "neurological": ["headache", "dizz", "numb", "seizure", "confusion"],
    "musculoskeletal": ["joint", "back pain", "muscle", "stiffness", "swelling"],
    "dermatological": ["rash", "itch", "skin", "lesion", "bump"],
}


def classify_mock(text):
    text_lower = text.lower()
    scores = {}
    for category, words in KEYWORDS.items():
        scores[category] = sum(1 for w in words if w in text_lower)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "unknown"
    return best


def classify_llm(text, config):
    import urllib.request

    api_key = config.get("api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
    model = config.get("model", "claude-haiku-4-5-20251001")

    prompt = (
        f"Classify the following medical symptom description into exactly one category.\n"
        f"Categories: {', '.join(CATEGORIES)}\n"
        f"Reply with ONLY the category name, nothing else.\n\n"
        f"{text}"
    )

    body = json.dumps({
        "model": model,
        "max_tokens": 50,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    answer = result["content"][0]["text"].strip().lower()
    for cat in CATEGORIES:
        if cat in answer:
            return cat
    return answer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--traces-dir", default=None)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    task = json.load(open(args.input))
    config = json.load(open(args.config)) if args.config and os.path.exists(args.config) else {}
    use_mock = config.get("mock", True)

    if use_mock:
        result = classify_mock(task["input"])
    else:
        result = classify_llm(task["input"], config)

    output = {"id": task["id"], "output": result}

    if args.traces_dir:
        os.makedirs(args.traces_dir, exist_ok=True)
        trace = {
            "mode": "mock" if use_mock else "llm",
            "input_text": task["input"],
            "output_category": result,
            "config": {k: v for k, v in config.items() if k != "api_key"},
        }
        with open(os.path.join(args.traces_dir, "trace.json"), "w") as f:
            json.dump([trace], f, indent=2)

    json.dump(output, open(args.output, "w"), indent=2)


if __name__ == "__main__":
    main()
