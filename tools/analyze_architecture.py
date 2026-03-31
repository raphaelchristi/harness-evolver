#!/usr/bin/env python3
"""Analyze harness architecture to detect current topology and produce signals.

Usage:
    analyze_architecture.py --harness PATH [--traces-dir PATH] [--summary PATH] [-o output.json]

Performs AST-based analysis of harness code, optional trace analysis, and optional
score analysis to classify the current agent topology and produce structured signals
for the architect agent.

Stdlib-only. No external dependencies.
"""

import argparse
import ast
import json
import os
import re
import sys


# --- AST Analysis ---

LLM_API_DOMAINS = [
    "api.anthropic.com",
    "api.openai.com",
    "generativelanguage.googleapis.com",
]

LLM_SDK_MODULES = {"openai", "anthropic", "langchain_openai", "langchain_anthropic",
                    "langchain_core", "langchain_community", "langchain"}

RETRIEVAL_MODULES = {"chromadb", "pinecone", "qdrant_client", "weaviate"}

RETRIEVAL_METHOD_NAMES = {"similarity_search", "query"}

GRAPH_FRAMEWORK_CLASSES = {"StateGraph"}
GRAPH_FRAMEWORK_METHODS = {"add_node", "add_edge"}

PARALLEL_PATTERNS = {"gather"}  # asyncio.gather
PARALLEL_CLASSES = {"ThreadPoolExecutor", "ProcessPoolExecutor"}

TOOL_DICT_KEYS = {"name", "description", "parameters"}


def _get_all_imports(tree):
    """Extract all imported module root names."""
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


def _get_all_import_modules(tree):
    """Extract all imported module full names (including submodules)."""
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return modules


def _count_string_matches(tree, patterns):
    """Count AST string constants that contain any of the given patterns."""
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for pattern in patterns:
                if pattern in node.value:
                    count += 1
                    break
    return count


def _count_llm_calls(tree, imports, source_text):
    """Count LLM API calls: urllib requests to known domains + SDK client calls."""
    count = 0

    # Count urllib.request calls with LLM API domains in string constants
    count += _count_string_matches(tree, LLM_API_DOMAINS)

    # Count SDK imports that imply LLM calls (each import of an LLM SDK = at least 1 call site)
    full_modules = _get_all_import_modules(tree)
    sdk_found = set()
    for mod in full_modules:
        root = mod.split(".")[0]
        if root in LLM_SDK_MODULES:
            sdk_found.add(root)

    # For SDK users, look for actual call patterns like .create, .chat, .invoke, .run
    llm_call_methods = {"create", "chat", "invoke", "run", "generate", "predict",
                        "complete", "completions"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in llm_call_methods and sdk_found:
                    count += 1

    # If we found SDK imports but no explicit call methods, count 1 per SDK
    if sdk_found and count == 0:
        count = len(sdk_found)

    return max(count, _count_string_matches(tree, LLM_API_DOMAINS))


def _has_loop_around_llm(tree, source_text):
    """Check if any LLM call is inside a loop (for/while)."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)):
            # Walk the loop body looking for LLM call signals
            for child in ast.walk(node):
                # Check for urllib.request.urlopen in a loop
                if isinstance(child, ast.Attribute) and child.attr == "urlopen":
                    return True
                # Check for SDK call methods in a loop
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    if child.func.attr in {"create", "chat", "invoke", "run",
                                            "generate", "predict", "complete"}:
                        return True
                # Check for LLM API domain strings in a loop
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    for domain in LLM_API_DOMAINS:
                        if domain in child.value:
                            return True
    return False


def _has_tool_definitions(tree):
    """Check for tool definitions: dicts with name/description/parameters keys, or @tool decorators."""
    # Check for @tool decorator
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "tool":
                    return True
                if isinstance(decorator, ast.Attribute) and decorator.attr == "tool":
                    return True

    # Check for dicts with tool-like keys
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = set()
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
            if TOOL_DICT_KEYS.issubset(keys):
                return True

    return False


def _has_retrieval(tree, imports):
    """Check for retrieval patterns: vector DB imports or .similarity_search/.query calls."""
    if imports & RETRIEVAL_MODULES:
        return True

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in RETRIEVAL_METHOD_NAMES:
                return True

    return False


def _has_graph_framework(tree, full_modules):
    """Check for graph framework usage (LangGraph StateGraph, add_node, add_edge)."""
    # Check if langgraph is imported
    for mod in full_modules:
        if "langgraph" in mod:
            return True

    # Check for StateGraph usage
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in GRAPH_FRAMEWORK_CLASSES:
            return True
        if isinstance(node, ast.Attribute):
            if node.attr in GRAPH_FRAMEWORK_CLASSES or node.attr in GRAPH_FRAMEWORK_METHODS:
                return True

    return False


def _has_parallel_execution(tree, imports):
    """Check for asyncio.gather, concurrent.futures, ThreadPoolExecutor."""
    if "concurrent" in imports:
        return True

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr == "gather":
                return True
            if node.attr in PARALLEL_CLASSES:
                return True
        if isinstance(node, ast.Name) and node.id in PARALLEL_CLASSES:
            return True

    return False


def _has_error_handling_around_llm(tree):
    """Check if LLM calls are wrapped in try/except."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            # Walk the try body for LLM signals
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute) and child.attr == "urlopen":
                    return True
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    if child.func.attr in {"create", "chat", "invoke", "run",
                                            "generate", "predict", "complete"}:
                        return True
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    for domain in LLM_API_DOMAINS:
                        if domain in child.value:
                            return True
    return False


