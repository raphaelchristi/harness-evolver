#!/usr/bin/env python3
"""Detect the technology stack of a harness by analyzing Python imports via AST.

Usage:
    detect_stack.py <file_or_directory> [-o output.json]

Maps imports to known libraries and their Context7 IDs for documentation lookup.
Stdlib-only. No external dependencies.
"""

import ast
import json
import os
import sys

KNOWN_LIBRARIES = {
    "langchain": {
        "context7_id": "/langchain-ai/langchain",
        "display": "LangChain",
        "modules": ["langchain", "langchain_core", "langchain_openai",
                     "langchain_anthropic", "langchain_community"],
    },
    "langgraph": {
        "context7_id": "/langchain-ai/langgraph",
        "display": "LangGraph",
        "modules": ["langgraph"],
    },
    "llamaindex": {
        "context7_id": "/run-llama/llama_index",
        "display": "LlamaIndex",
        "modules": ["llama_index"],
    },
    "openai": {
        "context7_id": "/openai/openai-python",
        "display": "OpenAI Python SDK",
        "modules": ["openai"],
    },
    "anthropic": {
        "context7_id": "/anthropics/anthropic-sdk-python",
        "display": "Anthropic Python SDK",
        "modules": ["anthropic"],
    },
    "dspy": {
        "context7_id": "/stanfordnlp/dspy",
        "display": "DSPy",
        "modules": ["dspy"],
    },
    "crewai": {
        "context7_id": "/crewAIInc/crewAI",
        "display": "CrewAI",
        "modules": ["crewai"],
    },
    "autogen": {
        "context7_id": "/microsoft/autogen",
        "display": "AutoGen",
        "modules": ["autogen"],
    },
    "chromadb": {
        "context7_id": "/chroma-core/chroma",
        "display": "ChromaDB",
        "modules": ["chromadb"],
    },
    "pinecone": {
        "context7_id": "/pinecone-io/pinecone-python-client",
        "display": "Pinecone",
        "modules": ["pinecone"],
    },
    "qdrant": {
        "context7_id": "/qdrant/qdrant",
        "display": "Qdrant",
        "modules": ["qdrant_client"],
    },
    "weaviate": {
        "context7_id": "/weaviate/weaviate",
        "display": "Weaviate",
        "modules": ["weaviate"],
    },
    "fastapi": {
        "context7_id": "/fastapi/fastapi",
        "display": "FastAPI",
        "modules": ["fastapi"],
    },
    "flask": {
        "context7_id": "/pallets/flask",
        "display": "Flask",
        "modules": ["flask"],
    },
    "pydantic": {
        "context7_id": "/pydantic/pydantic",
        "display": "Pydantic",
        "modules": ["pydantic"],
    },
    "pandas": {
        "context7_id": "/pandas-dev/pandas",
        "display": "Pandas",
        "modules": ["pandas"],
    },
    "numpy": {
        "context7_id": "/numpy/numpy",
        "display": "NumPy",
        "modules": ["numpy"],
    },
}


def detect_from_file(filepath):
    """Analyze imports of a Python file and return detected stack."""
    with open(filepath) as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return {}

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])

    detected = {}
    for lib_key, lib_info in KNOWN_LIBRARIES.items():
        found = imports & set(lib_info["modules"])
        if found:
            detected[lib_key] = {
                "context7_id": lib_info["context7_id"],
                "display": lib_info["display"],
                "modules_found": sorted(found),
            }

    return detected


def detect_from_directory(directory):
    """Analyze all .py files in a directory and consolidate the stack."""
    all_detected = {}
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".py"):
                filepath = os.path.join(root, f)
                file_detected = detect_from_file(filepath)
                for lib_key, lib_info in file_detected.items():
                    if lib_key not in all_detected:
                        all_detected[lib_key] = lib_info
                    else:
                        existing = set(all_detected[lib_key]["modules_found"])
                        existing.update(lib_info["modules_found"])
                        all_detected[lib_key]["modules_found"] = sorted(existing)
    return all_detected


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Detect stack from Python files")
    parser.add_argument("path", help="File or directory to analyze")
    parser.add_argument("--output", "-o", help="Output JSON path")
    args = parser.parse_args()

    if os.path.isfile(args.path):
        result = detect_from_file(args.path)
    else:
        result = detect_from_directory(args.path)

    output = json.dumps(result, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)
