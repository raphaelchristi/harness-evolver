#!/usr/bin/env python3
"""Extract a consolidated contract document from agent source code.

Walks Python source files in a project and produces a single contracts.md
listing every tool, function, and class with its signature, docstring, and
decorator hints. The intent (from Autogenesis AGP, Layer 1) is to give the
proposer a stable, up-to-date description of the agent's capability surface
without re-reading every source file — reducing prompt bloat and eliminating
prompt/code drift.

Outputs:
    contracts.md   — human/LLM-readable capability document
    contracts.json — machine-readable index of the same data

Stdlib-only. No external dependencies.

Usage:
    # Scan current directory
    python3 extract_contracts.py --root . --output contracts.md

    # Scan a worktree before a proposer run
    python3 extract_contracts.py --root /tmp/wt --output /tmp/wt/contracts.md

    # Limit scan to entry-point files listed in .evolver.json
    python3 extract_contracts.py --config .evolver.json --output contracts.md
"""

import argparse
import ast
import json
import os
import re
import sys


# Decorators that typically mark a function as a callable tool/skill.
# Matched by the final attribute name, so `langchain_core.tools.tool`
# and a bare `tool` both match.
TOOL_DECORATORS = {
    "tool",
    "function_tool",
    "openai_function",
    "openai_tool",
    "anthropic_tool",
    "agent_tool",
    "register_tool",
    "skill",
}

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".worktrees",
    "evolution_archive",
    ".evolver",
    "dist",
    "build",
}


def _decorator_name(dec):
    """Best-effort name for a decorator AST node."""
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return None


def _format_arg(arg, default=None):
    """Render a function argument as source-like text."""
    text = arg.arg
    if arg.annotation is not None:
        try:
            text += ": " + ast.unparse(arg.annotation)
        except Exception:
            pass
    if default is not None:
        try:
            text += " = " + ast.unparse(default)
        except Exception:
            pass
    return text


def _format_signature(fn):
    """Render a function/async-function signature as `name(args) -> ret`."""
    args = fn.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    # Align defaults to the tail of positional args.
    pad = len(positional) - len(defaults)
    default_map = [None] * pad + defaults

    rendered = [_format_arg(a, d) for a, d in zip(positional, default_map)]
    if args.vararg is not None:
        rendered.append("*" + _format_arg(args.vararg))
    elif args.kwonlyargs:
        rendered.append("*")
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        rendered.append(_format_arg(a, d))
    if args.kwarg is not None:
        rendered.append("**" + _format_arg(args.kwarg))

    sig = f"{fn.name}({', '.join(rendered)})"
    if fn.returns is not None:
        try:
            sig += " -> " + ast.unparse(fn.returns)
        except Exception:
            pass
    return sig


def _first_docstring_line(doc):
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_usage_examples(doc, max_examples=2):
    """Pull fenced code blocks or Example: blocks from a docstring."""
    if not doc:
        return []
    examples = []
    # Fenced blocks
    for match in re.finditer(r"```(?:python)?\n(.*?)```", doc, re.DOTALL):
        snippet = match.group(1).strip()
        if snippet:
            examples.append(snippet)
        if len(examples) >= max_examples:
            return examples
    # 'Example:' prose blocks
    if "Example:" in doc or "Examples:" in doc:
        parts = re.split(r"Examples?:", doc, maxsplit=1)
        if len(parts) == 2:
            tail = parts[1].strip()
            snippet = "\n".join(line for line in tail.splitlines()[:6] if line.strip())
            if snippet and snippet not in examples:
                examples.append(snippet)
    return examples[:max_examples]


def extract_file_contracts(path, root):
    """Parse a single Python file; return a dict of its contracts."""
    try:
        with open(path, encoding="utf-8") as f:
            source = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return None

    rel_path = os.path.relpath(path, root)
    module_doc = ast.get_docstring(tree) or ""

    tools = []
    functions = []
    classes = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            dec_names = [_decorator_name(d) for d in node.decorator_list]
            dec_names = [d for d in dec_names if d]
            is_tool = any(d in TOOL_DECORATORS for d in dec_names)
            entry = {
                "name": node.name,
                "signature": _format_signature(node),
                "decorators": dec_names,
                "doc": ast.get_docstring(node) or "",
                "lineno": node.lineno,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "examples": _extract_usage_examples(ast.get_docstring(node) or ""),
            }
            if is_tool:
                tools.append(entry)
            elif not node.name.startswith("_"):
                functions.append(entry)
        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name not in ("__init__", "__call__"):
                        continue
                    methods.append({
                        "name": item.name,
                        "signature": _format_signature(item),
                        "doc": _first_docstring_line(ast.get_docstring(item) or ""),
                    })
            classes.append({
                "name": node.name,
                "doc": ast.get_docstring(node) or "",
                "lineno": node.lineno,
                "methods": methods,
            })

    return {
        "path": rel_path,
        "module_doc": module_doc,
        "tools": tools,
        "functions": functions,
        "classes": classes,
    }


