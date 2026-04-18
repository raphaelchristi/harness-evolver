#!/usr/bin/env python3
"""RSPL-lite resource registry for the agent project.

Maps the Autogenesis Resource Substrate Protocol Layer (Layer 1) onto the
user's project: scans the tree, classifies files into one of the five RSPL
entity types (prompt, agent, tool, environment, memory), attaches a content
hash + version, and marks which resources are evolvable. The output gives
proposers a typed view of the evolvable surface so they can target
"mutate only tools" or "mutate only prompts" instead of blindly editing
arbitrary files.

Versioning is incremental: on each scan, files whose hash changed relative
to the previous registry receive version += 1; new files start at 1;
deleted files are retained with a `removed_at` timestamp for audit.

Output (by default, `.evolver/resources.json`):
    {
      "generated_at": "...",
      "root": "...",
      "counts": {"prompt": 3, "tool": 5, ...},
      "resources": [
        {"id": "tool/search.py", "type": "tool", "path": "tools/search.py",
         "hash": "sha256:...", "version": 2, "evolvable": true, "size": 1234,
         "reasons": ["@tool decorator"]},
         ...
      ]
    }

Stdlib-only. No external dependencies.

Usage:
    # Initial scan of the current project
    python3 resource_registry.py --root . --output .evolver/resources.json

    # Rescan (versions auto-bump on hash change)
    python3 resource_registry.py --root . --output .evolver/resources.json

    # Filter listing
    python3 resource_registry.py --root . --list --type tool

    # Mark a specific file non-evolvable
    python3 resource_registry.py --root . --freeze tools/credentials.py
"""

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone


EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".worktrees",
    ".claude",
    "evolution_archive",
    "dist",
    "build",
    "__pypackages__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".ipynb_checkpoints",
}

EXCLUDE_DIR_PREFIXES = (".",)  # hidden dirs except those listed explicitly below
EXCLUDE_DIR_EXCEPTIONS = {".evolver"}  # still excluded but we will allow memory files inside


PROMPT_PATH_HINTS = re.compile(r"(^|/)(prompts?|system_prompts?|templates?)(/|$)", re.IGNORECASE)
PROMPT_FILENAME_HINTS = re.compile(r"(prompt|template|instruction)s?\.(md|txt|prompt|jinja2?)$", re.IGNORECASE)

AGENT_PATH_HINTS = re.compile(r"(^|/)(agents?|graph|orchestrat(or|ion)|planner)(/|$)", re.IGNORECASE)
AGENT_FILENAME_HINTS = re.compile(r"(agent|graph|planner|orchestrator|react|chain)\.py$", re.IGNORECASE)

TOOL_PATH_HINTS = re.compile(r"(^|/)(tools?|skills?|functions?)(/|$)", re.IGNORECASE)

MEMORY_PATH_HINTS = re.compile(r"(^|/)(memory|knowledge|context_store|persistent|state_store)(/|$)", re.IGNORECASE)
MEMORY_FILENAME_HINTS = re.compile(r"(memory|knowledge|history|state_store)\..+$", re.IGNORECASE)

