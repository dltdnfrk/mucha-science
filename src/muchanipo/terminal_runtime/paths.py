from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .contracts import TerminalRunPaths


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_runs_dir() -> Path:
    default = Path.home() / ".local" / "share" / "muchanipo" / "runs"
    return Path(os.environ.get("MUCHANIPO_RUNS_DIR", default))


def new_run_id(topic: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = "".join(char.lower() if char.isalnum() else "-" for char in topic).strip("-")
    slug = "-".join(part for part in slug.split("-") if part)[:48] or "run"
    return f"{timestamp}-{slug}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_paths(
    *,
    topic: str,
    run_dir: Path | None,
    report_path: Path | None,
) -> TerminalRunPaths:
    run_id = new_run_id(topic)
    base = run_dir or default_runs_dir() / run_id
    report = report_path or base / "REPORT.md"
    return TerminalRunPaths(
        run_id=run_id,
        run_dir=base,
        events_path=base / "events.jsonl",
        report_path=report,
        summary_path=base / "summary.json",
    )
