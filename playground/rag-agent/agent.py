#!/usr/bin/env python3
"""RAG agent for NovaTech company knowledge base.

Uses keyword matching for retrieval (deliberately bad — no embeddings,
no semantic search). Stuffs all retrieved docs into context without
reranking. Baseline ~40-45%.

Usage:
    python agent.py input.json
    python agent.py --input input.json --output output.json
"""

import json
import os
import sys

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage


SYSTEM_PROMPT = """Answer questions based on the provided context. If the context doesn't contain the answer, say you don't know."""

KNOWLEDGE_PATH = os.path.join(os.path.dirname(__file__), "knowledge.json")


def load_knowledge():
    """Load knowledge base from JSON."""
    with open(KNOWLEDGE_PATH) as f:
        return json.load(f)


def retrieve(query: str, knowledge: list, top_k: int = 2) -> list:
    """Keyword-based retrieval — deliberately simplistic.

    Only matches exact word overlaps. No stemming, no synonyms,
    no semantic similarity. This is the main weakness to evolve.
    """
    query_words = set(query.lower().split())
    scored = []
    for doc in knowledge:
        doc_words = set(doc["text"].lower().split())
        overlap = len(query_words & doc_words)
        scored.append((overlap, doc))

    scored.sort(key=lambda x: -x[0])
    return [doc for _, doc in scored[:top_k]]


def run(input_text: str) -> str:
    knowledge = load_knowledge()
    retrieved = retrieve(input_text, knowledge)

    # Context stuffing — no reranking, no relevance check
    context = "\n\n".join(f"[{doc['id']}]: {doc['text']}" for doc in retrieved)

    model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-lite",
        temperature=0.3,
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {input_text}"),
    ]
    response = model.invoke(messages)
    return response.content


def main():
    input_path = None
    output_path = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--input":
            input_path = args[i + 1]
            i += 2
        elif args[i] == "--output":
            output_path = args[i + 1]
            i += 2
        elif not args[i].startswith("-"):
            input_path = args[i]
            i += 1
        else:
            i += 1

    if not input_path:
        print("Usage: python agent.py input.json", file=sys.stderr)
        sys.exit(1)

    with open(input_path) as f:
        data = json.load(f)

    question = data.get("input", data.get("question", ""))
    answer = run(question)
    result = {"output": answer}

    if output_path:
        with open(output_path, "w") as f:
            json.dump(result, f)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
