from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, IO

from .contracts import DEMO_TOPIC, InterviewCapture
from .interview import read_prompt
from .runs import home_snapshot

RenderCommand = Callable[..., Any]
RunCommand = Callable[..., Any]
InterviewCommand = Callable[..., InterviewCapture]


@dataclass(frozen=True, slots=True)
class HomeActions:
    terminal_run: RunCommand
    conduct_interview: InterviewCommand
    render_runs: RenderCommand
    render_cli_status: RenderCommand
    render_references: RenderCommand
    render_guard: RenderCommand
    render_orchestration: RenderCommand
    render_json_contracts: RenderCommand
    render_doctor: RenderCommand


def terminal_app(
    actions: HomeActions,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> int:
    inp = stdin or sys.stdin
    out = stdout or sys.stdout
    render_home(out)
    while True:
        raw_choice = read_prompt(inp, out, "muchanipo> ")
        if raw_choice is None:
            return _exit(out)
        topic_or_choice = raw_choice.strip()
        choice = topic_or_choice.lower()
        if choice == "":
            render_home(out)
            continue
        command = normalize_home_command(choice)
        if command == "exit":
            return _exit(out)
        if command == "new":
            raw_topic = read_prompt(inp, out, "topic> ")
            if raw_topic is None:
                return _exit(out)
            topic = raw_topic.strip()
            if not topic:
                out.write("topic is required\n")
                out.flush()
                continue
            raw_mode = read_prompt(inp, out, "mode [auto/offline/online] (auto)> ")
            run_from_app(
                topic,
                actions=actions,
                inp=inp,
                out=out,
                offline=offline_from_mode((raw_mode or "").strip().lower()),
                interview=True,
                depth="deep",
            )
            render_home(out)
            continue
        if command == "demo":
            run_from_app(
                DEMO_TOPIC,
                actions=actions,
                inp=inp,
                out=out,
                offline=True,
                interview=False,
                depth="shallow",
            )
            render_home(out)
            continue
        render_action = {
            "runs": actions.render_runs,
            "status": actions.render_cli_status,
            "references": actions.render_references,
            "guard": actions.render_guard,
            "orchestrate": actions.render_orchestration,
            "contracts": actions.render_json_contracts,
            "doctor": actions.render_doctor,
        }.get(command or "")
        if render_action is not None:
            render_action(stdout=out)
            continue
        if command == "help":
            render_help(out)
            continue
        if command == "home":
            render_home(out)
            continue
        if choice.startswith("/"):
            out.write(f"unknown command: {topic_or_choice}\n")
            out.write("type /help for commands\n")
            out.flush()
            continue
        run_from_app(
            topic_or_choice,
            actions=actions,
            inp=inp,
            out=out,
            offline=None,
            interview=True,
            depth="deep",
        )
        render_home(out)


def run_from_app(
    topic: str,
    *,
    actions: HomeActions,
    inp: IO[str],
    out: IO[str],
    offline: bool | None,
    interview: bool,
    depth: str,
    require_live: bool = False,
) -> None:
    try:
        capture = actions.conduct_interview(topic, stdin=inp, stdout=out) if interview else None
        actions.terminal_run(
            topic,
            stdout=out,
            offline=offline,
            dashboard=supports_dashboard(out),
            pipeline_input=capture.pipeline_input if capture else None,
            require_live=require_live,
            depth=depth,
        )
    except KeyboardInterrupt:
        out.write("\nRun interrupted; returning to Muchanipo home.\n")
        out.flush()
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - interactive boundary returns users home.
        out.write(f"\nRun failed; returning to Muchanipo home: {type(exc).__name__}: {exc}\n")
    out.flush()


def normalize_home_command(choice: str) -> str | None:
    aliases = {
        "/q": "exit", "/quit": "exit", "/exit": "exit", "/bye": "exit",
        "q": "exit", "quit": "exit", "exit": "exit",
        "/new": "new", "/run": "new", "1": "new", "new": "new", "n": "new",
        "/demo": "demo", "2": "demo", "demo": "demo",
        "/runs": "runs", "/history": "runs", "3": "runs", "runs": "runs", "r": "runs",
        "/status": "status", "4": "status", "status": "status", "s": "status",
        "/references": "references", "/refs": "references", "5": "references",
        "references": "references", "refs": "references",
        "/guard": "guard", "/audit": "guard", "6": "guard", "guard": "guard", "audit": "guard",
        "/orchestrate": "orchestrate", "/orchestration": "orchestrate", "/ops": "orchestrate",
        "7": "orchestrate", "orchestrate": "orchestrate", "orchestration": "orchestrate", "ops": "orchestrate",
        "/contracts": "contracts", "8": "contracts", "contracts": "contracts",
        "/doctor": "doctor", "9": "doctor", "doctor": "doctor", "d": "doctor",
        "/help": "help", "/h": "help", "/?": "help", "10": "help",
        "help": "help", "h": "help", "?": "help",
        "/clear": "home", "/home": "home",
    }
    return aliases.get(choice)


def render_home(out: IO[str], *, runs_dir: Path | None = None) -> None:
    snapshot = home_snapshot(runs_dir=runs_dir)
    out.write("\nMuchanipo\n---------\n")
    out.write(f"Runs dir: {snapshot['runs_dir']}\n")
    out.write("Tip: type a topic directly to start research.\n\n")
    render_home_runs(out, snapshot=snapshot)
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


def offline_from_mode(mode: str) -> bool | None:
    if mode in {"offline", "off", "mock", "m"}:
        return True
    if mode in {"online", "live", "on", "l"}:
        return False
    return None


def supports_dashboard(out: IO[str]) -> bool:
    return bool(getattr(out, "isatty", lambda: False)())


def _exit(out: IO[str]) -> int:
    out.write("bye\n")
    out.flush()
    return 0