ENV_EXTS = {".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".conf"}
ENV_FILENAMES = {".env", ".env.example", "config.yaml", "config.yml", "settings.yaml", "settings.yml"}

# Files that should never be auto-mutated even if found.
FROZEN_FILENAME_HINTS = re.compile(
    r"(credentials?|secret|apikey|api_key|token|\.env$|\.env\.)",
    re.IGNORECASE,
)

TOOL_DECORATORS = {
    "tool", "function_tool", "openai_function", "openai_tool", "anthropic_tool",
    "agent_tool", "register_tool", "skill",
}

AGENT_CLASS_HINTS = {
    "StateGraph", "ChatCompletionAgent", "ReActAgent", "Agent", "Runnable",
    "ChatAgent", "AgentExecutor", "LLMAgent",
}


def file_sha256(path):
    """Return sha256 hex of file content, or None on read error."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _py_has_tool_decorator(path):
    """True if the Python file defines any @tool-decorated function."""
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                name = None
                if isinstance(d, ast.Name):
                    name = d.id
                elif isinstance(d, ast.Attribute):
                    name = d.attr
                elif isinstance(d, ast.Call):
                    inner = d.func
                    name = inner.id if isinstance(inner, ast.Name) else getattr(inner, "attr", None)
                if name in TOOL_DECORATORS:
                    return True
    return False


def _py_looks_like_agent(path):
    """True if the Python file references known agent framework classes/functions."""
    try:
        with open(path, encoding="utf-8") as f:
            source = f.read()
    except (OSError, UnicodeDecodeError):
        return False
    for hint in AGENT_CLASS_HINTS:
        if re.search(rf"\b{re.escape(hint)}\b", source):
            return True
    if re.search(r"\b(create_react_agent|StateGraph\().*", source):
        return True
    return False


def _md_looks_like_prompt(path, rel_path):
    """True if a markdown/text file looks like a prompt template."""
    if PROMPT_PATH_HINTS.search(rel_path) or PROMPT_FILENAME_HINTS.search(rel_path):
        return True
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(2048)
    except (OSError, UnicodeDecodeError):
        return False
    # Rough heuristic: prompt-like files usually use second person / template vars.
    markers = ["You are ", "You must", "System:", "{input}", "{question}", "{context}"]
    return any(m in head for m in markers)


def classify(path, rel_path):
    """Return (type, evolvable, reasons) for a file — or (None, _, _) to skip."""
    reasons = []
    basename = os.path.basename(path)
    ext = os.path.splitext(basename)[1].lower()

    # Frozen detection up front so it overrides type choice below.
    frozen = bool(FROZEN_FILENAME_HINTS.search(rel_path))

    # Memory
    if MEMORY_PATH_HINTS.search(rel_path) or MEMORY_FILENAME_HINTS.match(basename):
        reasons.append("memory path/filename")
        return "memory", not frozen, reasons

    # Environment / config
    if basename in ENV_FILENAMES or ext in ENV_EXTS:
        reasons.append(f"config file ({ext or basename})")
        # .env-style secrets are not evolvable
        return "environment", not frozen, reasons

    # Prompt (markdown/text)
    if ext in {".md", ".txt", ".prompt", ".jinja", ".jinja2"} and _md_looks_like_prompt(path, rel_path):
        reasons.append("prompt template")
        return "prompt", not frozen, reasons

    # Python — decide between tool and agent
    if ext == ".py":
        if _py_has_tool_decorator(path):
            reasons.append("@tool decorator")
            return "tool", not frozen, reasons
        if TOOL_PATH_HINTS.search(rel_path):
            reasons.append("tools/ path")
            return "tool", not frozen, reasons
        if _py_looks_like_agent(path) or AGENT_PATH_HINTS.search(rel_path) or AGENT_FILENAME_HINTS.search(basename):
            reasons.append("agent framework class/function")
            return "agent", not frozen, reasons
        # Generic Python — only register if we can see it's meaningful
        return None, False, reasons

    return None, False, reasons


def walk_project(root):
    for dirpath, dirnames, filenames in os.walk(root):
        pruned = []
        for d in dirnames:
            if d in EXCLUDE_DIR_NAMES:
                continue
            if d.startswith(EXCLUDE_DIR_PREFIXES) and d not in EXCLUDE_DIR_EXCEPTIONS:
                continue
            pruned.append(d)
        dirnames[:] = pruned
        for name in filenames:
            if name.startswith(".") and name not in ENV_FILENAMES:
                continue
            yield os.path.join(dirpath, name)


def resource_id(rtype, rel_path):
    """Stable id based on type and normalized relative path."""
    normalized = rel_path.replace(os.sep, "/")
    return f"{rtype}/{normalized}"


def load_existing(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def build_registry(root, previous=None, freeze_paths=None):
    freeze_set = {os.path.normpath(p) for p in (freeze_paths or [])}
    prev_map = {}
    if previous:
        for r in previous.get("resources", []):
            prev_map[r["id"]] = r

    seen_ids = set()
    resources = []
    for abspath in walk_project(root):
        rel = os.path.relpath(abspath, root)
        rtype, evolvable, reasons = classify(abspath, rel)
        if not rtype:
            continue
        rid = resource_id(rtype, rel)
        seen_ids.add(rid)
        h = file_sha256(abspath)
        if h is None:
            continue
        size = os.path.getsize(abspath)
        prev = prev_map.get(rid)
        if prev and prev.get("hash") == "sha256:" + h:
            version = prev.get("version", 1)
        elif prev:
            version = prev.get("version", 1) + 1
        else:
            version = 1
        if os.path.normpath(rel) in freeze_set:
            evolvable = False
            reasons.append("frozen by --freeze")
        resources.append({
            "id": rid,
            "type": rtype,
            "path": rel.replace(os.sep, "/"),
            "hash": "sha256:" + h,
            "version": version,
            "evolvable": evolvable,
            "size": size,
            "reasons": reasons,
            "last_modified": datetime.fromtimestamp(os.path.getmtime(abspath), tz=timezone.utc).isoformat(),
        })

    # Carry forward tombstones for deleted resources.
    removed = []
    for rid, prev in prev_map.items():
        if rid not in seen_ids and not prev.get("removed_at"):
            tomb = dict(prev)
            tomb["removed_at"] = datetime.now(timezone.utc).isoformat()
            removed.append(tomb)

    counts = {}
    for r in resources:
        counts[r["type"]] = counts.get(r["type"], 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": os.path.abspath(root),
        "counts": counts,
        "resources": resources,
        "removed": removed,
    }


def format_summary(registry):
    counts = registry.get("counts", {})
    lines = [
        f"Registry: {len(registry['resources'])} active resources  "
        + ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())),
    ]
    if registry.get("removed"):
        lines.append(f"Tombstones: {len(registry['removed'])}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Build an RSPL-lite resource registry for the project.")
    parser.add_argument("--root", default=".", help="Project root (default: CWD)")
    parser.add_argument("--output", default=None,
                        help="Registry output path (default: {root}/.evolver/resources.json)")
    parser.add_argument("--list", action="store_true", help="Print the registry to stdout instead of writing it")
    parser.add_argument("--type", choices=["prompt", "tool", "agent", "environment", "memory"],
                        help="Filter listing by type")
    parser.add_argument("--evolvable-only", action="store_true", help="Filter to evolvable resources")
    parser.add_argument("--freeze", action="append", default=[],
                        help="Mark a path as non-evolvable (repeatable)")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"Not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or os.path.join(root, ".evolver", "resources.json")
    args.output = output_path
    previous = load_existing(output_path)
    registry = build_registry(root, previous=previous, freeze_paths=args.freeze)

    if args.list:
        rows = registry["resources"]
        if args.type:
            rows = [r for r in rows if r["type"] == args.type]
        if args.evolvable_only:
            rows = [r for r in rows if r["evolvable"]]
        for r in rows:
            tag = "E" if r["evolvable"] else "F"
            print(f"[{tag}] {r['type']:12} v{r['version']:<3} {r['path']}")
        return

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    tmp = args.output + ".tmp"
    with open(tmp, "w") as f:
        json.dump(registry, f, indent=2)
    os.replace(tmp, args.output)
    print(format_summary(registry))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
