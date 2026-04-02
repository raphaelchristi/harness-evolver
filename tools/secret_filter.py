#!/usr/bin/env python3
"""Secret detection and filtering for eval datasets.

Detects API keys, tokens, passwords, and other sensitive data in text.
Used by seed_from_traces.py and dataset_health.py.

Usage:
    echo "text with sk-ant-api..." | python3 secret_filter.py
    python3 secret_filter.py < file.txt

Stdlib-only — no external dependencies.
"""

import re
import json
import sys


SECRET_PATTERNS = re.compile(
    r'('
    r'sk-ant-api\S{20,}'
    r'|sk-or-v1-\S{20,}'
    r'|sk-\S{20,}'
    r'|ghp_\S{20,}'
    r'|gho_\S{20,}'
    r'|github_pat_\S{20,}'
    r'|xoxb-\S{20,}'
    r'|xapp-\S{20,}'
    r'|ntn_\S{20,}'
    r'|AKIA[A-Z0-9]{16}'
    r'|Bearer\s+[A-Za-z0-9\-._~+/]{20,}'
    r'|-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----'
    r')',
    re.IGNORECASE,
)

ENV_PATTERNS = re.compile(
    r'(?:ANTHROPIC_API_KEY|OPENAI_API_KEY|LANGSMITH_API_KEY|LANGCHAIN_API_KEY'
    r'|AWS_SECRET_ACCESS_KEY|DATABASE_URL|POSTGRES_PASSWORD'
    r'|SLACK_TOKEN|GITHUB_TOKEN|API_KEY|SECRET_KEY'
    r')\s*[=:]\s*["\']?\S{10,}',
    re.IGNORECASE,
)

ASSIGN_PATTERNS = re.compile(
    r'(?:password|secret|token|api_key|apikey)\s*[=:]\s*["\']?\S{10,}',
    re.IGNORECASE,
)


def detect_secrets(text):
    """Return list of secret matches found in text."""
    if not text:
        return []
    findings = []
    for pattern, name in [
        (SECRET_PATTERNS, "secret_key"),
        (ENV_PATTERNS, "env_variable"),
        (ASSIGN_PATTERNS, "assignment"),
    ]:
        for m in pattern.finditer(text):
            match_text = m.group()
            redacted = match_text[:10] + "..." + match_text[-4:] if len(match_text) > 20 else match_text
            findings.append({
                "pattern": name,
                "match": redacted,
                "position": m.start(),
            })
    return findings


def has_secrets(text):
    """Quick boolean check — does text contain any secrets?"""
    if not text:
        return False
    return bool(SECRET_PATTERNS.search(text) or ENV_PATTERNS.search(text) or ASSIGN_PATTERNS.search(text))


def redact_secrets(text):
    """Replace detected secrets with [REDACTED]."""
    if not text:
        return text
    text = SECRET_PATTERNS.sub("[REDACTED]", text)
    text = ENV_PATTERNS.sub("[REDACTED]", text)
    text = ASSIGN_PATTERNS.sub("[REDACTED]", text)
    return text


if __name__ == "__main__":
    text = sys.stdin.read()
    findings = detect_secrets(text)
    if findings:
        print(json.dumps({"has_secrets": True, "count": len(findings), "findings": findings}, indent=2))
        sys.exit(1)
    else:
        print(json.dumps({"has_secrets": False, "count": 0}))
        sys.exit(0)
