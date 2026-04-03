# This module is imported by sibling tools via: from _common import ...
"""Shared utilities for Harness Evolver tools.

Contains functions that were previously duplicated across multiple tool files:
- ensure_langsmith_api_key() — API key resolution (env > project .env > global credentials)
- write_config_atomic() — safe JSON config writes via temp file + rename
- load_config() — JSON config loading with error handling
"""

import json
import os
import platform
import sys


# Tracks where the API key was loaded from.
# Read this AFTER calling ensure_langsmith_api_key() — e.g.:
#   import _common
#   _common.ensure_langsmith_api_key()
#   source = _common.key_source
key_source = None


def ensure_langsmith_api_key():
    """Load LANGSMITH_API_KEY from env, project .env, or global credentials.

    Priority: env var > project .env (CWD or --config dir) > global credentials.
    Project .env takes precedence over global credentials because the project-local
    key is more likely to be correct and up-to-date.

    Validates key format before accepting (must be 30+ chars, start with lsv2_).
    Rejects obviously dummy/test keys.

    Sets the module-level `key_source` variable to indicate where the key was found.
    Returns True if a key was found and set, False otherwise.
    """
    global key_source

    def _is_valid_key(k):
        """Reject dummy/test keys and obviously invalid ones."""
        if not k or len(k) < 30:
            return False
        if k.startswith("lsv2_pt_test") or k == "your-api-key-here":
            return False
        return True

    if os.environ.get("LANGSMITH_API_KEY"):
        if _is_valid_key(os.environ["LANGSMITH_API_KEY"]):
            key_source = "environment"
            return True
        else:
            print(f"  WARNING: LANGSMITH_API_KEY in environment looks invalid (too short or test key), skipping", file=sys.stderr)
    # Check .env in CWD and in --config directory FIRST (project-local > global)
    env_candidates = [".env"]
    for i, arg in enumerate(sys.argv):
        if arg == "--config" and i + 1 < len(sys.argv):
            cfg_dir = os.path.dirname(os.path.abspath(sys.argv[i + 1]))
            env_candidates.append(os.path.join(cfg_dir, ".env"))
        elif arg.startswith("--config="):
            cfg_dir = os.path.dirname(os.path.abspath(arg.split("=", 1)[1]))
            env_candidates.append(os.path.join(cfg_dir, ".env"))
    for env_path in env_candidates:
        if os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("LANGSMITH_API_KEY=") and not line.startswith("#"):
                            key = line.split("=", 1)[1].strip().strip("'\"")
                            if key and _is_valid_key(key):
                                os.environ["LANGSMITH_API_KEY"] = key
                                key_source = f".env file ({env_path})"
                                return True
                            elif key:
                                print(f"  WARNING: LANGSMITH_API_KEY in {env_path} looks invalid, skipping", file=sys.stderr)
            except OSError:
                pass
    # Fallback: global langsmith-cli credentials file
    if platform.system() == "Darwin":
        creds_path = os.path.expanduser("~/Library/Application Support/langsmith-cli/credentials")
    else:
        creds_path = os.path.expanduser("~/.config/langsmith-cli/credentials")
    if os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LANGSMITH_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        if key and _is_valid_key(key):
                            os.environ["LANGSMITH_API_KEY"] = key
                            key_source = "credentials file"
                            return True
                        elif key:
                            print(f"  WARNING: LANGSMITH_API_KEY in {creds_path} looks invalid (dummy/test key?), skipping", file=sys.stderr)
        except OSError:
            pass
    return False


def write_config_atomic(path, config):
    """Write config JSON atomically (temp file + rename)."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_config(path):
    """Load JSON config file with error handling.

    Returns the parsed dict. Raises SystemExit with a message on failure.
    """
    if not os.path.exists(path):
        print(f"Config not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Failed to load config {path}: {e}", file=sys.stderr)
        sys.exit(1)
