from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, IO

from .contracts import HOME_FAILURE_SCAN_LIMIT, HOME_RECENT_RUN_LIMIT, JSON_SCHEMA_VERSION
from .paths import default_runs_dir


def list_runs(*, runs_dir: Path | None = None, limit: int = 10) -> list[dict[str, Any]]:
    root = runs_dir or default_runs_dir()
    if not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for summary_path in root.glob("*/summary.json"):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(summary, dict):
            summary.setdefault("run_dir", str(summary_path.parent))
            records.append(summary)
    records.sort(
        key=lambda item: str(item.get("completed_at") or item.get("run_id") or ""),
        reverse=True,
    )
    return records[:limit]


def runs_report(
    *,
    runs_dir: Path | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    root = runs_dir or default_runs_dir()
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
    root = runs_dir or default_runs_dir()
    safe_recent_limit = max(1, recent_limit)
    safe_scan_limit = max(safe_recent_limit, failure_scan_limit)
    scanned_runs = list_runs(runs_dir=root, limit=safe_scan_limit)
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "command": "muchanipo home",
        "runs_dir": str(root),
        "recent_runs": scanned_runs[:safe_recent_limit],
        "last_failure": first_failed_run(scanned_runs),
    }


def render_runs(
    *,
    stdout: IO[str] | None = None,
    runs_dir: Path | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    out = stdout or sys.stdout
    records = list_runs(runs_dir=runs_dir, limit=limit)
    out.write("\nRuns\n")
    out.write("----\n")
    if not records:
        out.write("No runs yet.\n\n")
        out.flush()
        return records
    for index, item in enumerate(records, start=1):
        out.write(f"{index}. {item.get('topic', '(untitled)')}\n")
        out.write(f"   run: {item.get('run_id', '-')}\n")
        out.write(f"   report: {item.get('report_path', '-')}\n")
    out.write("\n")
    out.flush()
    return records


def first_failed_run(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in records:
        if str(item.get("status") or "").lower() == "failed":
            return item
    return None
