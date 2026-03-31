"""TraceLogger — optional helper for harnesses to write structured trace records.

Usage in a harness:
    from trace_logger import TraceLogger

    trace = TraceLogger(traces_dir)
    trace.step("llm_call", {"prompt": p, "response": r, "model": "gpt-4"})
    trace.step("tool_use", {"tool": "search", "query": q, "results": results})
    trace.save()

Stdlib-only. No external dependencies.
"""

import json
import os
import time


class TraceLogger:
    def __init__(self, traces_dir):
        self.traces_dir = traces_dir
        self._steps = []
        if traces_dir:
            os.makedirs(traces_dir, exist_ok=True)

    def step(self, name, data=None):
        self._steps.append({
            "name": name,
            "timestamp": time.time(),
            "data": data if data is not None else {},
        })

    def save(self):
        if not self.traces_dir:
            return
        path = os.path.join(self.traces_dir, "trace.json")
        with open(path, "w") as f:
            json.dump(self._steps, f, indent=2)

    @property
    def steps(self):
        return list(self._steps)
