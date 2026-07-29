from __future__ import annotations

import sys
from typing import Any, IO

from .contracts import JSON_SCHEMA_VERSION


def orchestration_report(
    *,
    session: str = "muni",
    include_capture: bool = False,
    cleanup_workers: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    from src.muchanipo.orchestration import (
        DEFAULT_OPERATORS,
        cleanup_workers_report,
        orchestration_plan,
        orchestration_status,
    )

    if cleanup_workers:
        cleanup = cleanup_workers_report(session=session, dry_run=dry_run, force=force)
        actions = list(cleanup.get("actions") or [])
        return {
            "schema_version": JSON_SCHEMA_VERSION,
            "command": "muchanipo orchestrate",
            "session": session,
            "ok": bool(cleanup.get("ok")),
            "tmux_available": bool(cleanup.get("ok")) or bool(actions),
            "plan": orchestration_plan(),
            "windows": [],
            "panes": [],
            "operators": [operator.to_dict() for operator in DEFAULT_OPERATORS],
            "warnings": list(cleanup.get("warnings") or []),
            "cleanup": {
                "dry_run": bool(cleanup.get("dry_run")),
                "force": bool(cleanup.get("force")),
                "actions": actions,
            },
        }
    report = orchestration_status(session=session, include_capture=include_capture)
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "command": "muchanipo orchestrate",
        **report,
    }


def render_orchestration(
    *,
    stdout: IO[str] | None = None,
    session: str = "muni",
    include_capture: bool = False,
    cleanup_workers: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    out = stdout or sys.stdout
    report = orchestration_report(
        session=session,
        include_capture=include_capture,
        cleanup_workers=cleanup_workers,
        dry_run=dry_run,
        force=force,
    )
    out.write("\nOperator orchestration\n----------------------\n")
    out.write(f"Session: {report['session']}\n")
    out.write(f"Status : {'OK' if report.get('ok') else 'WARN'}\n")
    if cleanup_workers:
        cleanup_mode = "dry run" if dry_run else "forced" if force else "requires force"
        out.write(f"Cleanup: {cleanup_mode}\n")
        cleanup = report.get("cleanup") if isinstance(report.get("cleanup"), dict) else {}
        for action in cleanup.get("actions", []):
            out.write(f"- {action['status']}: {action['target']} {action['action']}\n")
    else:
        _render_status(out, report, include_capture=include_capture)
    if report.get("warnings"):
        out.write("\nWarnings\n")
        for warning in report["warnings"]:
            out.write(f"- {warning}\n")
    out.write("\n")
    out.flush()
    return report


def _render_status(out: IO[str], report: dict[str, Any], *, include_capture: bool) -> None:
    plan = report.get("plan") or {}
    out.write(f"Protected window: {plan.get('protected_window')}\n")
    out.write(
        f"Worker windows  : {', '.join(str(item) for item in plan.get('worker_windows', []))}\n"
    )
    out.write("\nOperators\n")
    for operator in report.get("operators", []):
        marker = (
            "OK"
            if operator.get("operator_pane_present") and operator.get("worker_window_present")
            else "WARN"
        )
        out.write(
            f"[{marker}] {operator['agent']:<8} pane={operator['pane']} "
            f"worker={operator['assigned_window']} mode={operator['mode']}\n"
        )
        if operator.get("model_requirement"):
            out.write(f"       model: {operator['model_requirement']}\n")
    if report.get("windows"):
        out.write("\nWindows\n")
        for window in report["windows"]:
            active = " active" if window.get("active") else ""
            out.write(
                f"- {window['index']}: {window['name']} panes={window['pane_count']}{active}\n"
            )
    if include_capture and report.get("captures"):
        out.write("\nCaptures\n")
        for target, capture in report["captures"].items():
            snippet = str(capture).strip().splitlines()[-1:] or [""]
            out.write(f"- window {target}: {snippet[0]}\n")
