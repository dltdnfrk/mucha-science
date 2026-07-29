from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, IO

from .contracts import JSON_SCHEMA_VERSION
from .paths import default_runs_dir, repo_root
from .providers import cli_statuses, first_error_line


def doctor_report(
    *,
    runs_dir: Path | None = None,
    status_loader: Callable[[], list[dict[str, Any]]] = cli_statuses,
) -> dict[str, Any]:
    root = runs_dir or default_runs_dir()
    cli_records = status_loader()
    installed_clis = [item["name"] for item in cli_records if item.get("installed")]
    checks = [
        python_check(),
        entrypoint_check(),
        runs_dir_check(root),
        {
            "name": "provider_clis",
            "ok": bool(installed_clis),
            "severity": "warning",
            "detail": ", ".join(installed_clis) if installed_clis else "no provider CLIs found; offline mode remains available",
            "hint": "Install/login to claude, codex, gemini, kimi, or opencode for online runs.",
        },
        provider_probe_check(cli_records),
        execution_mode_check(cli_records),
    ]
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "command": "muchanipo doctor",
        "ok": all(item["ok"] or item["severity"] != "error" for item in checks),
        "status": overall_status(checks),
        "runs_dir": str(root),
        "checks": checks,
        "cli_statuses": cli_records,
        "recommendations": doctor_recommendations(checks),
    }


def render_doctor(
    *,
    stdout: IO[str] | None = None,
    runs_dir: Path | None = None,
    report_loader: Callable[..., dict[str, Any]] = doctor_report,
) -> dict[str, Any]:
    out = stdout or sys.stdout
    report = report_loader(runs_dir=runs_dir)
    out.write("\nDoctor\n------\n")
    out.write(f"Runs dir: {report['runs_dir']}\n")
    for item in report["checks"]:
        marker = "OK" if item["ok"] else "WARN" if item["severity"] == "warning" else "FAIL"
        out.write(f"[{marker}] {item['name']}: {item['detail']}\n")
        if not item["ok"] and item.get("hint"):
            out.write(f"       {item['hint']}\n")
    out.write("\n")
    out.flush()
    return report


def python_check() -> dict[str, Any]:
    ok = sys.version_info >= (3, 11)
    return {
        "name": "python",
        "ok": ok,
        "severity": "warning",
        "detail": sys.version.split()[0] if ok else f"{sys.version.split()[0]} works for tests; package target is 3.11+",
        "hint": "Use Python 3.11 or newer for packaged installs.",
    }


def entrypoint_check() -> dict[str, Any]:
    installed = shutil.which("muchanipo")
    local_script = repo_root() / "bin" / "muchanipo"
    ok = bool(installed or local_script.exists())
    detail = installed or (str(local_script) if local_script.exists() else "not found")
    return {
        "name": "entrypoint",
        "ok": ok,
        "severity": "warning",
        "detail": detail,
        "hint": "Install the package or run via bin/muchanipo / python3 -m muchanipo.",
    }


def provider_probe_check(records: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [
        f"{item['name']}: {item['error']}"
        for item in records
        if item.get("installed") and item.get("error")
    ]
    return {
        "name": "provider_probe",
        "ok": not failed,
        "severity": "warning",
        "detail": "; ".join(failed) if failed else "installed provider CLIs responded to version probes",
        "hint": "Run the affected provider CLI directly and complete login/setup.",
    }


def execution_mode_check(records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from src.muchanipo.server import _detect_offline_mode
    except ImportError:
        offline_default = True
    else:
        offline_default = _detect_offline_mode()
    installed = [item["name"] for item in records if item.get("installed")]
    api_envs = [
        key
        for key in (
            "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY",
            "GOOGLE_API_KEY", "OPENAI_API_KEY", "KIMI_API_KEY",
            "MOONSHOT_API_KEY", "XIAOMI_MIMO_API_KEY", "MIMO_API_KEY",
        )
        if os.environ.get(key)
    ]
    if offline_default:
        detail = "default mode is offline/mock; online runs need provider CLI or API setup"
    else:
        sources = installed or api_envs
        detail = "default mode is online-capable"
        if sources:
            detail += f" via {', '.join(sources)}"
    return {
        "name": "execution_mode",
        "ok": True,
        "severity": "info",
        "detail": detail,
        "hint": "Use --offline for deterministic mock runs or --online to require live providers.",
    }


def overall_status(checks: list[dict[str, Any]]) -> str:
    if any(not item["ok"] and item["severity"] == "error" for item in checks):
        return "fail"
    if any(not item["ok"] and item["severity"] == "warning" for item in checks):
        return "warning"
    return "ok"


def doctor_recommendations(checks: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("hint") or "")
        for item in checks
        if not item.get("ok") and item.get("hint")
    ]


def runs_dir_check(root: Path) -> dict[str, Any]:
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".muchanipo-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return {
            "name": "runs_dir",
            "ok": False,
            "severity": "error",
            "detail": f"{root} is not writable: {first_error_line(str(exc))}",
            "hint": "Set MUCHANIPO_RUNS_DIR to a writable directory.",
        }
    return {
        "name": "runs_dir",
        "ok": True,
        "severity": "error",
        "detail": f"{root} is writable",
        "hint": "",
    }
