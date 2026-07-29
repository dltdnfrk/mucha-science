from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

JSON_SCHEMA_VERSION: Final = 1
HOME_RECENT_RUN_LIMIT: Final = 3
HOME_FAILURE_SCAN_LIMIT: Final = 50
DEMO_TOPIC: Final = "저비용 분자진단 키트 시장성"

CLI_JSON_CONTRACTS_V1: Final[dict[str, dict[str, Any]]] = {
    "muchanipo doctor": {
        "schema_version": JSON_SCHEMA_VERSION,
        "description": "Local runtime readiness for the TUI-first CLI.",
        "required_top_level_keys": (
            "schema_version", "command", "ok", "status", "runs_dir",
            "checks", "cli_statuses", "recommendations",
        ),
        "compatibility": "Consumers may ignore additive fields; required keys are stable for schema_version 1.",
    },
    "muchanipo status": {
        "schema_version": JSON_SCHEMA_VERSION,
        "description": "Installed/version status for provider CLIs.",
        "required_top_level_keys": ("schema_version", "command", "providers"),
        "compatibility": "Consumers may ignore additive fields; required keys are stable for schema_version 1.",
    },
    "muchanipo runs": {
        "schema_version": JSON_SCHEMA_VERSION,
        "description": "Recent terminal run summaries loaded from summary.json artifacts.",
        "required_top_level_keys": ("schema_version", "command", "runs_dir", "limit", "runs"),
        "compatibility": "Consumers may ignore additive fields; required keys are stable for schema_version 1.",
    },
    "muchanipo references": {
        "schema_version": JSON_SCHEMA_VERSION,
        "description": "Reference-project implementation inventory and six-stage readiness.",
        "required_top_level_keys": (
            "schema_version", "command", "stages", "references", "gaps",
            "not_ready_references", "license_warnings",
        ),
        "compatibility": "Consumers may ignore additive fields; required keys are stable for schema_version 1.",
    },
    "muchanipo guard": {
        "schema_version": JSON_SCHEMA_VERSION,
        "description": "Autoresearch completion-artifact guard for local product review, verification, and security barriers.",
        "required_top_level_keys": (
            "schema_version", "command", "status", "passed", "summary",
            "autoresearch", "checks", "warnings", "blockers",
        ),
        "compatibility": "Consumers may ignore additive fields; required keys are stable for schema_version 1.",
    },
    "muchanipo orchestrate": {
        "schema_version": JSON_SCHEMA_VERSION,
        "description": "tmux/smux operator hub and worker-window orchestration status.",
        "required_top_level_keys": (
            "schema_version", "command", "session", "ok", "tmux_available",
            "plan", "windows", "panes", "operators", "warnings",
        ),
        "compatibility": "Consumers may ignore additive fields; required keys are stable for schema_version 1.",
    },
}

STAGE_LABELS: Final[dict[str, str]] = {
    "intake": "아이디어 접수",
    "interview": "인터뷰 / 요구사항 정리",
    "targeting": "목표 설정 / 연구 지도",
    "research": "자료 수집 / 자동 연구",
    "evidence": "근거 검증 / 지식 정리",
    "council": "Council / 다중 관점 토론",
    "report": "보고서 작성",
    "vault": "학습 축적 / Vault",
    "agents": "에이전트 기록",
    "finalize": "완료",
}
STAGE_ORDER: Final[tuple[str, ...]] = tuple(STAGE_LABELS)


@dataclass(frozen=True, slots=True)
class TerminalRunPaths:
    run_id: str
    run_dir: Path
    events_path: Path
    report_path: Path
    summary_path: Path


@dataclass(frozen=True, slots=True)
class TerminalRunResult:
    topic: str
    run_id: str
    report_path: Path
    events_path: Path
    summary_path: Path
    offline: bool | None
    stage_status: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InterviewCapture:
    original_topic: str
    pipeline_input: str
    mode: str
    answered: int
