from __future__ import annotations

import io
import json
from pathlib import Path
from queue import Queue
import signal
import subprocess
from threading import Event, Thread
from typing import Self

import pytest

from src.muchanipo.web.pipeline_runtime import PipelineRuntime


RUN_ID = "run-00000000-0000-4000-8000-000000000111"


class LineStream:
    def __init__(self) -> None:
        self._lines: Queue[str | None] = Queue()

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> str:
        line = self._lines.get()
        if line is None:
            raise StopIteration
        return line

    def emit(self, event: dict[str, str]) -> None:
        self._lines.put(json.dumps(event) + "\n")

    def close(self) -> None:
        self._lines.put(None)


class ControlledProcess:
    """Mutable fake process whose wait/reap boundary is test-controlled."""

    def __init__(self) -> None:
        self.pid = 41_111
        self.stdin = io.StringIO()
        self.stdout = LineStream()
        self.stderr = LineStream()
        self.returncode: int | None = None
        self.release_wait = Event()
        self.wait_returned = Event()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if not self.release_wait.wait(timeout):
            raise subprocess.TimeoutExpired("controlled-child", timeout)
        self.wait_returned.set()
        assert self.returncode is not None
        return self.returncode

    def finish(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout.close()
        self.stderr.close()
        self.release_wait.set()


@pytest.fixture
def controlled_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PipelineRuntime, ControlledProcess, dict[str, object], Path]:
    # Given a web runtime whose child wait boundary is externally controlled
    process = ControlledProcess()
    invocation: dict[str, object] = {}

    def popen(command: list[str], **options: object) -> ControlledProcess:
        invocation.update({"command": command, **options})
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    data_root = tmp_path / "web-runs"
    runtime = PipelineRuntime(data_root, tmp_path)
    runtime.launch(
        run_id=RUN_ID,
        topic="generation boundary",
        pipeline="stub",
        depth="shallow",
        environment={"MUCHANIPO_OFFLINE": "1"},
    )
    return runtime, process, invocation, data_root


def test_launch_uses_generation_ownership_environment_and_staged_report(
    controlled_launch: tuple[PipelineRuntime, ControlledProcess, dict[str, object], Path],
) -> None:
    # Given a newly launched generation
    _, process, invocation, data_root = controlled_launch

    # When the child command and environment are inspected
    command = invocation["command"]
    environment = invocation["env"]
    assert isinstance(command, list)
    assert isinstance(environment, dict)
    generation_root = data_root / "runs" / RUN_ID / "generation-1"

    # Then the complete ExecutionContext identity and staged path are supplied
    assert command[command.index("--report-path") + 1] == str(
        generation_root / "staging" / "REPORT.md"
    )
    assert environment["MUCHANIPO_APP_RUN_ID"] == RUN_ID
    assert environment["MUCHANIPO_EXECUTION_GENERATION"] == "1"
    assert environment["MUCHANIPO_EXECUTION_NONCE"]
    assert environment["MUCHANIPO_OWNER_BOOT_ID"]
    assert environment["MUCHANIPO_EXECUTABLE_DIGEST"]
    assert environment["MUCHANIPO_EXECUTION_HANDSHAKE_PATH"] == str(
        generation_root / "execution-handshake.json"
    )
    assert environment["MUCHANIPO_EXECUTION_CANCEL_PATH"] == str(
        generation_root / "execution-cancel.json"
    )
    assert environment["MUCHANIPO_EXECUTION_FINALIZER_PATH"] == str(
        generation_root / "execution-finalizer.json"
    )
    assert environment["MUCHANIPO_HOME"] == str(data_root)
    process.finish(0)


