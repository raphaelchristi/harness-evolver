#!/usr/bin/env python3
"""Simple Q&A agent using Gemini via LangChain.

Single-call topology. Deliberately mediocre — vague system prompt,
no output format, no examples. Baseline should score ~35-40%.

Usage:
    python agent.py input.json
    python agent.py --input input.json --output output.json
"""

import json
import os
import sys

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage


SYSTEM_PROMPT = """You are a helpful assistant."""


def run(input_text: str) -> str:
    model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-lite",
        temperature=0.7,
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
    )
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=input_text),
    ]
    response = model.invoke(messages)
    return response.content


def main():
    # Parse input — support both positional and --input/--output flags
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