def walk_project(root):
    """Yield absolute paths of Python files under root, skipping junk dirs."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES and not d.startswith(".")]
        for name in filenames:
            if name.endswith(".py") and not name.startswith("."):
                yield os.path.join(dirpath, name)


def resolve_roots(args):
    """Resolve which files/directories to scan."""
    if args.root:
        return [os.path.abspath(args.root)]
    if args.files:
        return [os.path.abspath(p) for p in args.files]
    if args.config:
        try:
            with open(args.config) as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            return [os.getcwd()]
        entry = cfg.get("entry_point", "")
        out = []
        for token in entry.split():
            if token.endswith(".py") and not token.startswith("-"):
                out.append(os.path.abspath(token))
        if out:
            return out
    return [os.getcwd()]


def format_markdown(contracts):
    """Render the contracts list as markdown."""
    lines = [
        "# Agent Contracts",
        "",
        "*Auto-generated capability surface. Do not edit by hand — run `extract_contracts.py`.*",
        "",
        f"*Files scanned: {len(contracts)}*",
        "",
    ]

    all_tools = []
    for c in contracts:
        for t in c["tools"]:
            all_tools.append((c["path"], t))
    if all_tools:
        lines.append("## Tools")
        lines.append("")
        for path, t in all_tools:
            decs = ", ".join("@" + d for d in t["decorators"]) if t["decorators"] else ""
            lines.append(f"### `{t['name']}`  — `{path}:{t['lineno']}` {decs}".rstrip())
            lines.append("")
            lines.append(f"```python\n{t['signature']}\n```")
            if t["doc"]:
                lines.append("")
                lines.append(t["doc"].strip())
            if t["examples"]:
                lines.append("")
                lines.append("**Example:**")
                lines.append("")
                lines.append(f"```python\n{t['examples'][0]}\n```")
            lines.append("")

    any_fn = any(c["functions"] for c in contracts)
    if any_fn:
        lines.append("## Public Functions")
        lines.append("")
        for c in contracts:
            if not c["functions"]:
                continue
            lines.append(f"### `{c['path']}`")
            lines.append("")
            for fn in c["functions"]:
                doc = _first_docstring_line(fn["doc"])
                lines.append(f"- `{fn['signature']}` — {doc}" if doc else f"- `{fn['signature']}`")
            lines.append("")

    any_cls = any(c["classes"] for c in contracts)
    if any_cls:
        lines.append("## Classes")
        lines.append("")
        for c in contracts:
            if not c["classes"]:
                continue
            lines.append(f"### `{c['path']}`")
            lines.append("")
            for cls in c["classes"]:
                doc = _first_docstring_line(cls["doc"])
                header = f"**`{cls['name']}`**" + (f" — {doc}" if doc else "")
                lines.append(header)
                for m in cls["methods"]:
                    mdoc = f" — {m['doc']}" if m["doc"] else ""
                    lines.append(f"  - `{m['signature']}`{mdoc}")
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Extract capability contracts from agent source.")
    parser.add_argument("--root", help="Project root to scan (default: derive from --config or CWD)")
    parser.add_argument("--files", nargs="*", help="Explicit file list to scan")
    parser.add_argument("--config", default=None, help="Use entry_point from .evolver.json to pick files")
    parser.add_argument("--output", default="contracts.md", help="Markdown output path")
    parser.add_argument("--json", default=None, help="Optional JSON index output")
    args = parser.parse_args()

    roots = resolve_roots(args)
    files = []
    scan_root = roots[0] if len(roots) == 1 and os.path.isdir(roots[0]) else os.getcwd()
    for r in roots:
        if os.path.isdir(r):
            scan_root = r
            files.extend(walk_project(r))
        elif os.path.isfile(r):
            files.append(r)

    contracts = []
    for path in sorted(set(files)):
        entry = extract_file_contracts(path, scan_root)
        if not entry:
            continue
        if not (entry["tools"] or entry["functions"] or entry["classes"]):
            continue
        contracts.append(entry)

    md = format_markdown(contracts)
    with open(args.output, "w") as f:
        f.write(md)

    json_path = args.json or (args.output[:-3] + ".json" if args.output.endswith(".md") else args.output + ".json")
    with open(json_path, "w") as f:
        json.dump({"files": contracts}, f, indent=2)

    tool_count = sum(len(c["tools"]) for c in contracts)
    fn_count = sum(len(c["functions"]) for c in contracts)
    cls_count = sum(len(c["classes"]) for c in contracts)
    print(f"Contracts: {tool_count} tools, {fn_count} functions, {cls_count} classes across {len(contracts)} files")
    print(f"Wrote {args.output} and {json_path}")


if __name__ == "__main__":
    main()
