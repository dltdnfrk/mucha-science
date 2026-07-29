"""Compatibility facade for the terminal-native Muchanipo runtime."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, IO

from src.runtime.live_mode import assert_mimo_opencode_policy_credentials

from .terminal_runtime import doctor as _doctor
from .terminal_runtime import events as _events
from .terminal_runtime import home as _home
from .terminal_runtime import interview as _interview
from .terminal_runtime import lifecycle as _lifecycle
from .terminal_runtime import orchestration as _orchestration
from .terminal_runtime import paths as _paths
from .terminal_runtime import providers as _providers
from .terminal_runtime import quality as _quality
from .terminal_runtime import reports as _reports
from .terminal_runtime import runs as _runs
from .terminal_runtime.contracts import (
    CLI_JSON_CONTRACTS_V1,
    DEMO_TOPIC,
    HOME_FAILURE_SCAN_LIMIT,
    HOME_RECENT_RUN_LIMIT,
    JSON_SCHEMA_VERSION,
    STAGE_LABELS,
    STAGE_ORDER,
    InterviewCapture,
    TerminalRunPaths,
    TerminalRunResult,
)


def run_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Import the heavy pipeline only when a run starts."""
    from src.pipeline.runner import run_pipeline as pipeline_runner

    return pipeline_runner(*args, **kwargs)


