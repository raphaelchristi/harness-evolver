#!/usr/bin/env python3
"""Fetch and summarize production LangSmith traces for Harness Evolver.

Queries the LangSmith REST API directly (urllib, stdlib-only) to fetch
production traces and produce:
  1. A markdown seed file for the testgen agent (production_seed.md)
  2. A JSON summary for programmatic use (production_seed.json)

Usage:
    python3 seed_from_traces.py \
        --project ceppem-langgraph \
        --output-md .harness-evolver/production_seed.md \
        --output-json .harness-evolver/production_seed.json \
        [--api-key-env LANGSMITH_API_KEY] \
        [--limit 100]

Stdlib-only. No external dependencies (no langsmith-cli needed).
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

LANGSMITH_API_BASE = "https://api.smith.langchain.com/api/v1"


def langsmith_request(endpoint, api_key, method="GET", body=None, params=None):
    """Make a request to the LangSmith REST API."""
    url = f"{LANGSMITH_API_BASE}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
    }

    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        print(f"LangSmith API error {e.code}: {body_text}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"LangSmith API request failed: {e}", file=sys.stderr)
        return None


def fetch_runs(project_name, api_key, limit=100):
    """Fetch recent root runs from a LangSmith project."""
    # Try POST /runs/query first (newer API)
    body = {
        "project_name": project_name,
        "is_root": True,
        "limit": limit,
    }
    result = langsmith_request("runs/query", api_key, method="POST", body=body)
    if result and isinstance(result, dict):
        return result.get("runs", result.get("results", []))
    if result and isinstance(result, list):
        return result

    # Fallback: GET /runs with query params
    params = {
        "project_name": project_name,
        "is_root": "true",
        "limit": str(limit),
    }
    result = langsmith_request("runs", api_key, params=params)
    if result and isinstance(result, list):
        return result
    if result and isinstance(result, dict):
        return result.get("runs", result.get("results", []))

    return []


def extract_input(run):
    """Extract user input from a run's inputs field."""
    inputs = run.get("inputs", {})
    if not inputs:
        return None
    if isinstance(inputs, str):
        return inputs

    # Direct field
    for key in ("input", "question", "query", "prompt", "text", "user_input"):
        if key in inputs and isinstance(inputs[key], str):
            return inputs[key]

    # LangChain messages format
    messages = inputs.get("messages") or inputs.get("input")
    if isinstance(messages, list):
        if messages and isinstance(messages[0], list):
            messages = messages[0]
        for msg in messages:
            if isinstance(msg, dict):
                if msg.get("type") in ("human", "HumanMessage") or msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content:
                        return content
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                return part.get("text", "")
            elif isinstance(msg, str) and msg:
                return msg

    return None


def extract_output(run):
    """Extract the output/response from a run."""
    outputs = run.get("outputs", {})
    if not outputs:
        return None
    if isinstance(outputs, str):
        return outputs

    for key in ("output", "answer", "result", "response", "text"):
        if key in outputs and isinstance(outputs[key], str):
            return outputs[key]

    # LangChain messages format
    messages = outputs.get("messages") or outputs.get("output")
    if isinstance(messages, list):
        if messages and isinstance(messages[0], list):
            messages = messages[0]
        for msg in reversed(messages):
            if isinstance(msg, dict):
                if msg.get("type") in ("ai", "AIMessage", "assistant") or msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content:
                        return content
            elif isinstance(msg, str) and msg:
                return msg

    return None


def get_feedback(run):
    """Extract feedback from a run."""
    fb = run.get("feedback_stats") or {}
    if isinstance(fb, dict):
        pos = fb.get("thumbs_up", 0) or fb.get("positive", 0) or 0
        neg = fb.get("thumbs_down", 0) or fb.get("negative", 0) or 0
        if neg > 0:
            return "negative"
        if pos > 0:
            return "positive"
    return None


def categorize_run(run):
    """Categorize a run by its name/type."""
    name = run.get("name", "unknown")
    # Use top-level run name as category
    return name


