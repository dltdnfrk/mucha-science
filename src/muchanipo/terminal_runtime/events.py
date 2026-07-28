from __future__ import annotations

import json
from typing import Any, IO

from .contracts import STAGE_LABELS, STAGE_ORDER, TerminalRunPaths


def write_event(stream: IO[str], event: dict[str, Any]) -> None:
    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    stream.flush()


def render_plain_event(out: IO[str], event: dict[str, Any]) -> None:
    stage = str(event.get("stage") or "")
    if not stage:
        return
    label = STAGE_LABELS.get(stage, stage)
    if event.get("event") == "stage_started":
        out.write(f"[>] {label}\n")
    elif event.get("event") == "stage_completed":
        out.write(f"[✓] {label}\n")
    out.flush()


def render_dashboard(
    out: IO[str],
    *,
    topic: str,
    paths: TerminalRunPaths,
    status: dict[str, str],
    event: dict[str, Any] | None,
) -> None:
    if hasattr(out, "isatty") and out.isatty():
        out.write("\x1b[2J\x1b[H")
    out.write("Muchanipo Terminal Core\n")
    out.write(f"Topic : {topic}\n")
    out.write(f"Run   : {paths.run_id}\n")
    out.write(f"Report: {paths.report_path}\n\n")
    for stage in STAGE_ORDER:
        marker = {"pending": " ", "active": ">", "done": "✓", "error": "!"}.get(
            status.get(stage, "pending"), " "
        )
        out.write(f"[{marker}] {STAGE_LABELS[stage]}\n")
    if event:
        out.write(f"\nLast event: {event.get('event')}")
        if event.get("stage"):
            out.write(f" / {event.get('stage')}")
        out.write("\n")
    out.flush()
