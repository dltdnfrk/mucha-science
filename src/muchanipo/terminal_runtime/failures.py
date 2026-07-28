from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import IO

from .contracts import TerminalRunPaths
from .events import render_dashboard, write_event
from .paths import now_iso


@dataclass(frozen=True, slots=True)
class FailureContext:
    paths: TerminalRunPaths
    events_file: IO[str]
    out: IO[str]
    status: dict[str, str]
    started_at: float
    topic: str
    offline: bool | None
    jsonl: bool
    dashboard: bool
    require_live: bool
    depth: str


def record_terminal_failure(
    context: FailureContext,
    *,
    event_name: str,
    error_type: str,
    message: str,
) -> None:
    event = {
        "event": event_name,
        "topic": context.topic,
        "run_id": context.paths.run_id,
        "message": message,
        "error_type": error_type,
        "created_at": now_iso(),
    }
    write_event(context.events_file, event)
    failure_status = "interrupted" if event_name == "terminal_run_interrupted" else "failed"
    done_event = {
        "event": "done",
        "pipeline": "terminal",
        "run_id": context.paths.run_id,
        "aborted": True,
        "status": failure_status,
        "error_type": error_type,
    }
    write_event(context.events_file, done_event)
    summary = {
        "topic": context.topic,
        "run_id": context.paths.run_id,
        "status": failure_status,
        "report_path": str(context.paths.report_path),
        "events_path": str(context.paths.events_path),
        "offline": context.offline,
        "require_live": context.require_live,
        "depth": context.depth,
        "duration_sec": round(time.time() - context.started_at, 3),
        "error_type": error_type,
        "message": message,
        "completed_at": now_iso(),
    }
    context.paths.summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if context.jsonl:
        context.out.write(json.dumps(event, ensure_ascii=False) + "\n")
        context.out.write(json.dumps(done_event, ensure_ascii=False) + "\n")
    elif context.dashboard:
        render_dashboard(
            context.out,
            topic=context.topic,
            paths=context.paths,
            status=context.status,
            event=done_event,
        )
        context.out.write("\n")
    elif event_name == "terminal_run_interrupted":
        context.out.write("\nINTERRUPTED: run stopped by user. Partial artifacts were saved.\n")
    else:
        context.out.write(f"\nERROR: {error_type}: {message}\n")
        context.out.write("Partial artifacts were saved.\n")
    context.out.flush()