def analyze_runs(runs):
    """Analyze a batch of runs and produce structured insights."""
    if not runs:
        return None

    processed = []
    categories = Counter()
    errors = []
    latencies = []
    token_counts = []
    feedbacks = {"positive": 0, "negative": 0, "none": 0}

    for run in runs:
        user_input = extract_input(run)
        output = extract_output(run)
        error = run.get("error")
        tokens = run.get("total_tokens") or 0
        latency_ms = None
        feedback = get_feedback(run)

        # Calculate latency from start/end times
        start = run.get("start_time") or run.get("start_dt")
        end = run.get("end_time") or run.get("end_dt")
        if isinstance(start, str) and isinstance(end, str):
            try:
                from datetime import datetime as dt
                s = dt.fromisoformat(start.replace("Z", "+00:00"))
                e = dt.fromisoformat(end.replace("Z", "+00:00"))
                latency_ms = int((e - s).total_seconds() * 1000)
            except Exception:
                pass
        elif run.get("latency"):
            latency_ms = int(run["latency"] * 1000) if isinstance(run["latency"], float) else run["latency"]

        category = categorize_run(run)
        categories[category] += 1

        entry = {
            "input": (user_input or "")[:500],
            "output": (output or "")[:300],
            "category": category,
            "tokens": tokens,
            "latency_ms": latency_ms,
            "error": (error or "")[:200] if error else None,
            "feedback": feedback,
        }
        processed.append(entry)

        if error:
            errors.append({"error": error[:200], "input": (user_input or "")[:200], "category": category})
        if latency_ms:
            latencies.append(latency_ms)
        if tokens:
            token_counts.append(tokens)

        if feedback == "positive":
            feedbacks["positive"] += 1
        elif feedback == "negative":
            feedbacks["negative"] += 1
        else:
            feedbacks["none"] += 1

    # Compute statistics
    stats = {
        "total_traces": len(runs),
        "with_input": sum(1 for p in processed if p["input"]),
        "with_error": len(errors),
        "error_rate": len(errors) / max(len(runs), 1),
        "feedback": feedbacks,
    }

    if latencies:
        latencies.sort()
        stats["latency"] = {
            "avg_ms": int(sum(latencies) / len(latencies)),
            "p50_ms": latencies[len(latencies) // 2],
            "p95_ms": latencies[int(len(latencies) * 0.95)] if len(latencies) >= 20 else latencies[-1],
            "max_ms": latencies[-1],
        }

    if token_counts:
        stats["tokens"] = {
            "avg": int(sum(token_counts) / len(token_counts)),
            "max": max(token_counts),
            "total": sum(token_counts),
        }

    # Group by category
    by_category = {}
    for entry in processed:
        cat = entry["category"]
        by_category.setdefault(cat, []).append(entry)

    # Error patterns
    error_patterns = Counter()
    for e in errors:
        # Normalize error to first 60 chars
        pattern = e["error"][:60]
        error_patterns[pattern] += 1

    return {
        "stats": stats,
        "categories": dict(categories.most_common()),
        "by_category": by_category,
        "error_patterns": dict(error_patterns.most_common(10)),
        "errors": errors[:20],
        "processed": processed,
    }


def generate_markdown_seed(analysis, project_name):
    """Generate a markdown seed file for the testgen agent."""
    stats = analysis["stats"]
    lines = [
        f"# Production Trace Analysis: {project_name}",
        "",
        f"*{stats['total_traces']} traces analyzed*",
        "",
        "## Key Metrics",
        "",
        f"- **Error rate**: {stats['error_rate']:.1%}",
    ]

    if "latency" in stats:
        lat = stats["latency"]
        lines.append(f"- **Latency**: {lat['avg_ms']}ms avg, {lat['p50_ms']}ms p50, {lat['p95_ms']}ms p95")

    if "tokens" in stats:
        tok = stats["tokens"]
        lines.append(f"- **Tokens**: {tok['avg']} avg, {tok['max']} max")

    fb = stats["feedback"]
    total_fb = fb["positive"] + fb["negative"]
    if total_fb > 0:
        lines.append(f"- **User feedback**: {fb['positive']}/{total_fb} positive ({fb['positive']/total_fb:.0%})")

    # Traffic distribution
    lines.extend(["", "## Traffic Distribution", ""])
    total = stats["total_traces"]
    for cat, count in sorted(analysis["categories"].items(), key=lambda x: -x[1]):
        pct = count / max(total, 1) * 100
        lines.append(f"- **{cat}**: {count} traces ({pct:.0f}%)")

    # Sample inputs by category
    lines.extend(["", "## Sample Inputs by Category", ""])
    for cat, entries in sorted(analysis["by_category"].items(), key=lambda x: -len(x[1])):
        lines.append(f"### {cat} ({len(entries)} traces)")
        lines.append("")
        # Show up to 8 sample inputs per category
        shown = 0
        for entry in entries:
            if not entry["input"] or shown >= 8:
                break
            status = "ERROR" if entry["error"] else "ok"
            tok_str = f", {entry['tokens']}tok" if entry["tokens"] else ""
            lat_str = f", {entry['latency_ms']}ms" if entry["latency_ms"] else ""
            fb_str = ""
            if entry["feedback"] == "negative":
                fb_str = " [NEGATIVE FEEDBACK]"
            elif entry["feedback"] == "positive":
                fb_str = " [+]"
            lines.append(f'- "{entry["input"][:150]}" ({status}{tok_str}{lat_str}){fb_str}')
            shown += 1
        lines.append("")

    # Error patterns
    if analysis["error_patterns"]:
        lines.extend(["## Error Patterns", ""])
        for pattern, count in analysis["error_patterns"].items():
            lines.append(f"- **{pattern}**: {count} occurrences")
        lines.append("")

    # Negative feedback traces
    neg_traces = [e for e in analysis["processed"] if e["feedback"] == "negative" and e["input"]]
    if neg_traces:
        lines.extend(["## Traces with Negative Feedback (high priority)", ""])
        for entry in neg_traces[:10]:
            lines.append(f'- "{entry["input"][:200]}" → category: {entry["category"]}')
        lines.append("")

    # Guidance for testgen
    lines.extend([
        "## Guidance for Test Generation",
        "",
        "Use the above data to generate test cases that:",
        "1. **Match the real traffic distribution** — generate more tasks for high-traffic categories",
        "2. **Include actual user phrasing** — real inputs show how users actually communicate (informal, abbreviations, typos)",
        "3. **Cover real error patterns** — the errors above are genuine failure modes, not imagined scenarios",
        "4. **Prioritize negative feedback traces** — these are confirmed bad experiences",
        "5. **Include slow queries as edge cases** — high-latency traces may reveal timeout or complexity issues",
    ])

    return "\n".join(lines)


def generate_json_summary(analysis, project_name):
    """Generate a JSON summary for programmatic use."""
    return {
        "project": project_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": analysis["stats"],
        "categories": analysis["categories"],
        "error_patterns": analysis["error_patterns"],
        "sample_inputs": {
            cat: [e["input"] for e in entries if e["input"]][:10]
            for cat, entries in analysis["by_category"].items()
        },
        "negative_feedback_inputs": [
            e["input"] for e in analysis["processed"]
            if e["feedback"] == "negative" and e["input"]
        ][:20],
        "slow_queries": [
            {"input": e["input"][:200], "latency_ms": e["latency_ms"], "category": e["category"]}
            for e in sorted(analysis["processed"], key=lambda x: -(x["latency_ms"] or 0))
            if e["latency_ms"] and e["input"]
        ][:10],
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch and summarize production LangSmith traces")
    parser.add_argument("--project", required=True, help="LangSmith project name")
    parser.add_argument("--api-key-env", default="LANGSMITH_API_KEY",
                        help="Env var containing API key (default: LANGSMITH_API_KEY)")
    parser.add_argument("--limit", type=int, default=100, help="Max traces to fetch (default: 100)")
    parser.add_argument("--output-md", required=True, help="Output path for markdown seed")
    parser.add_argument("--output-json", required=True, help="Output path for JSON summary")
    parser.add_argument("--use-sdk", action="store_true",
                        help="Use langsmith Python SDK instead of REST API (v3 mode)")
    args = parser.parse_args()

    print(f"Fetching up to {args.limit} traces from LangSmith project '{args.project}'...")

    if args.use_sdk:
        try:
            from langsmith import Client
            client = Client()
            raw_runs = list(client.list_runs(
                project_name=args.project, is_root=True, limit=args.limit,
            ))
            # Convert SDK run objects to dicts matching our format
            runs = []
            for r in raw_runs:
                run_dict = {
                    "id": str(r.id),
                    "name": r.name,
                    "inputs": r.inputs,
                    "outputs": r.outputs,
                    "error": r.error,
                    "total_tokens": r.total_tokens,
                    "feedback_stats": None,
                    "start_time": r.start_time.isoformat() if r.start_time else None,
                    "end_time": r.end_time.isoformat() if r.end_time else None,
                }
                runs.append(run_dict)
        except ImportError:
            print("langsmith package not installed. Use --use-sdk with pip install langsmith", file=sys.stderr)
            sys.exit(1)
    else:
        api_key = os.environ.get(args.api_key_env, "")
        if not api_key:
            print(f"No API key found in ${args.api_key_env} — cannot fetch production traces", file=sys.stderr)
            sys.exit(1)
        runs = fetch_runs(args.project, api_key, args.limit)

    if not runs:
        print("No traces found. The project may be empty or the name may be wrong.")
        # Write empty files so downstream doesn't break
        for path in [args.output_md, args.output_json]:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(args.output_md, "w") as f:
            f.write(f"# Production Trace Analysis: {args.project}\n\nNo traces found.\n")
        with open(args.output_json, "w") as f:
            json.dump({"project": args.project, "stats": {"total_traces": 0}}, f, indent=2)
        return

    print(f"Fetched {len(runs)} traces. Analyzing...")
    analysis = analyze_runs(runs)

    if not analysis:
        print("Analysis failed — no processable traces")
        return

    # Write markdown seed
    os.makedirs(os.path.dirname(args.output_md) or ".", exist_ok=True)
    md = generate_markdown_seed(analysis, args.project)
    with open(args.output_md, "w") as f:
        f.write(md)

    # Write JSON summary
    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    summary = generate_json_summary(analysis, args.project)
    with open(args.output_json, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    stats = analysis["stats"]
    cats = len(analysis["categories"])
    errs = stats["with_error"]
    print(f"Production seed generated:")
    print(f"  {stats['total_traces']} traces, {cats} categories, {errs} errors ({stats['error_rate']:.1%})")
    print(f"  {args.output_md}")
    print(f"  {args.output_json}")


if __name__ == "__main__":
    main()