def test_cancel_receipt_has_identity_and_waits_for_reap(
    controlled_launch: tuple[PipelineRuntime, ControlledProcess, dict[str, object], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an active generation that does not exit immediately on SIGINT
    runtime, process, _, data_root = controlled_launch
    signal_sent = Event()
    monkeypatch.setattr(
        "src.muchanipo.web.pipeline_runtime.os.killpg",
        lambda _pid, sent_signal: signal_sent.set()
        if sent_signal == signal.SIGINT
        else None,
    )
    acknowledgement: list[dict[str, object]] = []

    # When cancellation is requested but the child has not crossed wait/reap
    cancel_thread = Thread(
        target=lambda: acknowledgement.append(runtime.cancel(RUN_ID, 1)),
        daemon=True,
    )
    cancel_thread.start()
    assert signal_sent.wait(timeout=2)
    marker = json.loads(
        (
            data_root
            / "runs"
            / RUN_ID
            / "generation-1"
            / "execution-cancel.json"
        ).read_text(encoding="utf-8")
    )
    events_before_reap, terminal_before_reap = runtime.wait_for_events(RUN_ID, -1, 0)

    # Then identity is durable, but termination is not reported prematurely
    assert marker["app_run_id"] == RUN_ID
    assert marker["generation"] == 1
    assert marker["launch_nonce"]
    assert acknowledgement == []
    assert events_before_reap == []
    assert terminal_before_reap is False

    process.finish(130)
    cancel_thread.join(timeout=2)
    assert process.wait_returned.is_set()
    assert acknowledgement[0]["termination_observed"] is True
    assert acknowledgement[0]["reaped"] is True


def test_cancel_filters_late_completion_and_removes_generation_artifacts(
    controlled_launch: tuple[PipelineRuntime, ControlledProcess, dict[str, object], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given cancellation ownership has been durably established
    runtime, process, _, data_root = controlled_launch
    signal_sent = Event()
    monkeypatch.setattr(
        "src.muchanipo.web.pipeline_runtime.os.killpg",
        lambda _pid, _signal: signal_sent.set(),
    )
    cancel_thread = Thread(target=lambda: runtime.cancel(RUN_ID, 1), daemon=True)
    cancel_thread.start()
    assert signal_sent.wait(timeout=2)
    generation_root = data_root / "runs" / RUN_ID / "generation-1"
    (generation_root / "staging").mkdir(parents=True, exist_ok=True)
    (generation_root / "staging" / "REPORT.md").write_text("# late staged\n")
    (generation_root / "final").mkdir(parents=True, exist_ok=True)
    (generation_root / "final" / "REPORT.md").write_text("# late final\n")

    # When the cancelled child emits late artifact and completion events
    process.stdout.emit({"event": "report_chunk", "markdown": "# late"})
    process.stdout.emit({"event": "final_report", "markdown": "# late"})
    process.stdout.emit({"event": "done", "status": "completed"})
    process.stdout.emit({"event": "terminal_run_done", "status": "completed"})
    process.finish(130)
    cancel_thread.join(timeout=2)
    events, terminal = runtime.wait_for_events(RUN_ID, -1, 2)

    # Then only reaped cancellation is terminal and no final artifact survives
    assert terminal is True
    assert [event["event"] for event in events] == ["execution_cancelled"]
    assert events[0]["termination_observed"] is True
    assert events[0]["reaped"] is True
    assert not (generation_root / "staging").exists()
    assert not (generation_root / "final").exists()
    artifact_receipt = json.loads(
        (generation_root / "run-receipt.json").read_text(encoding="utf-8")
    )
    assert artifact_receipt["terminal_reason"] == "cancelled"
    assert artifact_receipt["final_hash"] is None


def test_new_runtime_reuses_durable_launch_and_replays_terminal_events(
    controlled_launch: tuple[PipelineRuntime, ControlledProcess, dict[str, object], Path],
    tmp_path: Path,
) -> None:
    # Given a generation that emitted a terminal event and was reaped
    runtime, process, _, data_root = controlled_launch
    original_receipt = runtime.launch(
        run_id=RUN_ID,
        topic="ignored duplicate",
        pipeline="stub",
        depth="shallow",
        environment={},
    )
    process.stdout.emit({"event": "done", "status": "completed"})
    process.finish(0)
    events, terminal = runtime.wait_for_events(RUN_ID, -1, 2)
    assert terminal is True

    # When a new web runtime instance opens the same durable root
    restarted = PipelineRuntime(data_root, tmp_path)
    replayed, replay_terminal = restarted.wait_for_events(RUN_ID, -1, 0)
    reused_receipt = restarted.launch(
        run_id=RUN_ID,
        topic="must not relaunch",
        pipeline="stub",
        depth="shallow",
        environment={},
    )

    # Then the launch identity is reused and terminal events replay exactly
    assert replay_terminal is True
    assert replayed == events
    assert reused_receipt["launch_nonce"] == original_receipt["launch_nonce"]
    assert reused_receipt["generation"] == original_receipt["generation"]
