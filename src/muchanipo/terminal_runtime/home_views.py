from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, IO

from .runs import home_snapshot


def render_home(
    out: IO[str],
    *,
    runs_dir: Path | None = None,
    snapshot_loader: Callable[..., dict[str, Any]] = home_snapshot,
    runs_renderer: Callable[..., None] | None = None,
) -> None:
    snapshot = snapshot_loader(runs_dir=runs_dir)
    out.write("\nMuchanipo\n---------\n")
    out.write(f"Runs dir: {snapshot['runs_dir']}\n")
    out.write("Tip: type a topic directly to start research.\n\n")
    (runs_renderer or render_home_runs)(out, snapshot=snapshot)
    out.write("1. New research\n2. Demo run\n3. Runs\n4. CLI status\n")
    out.write("5. Reference readiness\n6. Autoresearch product guard\n")
    out.write("7. Operator orchestration\n8. JSON contracts\n9. Doctor\n10. Help\nq. Quit\n\n")
    out.flush()


def render_home_runs(out: IO[str], *, snapshot: dict[str, Any]) -> None:
    recent_runs = list(snapshot.get("recent_runs") or [])
    last_failure = snapshot.get("last_failure")
    if not recent_runs:
        out.write("Recent runs: none yet\n\n")
        return
    out.write("Recent runs\n")
    for index, item in enumerate(recent_runs, start=1):
        status = str(item.get("status") or "unknown")
        topic = truncate(str(item.get("topic") or "(untitled)"), 72)
        completed_at = str(item.get("completed_at") or "-")
        out.write(f"{index}. [{status}] {topic}\n")
        out.write(f"   run: {item.get('run_id', '-')} | completed: {completed_at}\n")
    if isinstance(last_failure, dict):
        topic = truncate(str(last_failure.get("topic") or "(untitled)"), 72)
        error_type = str(last_failure.get("error_type") or "Error")
        message = truncate(str(last_failure.get("message") or "no error message recorded"), 96)
        out.write("\nLast failure\n")
        out.write(f"[failed] {topic}\n   {error_type}: {message}\n")
        out.write(f"   run: {last_failure.get('run_id', '-')}\n")
    out.write("\n")


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def render_help(out: IO[str]) -> None:
    out.write("\nCommands\n--------\n")
    out.write("muchanipo                         open this terminal app\n")
    out.write("muchanipo demo                    run a deterministic offline demo\n")
    out.write('muchanipo "topic"                 start a dashboard run\n')
    out.write('muchanipo run "topic"             line-by-line run\n')
    out.write('muchanipo tui "topic"             dashboard run\n')
    out.write("muchanipo runs                    list previous runs\n")
    out.write("muchanipo status                  show local CLI provider status\n\n")
    out.write("muchanipo orchestrate             show tmux/smux operator status\n")
    out.write("muchanipo contracts               show CLI JSON contracts\n")
    out.write("muchanipo references              show reference runtime readiness\n")
    out.write("muchanipo guard                   run Autoresearch product/security guard\n")
    out.write("muchanipo doctor                  check local runtime readiness\n\n")
    out.write("Interactive slash commands\n")
    out.write("  /new, /run        start a new research run\n")
    out.write("  /demo             run the deterministic offline demo\n")
    out.write("  /runs, /history   list previous runs\n")
    out.write("  /status           show local CLI provider status\n")
    out.write("  /references       show reference runtime readiness\n")
    out.write("  /guard, /audit    run Autoresearch product/security guard\n")
    out.write("  /orchestrate      show tmux/smux operator status\n")
    out.write("  /contracts        show CLI JSON contracts\n")
    out.write("  /doctor           check local runtime readiness\n")
    out.write("  /help             show this help\n")
    out.write("  /clear, /home     redraw the home screen\n")
    out.write("  /exit, /quit, /q  exit Muchanipo\n\n")
    out.flush()


def supports_dashboard(out: IO[str]) -> bool:
    return bool(getattr(out, "isatty", lambda: False)())