def _count_functions(tree):
    """Count function definitions (top-level and nested)."""
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count += 1
    return count


def _count_classes(tree):
    """Count class definitions."""
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            count += 1
    return count


def _estimate_topology(signals):
    """Classify the current topology based on code signals."""
    if signals["has_graph_framework"]:
        if signals["has_parallel_execution"]:
            return "parallel"
        return "hierarchical"

    if signals["has_retrieval"]:
        return "rag"

    if signals["has_loop_around_llm"]:
        if signals["has_tool_definitions"]:
            return "react-loop"
        return "react-loop"

    if signals["llm_call_count"] >= 3:
        if signals["has_tool_definitions"]:
            return "react-loop"
        return "chain"

    if signals["llm_call_count"] == 2:
        return "chain"

    if signals["llm_call_count"] <= 1:
        return "single-call"

    return "single-call"


def analyze_code(harness_path):
    """Analyze a harness Python file and return code signals."""
    with open(harness_path) as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {
            "llm_call_count": 0,
            "has_loop_around_llm": False,
            "has_tool_definitions": False,
            "has_retrieval": False,
            "has_graph_framework": False,
            "has_parallel_execution": False,
            "has_error_handling": False,
            "estimated_topology": "unknown",
            "code_lines": len(source.splitlines()),
            "function_count": 0,
            "class_count": 0,
        }

    imports = _get_all_imports(tree)
    full_modules = _get_all_import_modules(tree)

    llm_call_count = _count_llm_calls(tree, imports, source)
    has_loop = _has_loop_around_llm(tree, source)
    has_tools = _has_tool_definitions(tree)
    has_retrieval = _has_retrieval(tree, imports)
    has_graph = _has_graph_framework(tree, full_modules)
    has_parallel = _has_parallel_execution(tree, imports)
    has_error = _has_error_handling_around_llm(tree)

    signals = {
        "llm_call_count": llm_call_count,
        "has_loop_around_llm": has_loop,
        "has_tool_definitions": has_tools,
        "has_retrieval": has_retrieval,
        "has_graph_framework": has_graph,
        "has_parallel_execution": has_parallel,
        "has_error_handling": has_error,
        "code_lines": len(source.splitlines()),
        "function_count": _count_functions(tree),
        "class_count": _count_classes(tree),
    }
    signals["estimated_topology"] = _estimate_topology(signals)

    return signals


# --- Trace Analysis ---

def analyze_traces(traces_dir):
    """Analyze execution traces for error patterns, timing, and failures."""
    if not os.path.isdir(traces_dir):
        return None

    result = {
        "error_patterns": [],
        "timing": None,
        "task_failures": [],
        "stderr_lines": 0,
    }

    # Read stderr.log
    stderr_path = os.path.join(traces_dir, "stderr.log")
    if os.path.isfile(stderr_path):
        try:
            with open(stderr_path) as f:
                stderr = f.read()
            lines = stderr.strip().splitlines()
            result["stderr_lines"] = len(lines)

            # Detect common error patterns
            error_counts = {}
            for line in lines:
                for pattern in ["Traceback", "Error", "Exception", "Timeout",
                                "ConnectionRefused", "HTTPError", "JSONDecodeError",
                                "KeyError", "TypeError", "ValueError"]:
                    if pattern in line:
                        error_counts[pattern] = error_counts.get(pattern, 0) + 1

            result["error_patterns"] = [
                {"pattern": p, "count": c}
                for p, c in sorted(error_counts.items(), key=lambda x: -x[1])
            ]
        except Exception:
            pass

    # Read timing.json
    timing_path = os.path.join(traces_dir, "timing.json")
    if os.path.isfile(timing_path):
        try:
            with open(timing_path) as f:
                timing = json.load(f)
            result["timing"] = timing
        except (json.JSONDecodeError, Exception):
            pass

    # Scan per-task output directories for failures
    for entry in sorted(os.listdir(traces_dir)):
        task_dir = os.path.join(traces_dir, entry)
        if os.path.isdir(task_dir) and entry.startswith("task_"):
            output_path = os.path.join(task_dir, "output.json")
            if os.path.isfile(output_path):
                try:
                    with open(output_path) as f:
                        output = json.load(f)
                    # Check for empty or error outputs
                    out_value = output.get("output", "")
                    if not out_value or out_value in ("error", "unknown", ""):
                        result["task_failures"].append({
                            "task": entry,
                            "output": out_value,
                        })
                except (json.JSONDecodeError, Exception):
                    result["task_failures"].append({
                        "task": entry,
                        "output": "parse_error",
                    })

    return result


# --- Score Analysis ---