def terminal_run(
    topic: str,
    *,
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
    return _lifecycle.terminal_run(
        topic,
        pipeline_runner=run_pipeline,
        credential_check=assert_mimo_opencode_policy_credentials,
        path_resolver=_resolve_paths,
        stdout=stdout,
        report_path=report_path,
        run_dir=run_dir,
        offline=offline,
        jsonl=jsonl,
        dashboard=dashboard,
        pipeline_input=pipeline_input,
        require_live=require_live,
        depth=depth,
    )


def conduct_interview(
    topic: str,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> InterviewCapture:
    return _interview.conduct_interview(topic, stdin=stdin, stdout=stdout)


def terminal_app(
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> int:
    actions = _home.HomeActions(
        terminal_run=terminal_run,
        conduct_interview=conduct_interview,
        render_runs=render_runs,
        render_cli_status=render_cli_status,
        render_references=render_references,
        render_guard=render_guard,
        render_orchestration=render_orchestration,
        render_json_contracts=render_json_contracts,
        render_doctor=render_doctor,
    )
    return _home.terminal_app(actions, stdin=stdin, stdout=stdout)


def cli_statuses() -> list[dict[str, Any]]:
    return _providers.cli_statuses(
        path_resolver=_resolve_cli_path,
        run_command=subprocess.run,
    )


def cli_prompt_probes(
    records: list[dict[str, Any]] | None = None,
    *,
    timeout_sec: int | None = None,
) -> list[dict[str, Any]]:
    return _providers.cli_prompt_probes(
        records,
        timeout_sec=timeout_sec,
        status_loader=cli_statuses,
        probe_caller=_call_provider_probe,
    )


def render_cli_status(
    *,
    stdout: IO[str] | None = None,
    probe: bool = False,
) -> list[dict[str, Any]]:
    return _providers.render_cli_status(
        stdout=stdout,
        probe=probe,
        status_loader=cli_statuses,
        prompt_loader=cli_prompt_probes,
    )


def status_report(*, probe: bool = False) -> dict[str, Any]:
    return _providers.status_report(
        probe=probe,
        status_loader=cli_statuses,
        prompt_loader=cli_prompt_probes,
    )


def doctor_report(*, runs_dir: Path | None = None) -> dict[str, Any]:
    return _doctor.doctor_report(runs_dir=runs_dir, status_loader=cli_statuses)


def render_doctor(
    *,
    stdout: IO[str] | None = None,
    runs_dir: Path | None = None,
) -> dict[str, Any]:
    return _doctor.render_doctor(
        stdout=stdout,
        runs_dir=runs_dir,
        report_loader=doctor_report,
    )


def references_report() -> dict[str, Any]:
    return _reports.references_report()


def render_references(*, stdout: IO[str] | None = None) -> dict[str, Any]:
    return _reports.render_references(stdout=stdout, report_loader=references_report)


def guard_report(*, strict: bool = False, include_untracked: bool = True) -> dict[str, Any]:
    return _reports.guard_report(strict=strict, include_untracked=include_untracked)


def render_guard(*, stdout: IO[str] | None = None, strict: bool = False) -> dict[str, Any]:
    return _reports.render_guard(stdout=stdout, strict=strict)


def orchestration_report(
    *,
    session: str = "muni",
    include_capture: bool = False,
    cleanup_workers: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    return _orchestration.orchestration_report(
        session=session,
        include_capture=include_capture,
        cleanup_workers=cleanup_workers,
        dry_run=dry_run,
        force=force,
    )


def render_orchestration(
    *,
    stdout: IO[str] | None = None,
    session: str = "muni",
    include_capture: bool = False,
    cleanup_workers: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    return _orchestration.render_orchestration(
        stdout=stdout,
        session=session,
        include_capture=include_capture,
        cleanup_workers=cleanup_workers,
        dry_run=dry_run,
        force=force,
    )


def list_runs(*, runs_dir: Path | None = None, limit: int = 10) -> list[dict[str, Any]]:
    return _runs.list_runs(runs_dir=runs_dir, limit=limit)


def runs_report(*, runs_dir: Path | None = None, limit: int = 10) -> dict[str, Any]:
    root = runs_dir or _default_runs_dir()
    safe_limit = max(1, limit)
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "command": "muchanipo runs",
        "runs_dir": str(root),
        "limit": safe_limit,
        "runs": list_runs(runs_dir=root, limit=safe_limit),
    }


def home_snapshot(
    *,
    runs_dir: Path | None = None,
    recent_limit: int = HOME_RECENT_RUN_LIMIT,
    failure_scan_limit: int = HOME_FAILURE_SCAN_LIMIT,
) -> dict[str, Any]:
    return _runs.home_snapshot(
        runs_dir=runs_dir,
        recent_limit=recent_limit,
        failure_scan_limit=failure_scan_limit,
    )


def render_runs(
    *,
    stdout: IO[str] | None = None,
    runs_dir: Path | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    return _runs.render_runs(stdout=stdout, runs_dir=runs_dir, limit=limit)


json_contracts_report = _reports.json_contracts_report
render_json_contracts = _reports.render_json_contracts
_normalize_home_command = _home.normalize_home_command
_research_quality_snapshot = _quality.research_quality_snapshot
_research_quality_iteration_counts = _quality.research_quality_iteration_counts
_parse_artifact = _quality.parse_artifact
_as_dict = _quality.as_dict
_coerce_int = _quality.coerce_int
_coerce_float = _quality.coerce_float
_interview_answer_label = _interview.interview_answer_label
_read_prompt = _interview.read_prompt
_offline_from_mode = _home.offline_from_mode
_truncate = _home.truncate
_render_help = _home.render_help
_first_failed_run = _runs.first_failed_run
_resolve_cli_path = _providers.resolve_cli_path
_first_error_line = _providers.first_error_line
_call_provider_probe = _providers.call_provider_probe
_extract_json_object = _providers.extract_json_object
_repo_root = _paths.repo_root
_runs_dir_check = _doctor.runs_dir_check
_python_check = _doctor.python_check
_entrypoint_check = _doctor.entrypoint_check
_provider_probe_check = _doctor.provider_probe_check
_execution_mode_check = _doctor.execution_mode_check
_overall_status = _doctor.overall_status
_doctor_recommendations = _doctor.doctor_recommendations
_default_runs_dir = _paths.default_runs_dir
_new_run_id = _paths.new_run_id
_now_iso = _paths.now_iso
_write_event = _events.write_event
_render_plain_event = _events.render_plain_event
_render_dashboard = _events.render_dashboard


def _resolve_paths(
    *,
    topic: str,
    run_dir: Path | None,
    report_path: Path | None,
) -> TerminalRunPaths:
    return _paths.resolve_paths(topic=topic, run_dir=run_dir, report_path=report_path)


def _render_home(out: IO[str], *, runs_dir: Path | None = None) -> None:
    _home.render_home(out, runs_dir=runs_dir)


def _render_home_runs(out: IO[str], *, snapshot: dict[str, Any]) -> None:
    _home.render_home_runs(out, snapshot=snapshot)


def _supports_dashboard(out: IO[str]) -> bool:
    return _home.supports_dashboard(out)
