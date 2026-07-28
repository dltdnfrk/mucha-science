from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, IO

from src.research.depth import normalize_depth

from .completion import CompletionContext, complete_run
from .contracts import STAGE_ORDER, TerminalRunPaths, TerminalRunResult
from .events import render_dashboard, render_plain_event, write_event
from .failures import FailureContext, record_terminal_failure
from .paths import now_iso

PipelineRunner = Callable[..., dict[str, Any]]
CredentialCheck = Callable[[], None]
PathResolver = Callable[..., TerminalRunPaths]


def terminal_run(
    topic: str,
    *,
    pipeline_runner: PipelineRunner,
    credential_check: CredentialCheck,
    path_resolver: PathResolver,
    stdout: IO[str] | None = None,
    report_path: Path | None = None,
    run_dir: Path | None = None,
    offline: bool | None = None,
    jsonl: bool = False,
    dashboard: bool = False,
    pipeline_input: str | None = None,
    require_live: bool = False,
    depth: str = "deep",
) -> TerminalRunResult:
    out = stdout or sys.stdout
    normalized_depth = normalize_depth(depth)
    pipeline_topic = pipeline_input or topic
    paths = path_resolver(topic=topic, run_dir=run_dir, report_path=report_path)
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    status = {stage: "pending" for stage in STAGE_ORDER}
    started_at = time.time()

    with paths.events_path.open("w", encoding="utf-8") as events_file:
        def emit_terminal(event: dict[str, Any]) -> None:
            write_event(events_file, event)
            stage = str(event.get("stage") or "")
            if stage in status:
                if event.get("event") == "stage_started":
                    status[stage] = "active"
                elif event.get("event") == "stage_completed":
                    status[stage] = "done"
            if jsonl:
                out.write(json.dumps(event, ensure_ascii=False) + "\n")
                out.flush()
            elif dashboard:
                render_dashboard(out, topic=topic, paths=paths, status=status, event=event)
            else:
                render_plain_event(out, event)

        write_event(
            events_file,
            {
                "event": "terminal_run_started",
                "topic": topic,
                "run_id": paths.run_id,
                "report_path": str(paths.report_path),
                "events_path": str(paths.events_path),
                "offline": offline,
                "require_live": require_live,
                "depth": normalized_depth,
                "pipeline_input": pipeline_topic if pipeline_topic != topic else None,
                "created_at": now_iso(),
            },
        )
        if not jsonl and not dashboard:
            out.write(f"Muchanipo run started: {topic}\n")
            out.write(f"Run dir: {paths.run_dir}\n")
            out.flush()
        if dashboard:
            render_dashboard(out, topic=topic, paths=paths, status=status, event=None)

        failure_context = FailureContext(
            paths=paths,
            events_file=events_file,
            out=out,
            status=status,
            started_at=started_at,
            topic=topic,
            offline=offline,
            jsonl=jsonl,
            dashboard=dashboard,
            require_live=require_live,
            depth=normalized_depth,
        )
        try:
            if require_live:
                credential_check()
            result = pipeline_runner(
                pipeline_topic,
                progress_callback=emit_terminal,
                offline=offline,
                require_live=require_live,
                depth=normalized_depth,
            )
        except KeyboardInterrupt as exc:
            status["finalize"] = "error"
            record_terminal_failure(
                failure_context,
                event_name="terminal_run_interrupted",
                error_type="KeyboardInterrupt",
                message="interrupted by user",
            )
            raise exc
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - terminal boundary persists arbitrary pipeline failures.
            status["finalize"] = "error"
            record_terminal_failure(
                failure_context,
                event_name="terminal_run_error",
                error_type=type(exc).__name__,
                message=str(exc),
            )
            raise

    return complete_run(
        result,
        CompletionContext(
            topic=topic,
            pipeline_topic=pipeline_topic,
            paths=paths,
            out=out,
            status=status,
            started_at=started_at,
            offline=offline,
            require_live=require_live,
            depth=normalized_depth,
            jsonl=jsonl,
            dashboard=dashboard,
        ),
    )