def analyze_scores(summary_path):
    """Analyze summary.json for stagnation, oscillation, and per-task failures."""
    if not os.path.isfile(summary_path):
        return None

    try:
        with open(summary_path) as f:
            summary = json.load(f)
    except (json.JSONDecodeError, Exception):
        return None

    result = {
        "iterations": summary.get("iterations", 0),
        "best_score": 0.0,
        "baseline_score": 0.0,
        "recent_scores": [],
        "is_stagnating": False,
        "is_oscillating": False,
        "score_trend": "unknown",
    }

    # Extract best score
    best = summary.get("best", {})
    result["best_score"] = best.get("combined_score", 0.0)
    result["baseline_score"] = summary.get("baseline_score", 0.0)

    # Extract recent version scores
    versions = summary.get("versions", [])
    if isinstance(versions, list):
        recent = versions[-5:] if len(versions) > 5 else versions
        result["recent_scores"] = [
            {"version": v.get("version", "?"), "score": v.get("combined_score", 0.0)}
            for v in recent
        ]
    elif isinstance(versions, dict):
        items = sorted(versions.items())
        recent = items[-5:] if len(items) > 5 else items
        result["recent_scores"] = [
            {"version": k, "score": v.get("combined_score", 0.0)}
            for k, v in recent
        ]

    # Detect stagnation (last 3+ scores within 1% of each other)
    scores = [s["score"] for s in result["recent_scores"]]
    if len(scores) >= 3:
        last_3 = scores[-3:]
        spread = max(last_3) - min(last_3)
        if spread <= 0.01:
            result["is_stagnating"] = True

    # Detect oscillation (alternating up/down for last 4+ scores)
    if len(scores) >= 4:
        deltas = [scores[i+1] - scores[i] for i in range(len(scores)-1)]
        sign_changes = sum(
            1 for i in range(len(deltas)-1)
            if (deltas[i] > 0 and deltas[i+1] < 0) or (deltas[i] < 0 and deltas[i+1] > 0)
        )
        if sign_changes >= len(deltas) - 1:
            result["is_oscillating"] = True

    # Score trend
    if len(scores) >= 2:
        if scores[-1] > scores[0]:
            result["score_trend"] = "improving"
        elif scores[-1] < scores[0]:
            result["score_trend"] = "declining"
        else:
            result["score_trend"] = "flat"

    return result


# --- Main ---

def analyze_multiple(file_paths):
    """Analyze multiple Python files and merge their signals.

    Useful in monorepo setups where the harness is a thin wrapper that
    delegates to the actual agent code. Pass the harness AND the main
    agent source files for a comprehensive topology classification.
    """
    merged = {
        "llm_call_count": 0,
        "has_loop_around_llm": False,
        "has_tool_definitions": False,
        "has_retrieval": False,
        "has_graph_framework": False,
        "has_parallel_execution": False,
        "has_error_handling": False,
        "code_lines": 0,
        "function_count": 0,
        "class_count": 0,
        "files_analyzed": [],
    }

    for path in file_paths:
        if not os.path.isfile(path):
            continue
        try:
            signals = analyze_code(path)
        except Exception:
            continue

        merged["llm_call_count"] += signals.get("llm_call_count", 0)
        merged["code_lines"] += signals.get("code_lines", 0)
        merged["function_count"] += signals.get("function_count", 0)
        merged["class_count"] += signals.get("class_count", 0)
        merged["files_analyzed"].append(os.path.basename(path))

        for bool_key in ["has_loop_around_llm", "has_tool_definitions", "has_retrieval",
                         "has_graph_framework", "has_parallel_execution", "has_error_handling"]:
            if signals.get(bool_key):
                merged[bool_key] = True

    merged["estimated_topology"] = _estimate_topology(merged)
    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Analyze harness architecture and produce signals for the architect agent",
        usage="analyze_architecture.py --harness PATH [--source-files PATH ...] "
              "[--traces-dir PATH] [--summary PATH] [-o output.json]",
    )
    parser.add_argument("--harness", required=True, help="Path to harness Python file")
    parser.add_argument("--source-files", nargs="*", default=None,
                        help="Additional source files to analyze (e.g. the actual agent code). "
                             "Useful when the harness is a thin wrapper around a larger system.")
    parser.add_argument("--traces-dir", default=None, help="Path to traces directory")
    parser.add_argument("--summary", default=None, help="Path to summary.json")
    parser.add_argument("-o", "--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    if not os.path.isfile(args.harness):
        print(json.dumps({"error": f"Harness file not found: {args.harness}"}))
        sys.exit(1)

    if args.source_files:
        all_files = [args.harness] + [f for f in args.source_files if os.path.isfile(f)]
        code_signals = analyze_multiple(all_files)
    else:
        code_signals = analyze_code(args.harness)

    result = {
        "code_signals": code_signals,
        "trace_signals": None,
        "score_signals": None,
    }

    if args.traces_dir:
        result["trace_signals"] = analyze_traces(args.traces_dir)

    if args.summary:
        result["score_signals"] = analyze_scores(args.summary)

    output = json.dumps(result, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output + "\n")
    else:
        print(output)


if __name__ == "__main__":
    main()
