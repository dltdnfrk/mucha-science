from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, IO

from .contracts import STAGE_ORDER, TerminalRunPaths, TerminalRunResult
from .events import render_dashboard, write_event
from .paths import now_iso
from .quality import research_quality_iteration_counts, research_quality_snapshot


@dataclass(frozen=True, slots=True)
class CompletionContext:
    topic: str
    pipeline_topic: str
    paths: TerminalRunPaths
    out: IO[str]
    status: dict[str, str]
    started_at: float
    offline: bool | None
    require_live: bool
    depth: str
    jsonl: bool
    dashboard: bool


def complete_run(result: dict[str, Any], context: CompletionContext) -> TerminalRunResult:
    quality_only = bool(result.get("research_quality_only"))
    quality_snapshot = research_quality_snapshot(result) if quality_only else {}
    report_markdown = str(result.get("report_md") or "")
    if not quality_only:
        context.paths.report_path.parent.mkdir(parents=True, exist_ok=True)
        context.paths.report_path.write_text(report_markdown, encoding="utf-8")

    terminal_status = _terminal_status(quality_only, quality_snapshot)
    summary = _build_summary(result, context, terminal_status, quality_snapshot)
    context.paths.summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    completion_events = _completion_events(
        result=result,
        summary=summary,
        report_markdown=report_markdown,
        quality_only=quality_only,
        quality_snapshot=quality_snapshot,
        paths=context.paths,
    )
    with context.paths.events_path.open("a", encoding="utf-8") as append_events:
        for event in completion_events:
            write_event(append_events, event)
    _render_completion(context, completion_events, quality_only)
    return TerminalRunResult(
        topic=context.topic,
        run_id=context.paths.run_id,
        report_path=context.paths.report_path,
        events_path=context.paths.events_path,
        summary_path=context.paths.summary_path,
        offline=context.offline,
        stage_status=dict(context.status),
    )


def _terminal_status(quality_only: bool, snapshot: dict[str, Any]) -> str:
    if not quality_only:
        return "completed"
    readiness = str(snapshot.get("research_quality_readiness") or "ready")
    return "research_quality_ready" if readiness == "ready" else "research_quality_needs_review"


def _build_summary(
    result: dict[str, Any],
    context: CompletionContext,
    terminal_status: str,
    quality_snapshot: dict[str, Any],
) -> dict[str, Any]:
    quality_only = bool(result.get("research_quality_only"))
    summary = {
        "topic": context.topic,
        "run_id": context.paths.run_id,
        "status": terminal_status,
        "pipeline_input": context.pipeline_topic if context.pipeline_topic != context.topic else None,
        "report_path": None if quality_only else str(context.paths.report_path),
        "events_path": str(context.paths.events_path),
        "offline": context.offline,
        "require_live": context.require_live,
        "depth": context.depth,
        "target_runtime_seconds": getattr(result.get("depth_profile"), "target_runtime_seconds", None),
        "council_persona_pool_size": int(result.get("council_persona_pool_size") or 0),
        "active_council_persona_count": int(result.get("active_council_persona_count") or 0),
        "council_turn_count": len(result.get("council_turn_transcript") or []),
        "duration_sec": round(time.time() - context.started_at, 3),
        "round_count": len(result.get("rounds") or []),
        "executed_council_round_count": int(result.get("executed_council_round_count") or 0),
        "brief_id": getattr(result.get("brief"), "id", None),
        "vault_path": str(result.get("vault_path") or ""),
        "completed_at": now_iso(),
    }
    if quality_only:
        summary.update(
            {
                "research_quality_only": True,
                "research_quality_stop": str(
                    quality_snapshot.get("research_quality_stop")
                    or result.get("research_quality_only_stop")
                    or "before_council"
                ),
                "research_quality_snapshot": quality_snapshot,
                **research_quality_iteration_counts(quality_snapshot),
            }
        )
    return summary


def _completion_events(
    *,
    result: dict[str, Any],
    summary: dict[str, Any],
    report_markdown: str,
    quality_only: bool,
    quality_snapshot: dict[str, Any],
    paths: TerminalRunPaths,
) -> list[dict[str, Any]]:
    done_event = {
        "event": "done",
        "pipeline": "terminal",
        "report_path": summary["report_path"],
        "vault_path": str(result.get("vault_path") or ""),
        "status": summary["status"],
        "depth": summary["depth"],
        "council_persona_pool_size": summary["council_persona_pool_size"],
        "active_council_persona_count": summary["active_council_persona_count"],
        "council_turn_count": summary["council_turn_count"],
    }
    if quality_only:
        done_event.update(
            {
                "research_quality_only": True,
                "research_quality_stop": summary["research_quality_stop"],
                "research_quality_snapshot": quality_snapshot,
            }
        )
    final_report_event = {
        "event": "final_report",
        "markdown": report_markdown,
        "report_path": str(paths.report_path),
        "vault_path": str(result.get("vault_path") or ""),
        "chapter_count": sum(
            1 for line in report_markdown.splitlines() if line.startswith("## ")
        ),
    }
    terminal_done_event = {"event": "terminal_run_done", **summary}
    if quality_only:
        return [done_event, terminal_done_event]
    return [final_report_event, done_event, terminal_done_event]


def _render_completion(
    context: CompletionContext,
    events: list[dict[str, Any]],
    quality_only: bool,
) -> None:
    if context.jsonl:
        for event in events:
            context.out.write(json.dumps(event, ensure_ascii=False) + "\n")
    elif context.dashboard:
        context.status.update({stage: "done" for stage in STAGE_ORDER})
        render_dashboard(
            context.out,
            topic=context.topic,
            paths=context.paths,
            status=context.status,
            event=events[-1],
        )
        context.out.write("\n")
    else:
        if quality_only:
            context.out.write("Research quality snapshot ready before council.\n")
        else:
            context.out.write(f"Report: {context.paths.report_path}\n")
        context.out.write(f"Events: {context.paths.events_path}\n")
        context.out.write("Muchanipo run completed.\n")
    context.out.flush()
