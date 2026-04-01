#!/usr/bin/env bash
# Harness Evolver — SessionStart hook
# Ensures Python venv, langsmith, langsmith-cli, and env vars are ready.
# Runs silently on every session start. Installs deps only if missing.

set -euo pipefail

# Resolve paths — plugin root is set by Claude Code
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
PLUGIN_DATA="${CLAUDE_PLUGIN_DATA:-}"

# Fallback: if running outside plugin system (npx install), use legacy paths
if [ -z "$PLUGIN_ROOT" ]; then
    PLUGIN_ROOT="$HOME/.evolver"
    PLUGIN_DATA="$HOME/.evolver"
fi

TOOLS_DIR="$PLUGIN_ROOT/tools"
VENV_DIR="$PLUGIN_DATA/venv"
VENV_PY="$VENV_DIR/bin/python"

# --- 1. Create venv if missing ---
if [ ! -f "$VENV_PY" ]; then
    if command -v uv >/dev/null 2>&1; then
        uv venv "$VENV_DIR" >/dev/null 2>&1
    else
        python3 -m venv "$VENV_DIR" >/dev/null 2>&1
    fi
fi

# --- 2. Install langsmith if missing ---
if [ -f "$VENV_PY" ]; then
    "$VENV_PY" -c "import langsmith" 2>/dev/null || {
        if command -v uv >/dev/null 2>&1; then
            uv pip install --python "$VENV_PY" langsmith >/dev/null 2>&1
        else
            "$VENV_DIR/bin/pip" install --upgrade langsmith >/dev/null 2>&1 || \
            "$VENV_PY" -m pip install --upgrade langsmith >/dev/null 2>&1
        fi
    }
fi

# --- 3. Install langsmith-cli if missing ---
command -v langsmith-cli >/dev/null 2>&1 || {
    if command -v uv >/dev/null 2>&1; then
        uv tool install langsmith-cli >/dev/null 2>&1
    else
        pip install langsmith-cli >/dev/null 2>&1 || pip3 install langsmith-cli >/dev/null 2>&1
    fi
} || true

# --- 4. Load API key from credentials file if not in env ---
if [ -z "${LANGSMITH_API_KEY:-}" ]; then
    if [ "$(uname)" = "Darwin" ]; then
        CREDS="$HOME/Library/Application Support/langsmith-cli/credentials"
    else
        CREDS="$HOME/.config/langsmith-cli/credentials"
    fi
    if [ -f "$CREDS" ]; then
        KEY=$(grep '^LANGSMITH_API_KEY=' "$CREDS" 2>/dev/null | head -1 | cut -d= -f2-)
        if [ -n "$KEY" ]; then
            echo "export LANGSMITH_API_KEY=\"$KEY\"" >> "$CLAUDE_ENV_FILE"
        fi
    fi
fi

# --- 5. Export env vars for skills ---
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo "export EVOLVER_TOOLS=\"$TOOLS_DIR\"" >> "$CLAUDE_ENV_FILE"
    echo "export EVOLVER_PY=\"$VENV_PY\"" >> "$CLAUDE_ENV_FILE"
fi
