#!/usr/bin/env python3
"""Shared LLM API calling utility. Stdlib-only (urllib).

Auto-detects the best available provider from environment variables.
Supports: Gemini, OpenAI, Anthropic, OpenRouter.
"""

import json
import os
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PROVIDER_PRIORITY = [
    ("GEMINI_API_KEY", "gemini", "gemini-2.5-flash"),
    ("GOOGLE_API_KEY", "gemini", "gemini-2.5-flash"),
    ("OPENROUTER_API_KEY", "openrouter", "google/gemini-2.5-flash"),
    ("OPENAI_API_KEY", "openai", "gpt-4o-mini"),
    ("ANTHROPIC_API_KEY", "anthropic", "claude-haiku-4-5-20251001"),
]


def detect_provider():
    """Auto-detect best available LLM provider from env vars.
    Returns (provider_name, api_key, model) or raises RuntimeError."""
    for env_var, provider, model in PROVIDER_PRIORITY:
        key = os.environ.get(env_var, "")
        if key:
            return provider, key, model
    raise RuntimeError(
        "No LLM API key found. Set one of: " +
        ", ".join(e for e, _, _ in PROVIDER_PRIORITY)
    )


def call_llm(provider, api_key, model, prompt, max_tokens=4096, temperature=0.0):
    """Call LLM API via urllib. Returns response text. Retries 3x with backoff."""
    for attempt in range(3):
        try:
            if provider == "gemini":
                return _call_gemini(api_key, model, prompt, max_tokens, temperature)
            elif provider == "openai":
                return _call_openai(api_key, model, prompt, max_tokens, temperature)
            elif provider == "anthropic":
                return _call_anthropic(api_key, model, prompt, max_tokens, temperature)
            elif provider == "openrouter":
                return _call_openrouter(api_key, model, prompt, max_tokens, temperature)
            else:
                raise ValueError(f"Unknown provider: {provider}")
        except ValueError:
            raise
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("All retries failed")


def _call_gemini(api_key, model, prompt, max_tokens, temperature):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": max(temperature, 0.0),
        },
    }).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_openai(api_key, model, prompt, max_tokens, temperature):
    url = "https://api.openai.com/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def _call_anthropic(api_key, model, prompt, max_tokens, temperature):
    url = "https://api.anthropic.com/v1/messages"
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = Request(url, data=body, headers={
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    })
    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["content"][0]["text"]


def _call_openrouter(api_key, model, prompt, max_tokens, temperature):
    url = "https://openrouter.ai/api/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]
