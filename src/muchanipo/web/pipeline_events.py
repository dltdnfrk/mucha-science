from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
import time

from .pipeline_contract import JsonObject, PipelineRun


TERMINAL_EVENTS = frozenset({"done", "execution_cancelled", "terminal_run_done"})


def parse_pipeline_event(line: str) -> JsonObject:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        value = None
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return {
            "event": "pipeline_output_error",
            "message": "pipeline emitted a non-JSON line",
        }
    event: JsonObject = value
    data = event.get("data")
    if not isinstance(data, dict):
        return event
    flattened = dict(event)
    for key, item in data.items():
        if key not in flattened:
            flattened[key] = item
    return flattened


def runtime_status(runs: Sequence[PipelineRun], workspace_root: Path) -> JsonObject:
    running = [run for run in runs if run.process.poll() is None]
    active = running[-1] if running else None
    return {
        "running": active is not None,
        "stdin_open": active is not None
        and active.process.stdin is not None
        and not active.process.stdin.closed,
        "child_tracked": active is not None,
        "buffered_event_count": len(active.events) if active is not None else 0,
        "child_pid": active.process.pid if active is not None else None,
        "app_run_id": active.run_id if active is not None else None,
        "runtime_age_ms": (
            int(time.time() * 1000) - active.started_at_unix_ms
            if active is not None
            else None
        ),
        "workspace_root": str(workspace_root),
    }
