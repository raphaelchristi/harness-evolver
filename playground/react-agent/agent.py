#!/usr/bin/env python3
"""ReAct agent with tools using LangGraph + Gemini.

Has 3 tools but uses them poorly — bad tool descriptions,
no routing guidance, excessive looping. Baseline ~40%.

Usage:
    python agent.py input.json
    python agent.py --input input.json --output output.json
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


# --- Tools (deliberately poor descriptions) ---

@tool
def calculator(expression: str) -> str:
    """Do math."""
    try:
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return f"Error: invalid characters in expression"
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


@tool
def lookup(topic: str) -> str:
    """Look up information."""
    # Deliberately small and incomplete knowledge base
    facts = {
        "python": "Python is a programming language created by Guido van Rossum in 1991.",
        "javascript": "JavaScript is a programming language for web development.",
        "rust": "Rust is a systems programming language focused on safety.",
        "earth": "Earth is the third planet from the Sun with a diameter of 12,742 km.",
        "mars": "Mars is the fourth planet from the Sun, known as the Red Planet.",
        "photosynthesis": "Photosynthesis is the process by which plants convert sunlight into energy.",
        "dna": "DNA (deoxyribonucleic acid) carries genetic instructions for life.",
        "tcp": "TCP is a connection-oriented protocol that ensures reliable data delivery.",
        "udp": "UDP is a connectionless protocol that prioritizes speed over reliability.",
        "http": "HTTP is the protocol used for transferring web pages on the internet.",
    }
    key = topic.lower().strip()
    for k, v in facts.items():
        if k in key:
            return v
    return f"No information found about '{topic}'."


@tool
def get_date() -> str:
    """Get today's date."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# --- Graph State ---

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# --- System prompt (deliberately vague) ---

SYSTEM_PROMPT = """You are an assistant with access to tools. Use them when needed."""


# --- Graph construction ---

def build_graph():
    model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-lite",
        temperature=0.5,
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
    )

    tools = [calculator, lookup, get_date]
    model_with_tools = model.bind_tools(tools)

    def agent_node(state: AgentState):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response = model_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState):
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


def run(input_text: str) -> str:
    app = build_graph()
    result = app.invoke({"messages": [HumanMessage(content=input_text)]})
    last_message = result["messages"][-1]
    return last_message.content


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
