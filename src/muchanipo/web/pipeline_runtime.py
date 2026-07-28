from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Lock, Thread
import time
import uuid

from src.muchanipo.terminal_runtime.artifacts import StagedArtifactOwner

from .pipeline_contract import (
    JsonObject,
    JsonValue,
    PipelineIdentity,
    PipelineRequestError,
    PipelineRun,
    PipelineRunStorage,
    load_terminal_run,
    next_generation,
    sanitize_environment,
    validate_launch,
)
from .pipeline_events import TERMINAL_EVENTS, parse_pipeline_event, runtime_status


_CANCELLED_EVENT_FILTER = frozenset({
    "done",
    "execution_cancelled",
    "final_report",
    "report_chunk",
    "terminal_run_done",
})


class PipelineRuntime:
    def __init__(self, data_root: Path, workspace_root: Path) -> None:
        self._data_root = data_root
        self._workspace_root = workspace_root
        self._runs: dict[str, PipelineRun] = {}
        self._lock = Lock()
        self._owner_boot_id = f"web-{uuid.uuid4().hex}"
        with Path(sys.executable).resolve().open("rb") as executable:
            self._executable_digest = hashlib.file_digest(executable, "sha256").hexdigest()

    def launch(
        self,
        *,
        run_id: str,
        topic: str,
        pipeline: str,
        depth: str,
        environment: Mapping[str, str],
    ) -> JsonObject:
        clean_topic = topic.strip()
        validate_launch(run_id, clean_topic, pipeline, depth)
        clean_environment = sanitize_environment(environment)
        with self._lock:
            existing = self._runs.get(run_id) or load_terminal_run(
                self._data_root,
                run_id,
            )
            if existing is not None:
                self._runs[run_id] = existing
                return existing.receipt()
            generation = next_generation(self._data_root, run_id)
            started_at = int(time.time() * 1000)
            identity = PipelineIdentity(
                run_id=run_id,
                generation=generation,
                launch_nonce=f"web-{uuid.uuid4().hex}",
                owner_boot_id=self._owner_boot_id,
                executable_digest=self._executable_digest,
            )
            owner = StagedArtifactOwner(
                run_id,
                generation,
                identity.launch_nonce,
                self._data_root,
            )
            owner.prepare()
            storage = PipelineRunStorage(owner)
            launch_receipt = self._launch_receipt(identity, started_at, None)
            storage.write_launch(launch_receipt)
            process_environment = os.environ.copy()
            process_environment.update(clean_environment)
            process_environment.update({
                "MUCHANIPO_APP_RUN_ID": run_id,
                "MUCHANIPO_EXECUTION_GENERATION": str(generation),
                "MUCHANIPO_EXECUTION_NONCE": identity.launch_nonce,
                "MUCHANIPO_OWNER_BOOT_ID": identity.owner_boot_id,
                "MUCHANIPO_EXECUTABLE_DIGEST": identity.executable_digest,
                "MUCHANIPO_EXECUTION_HANDSHAKE_PATH": str(storage.handshake_path),
                "MUCHANIPO_EXECUTION_CANCEL_PATH": str(storage.cancel_path),
                "MUCHANIPO_EXECUTION_FINALIZER_PATH": str(storage.finalizer_path),
                "MUCHANIPO_HOME": str(self._data_root),
            })
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    "-m",
                    "muchanipo",
                    "serve",
                    "--topic",
                    clean_topic,
                    "--pipeline",
                    pipeline,
                    "--depth",
                    depth,
                    "--report-path",
                    str(owner.staging_dir / "REPORT.md"),
                ],
                cwd=self._workspace_root,
                env=process_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            launch_receipt = self._launch_receipt(identity, started_at, process.pid)
            storage.write_launch(launch_receipt)
            run = PipelineRun(
                identity=identity,
                process=process,
                storage=storage,
                started_at_unix_ms=started_at,
                launch_receipt=launch_receipt,
            )
            self._runs[run_id] = run
        stdout_reader = Thread(target=self._read_stdout, args=(run,), daemon=True)
        stderr_reader = Thread(target=self._read_stderr, args=(run,), daemon=True)
        stdout_reader.start()
        stderr_reader.start()
        Thread(
            target=self._wait_for_process,
            args=(run, stdout_reader, stderr_reader),
            daemon=True,
        ).start()
        return run.receipt()

    def send_action(
        self,
        run_id: str,
        generation: int,
        action: Mapping[str, JsonValue],
    ) -> None:
        run = self._matching_run(run_id, generation)
        process = run.process
        if process is None:
            raise PipelineRequestError("run_not_interactive", "run input is no longer available")
        stdin = process.stdin
        if stdin is None or stdin.closed or process.poll() is not None:
            raise PipelineRequestError("run_not_interactive", "run input is no longer available")
        stdin.write(json.dumps(dict(action), ensure_ascii=False, separators=(",", ":")) + "\n")
        stdin.flush()

    def cancel(self, run_id: str, generation: int) -> JsonObject:
        run = self._matching_run(run_id, generation)
        process = run.process
        if process is None or run.reaped:
            return self._cancel_acknowledgement(run)
        with run.condition:
            if not run.cancellation_requested:
                run.cancellation_requested = True
                run.storage.write_cancel(run.identity)
                try:
                    os.killpg(process.pid, signal.SIGINT)
                    run.termination_kill_sent = True
                except ProcessLookupError:
                    pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._signal_process(run, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._signal_process(run, signal.SIGKILL)
                process.wait(timeout=2)
        with run.condition:
            observed = run.condition.wait_for(lambda: run.terminal, timeout=5)
            if not observed:
                raise RuntimeError("reaped pipeline termination was not durably recorded")
        return self._cancel_acknowledgement(run)

    def wait_for_events(
        self,
        run_id: str,
        after_sequence: int,
        timeout: float,
    ) -> tuple[list[JsonObject], bool]:
        run = self._run(run_id)
        with run.condition:
            pending = [
                event
                for event in run.events
                if isinstance(event.get("sequence"), int)
                and int(event["sequence"]) > after_sequence
            ]
            terminal_pending_reap = any(
                event.get("event") in TERMINAL_EVENTS for event in pending
            )
            if not run.terminal and (not pending or terminal_pending_reap):
                run.condition.wait_for(
                    lambda: run.terminal
                    or any(
                        isinstance(event.get("sequence"), int)
                        and int(event["sequence"]) > after_sequence
                        and event.get("event") not in TERMINAL_EVENTS
                        for event in run.events
                    ),
                    timeout=timeout,
                )
            events = [
                dict(event)
                for event in run.events
                if isinstance(event.get("sequence"), int)
                and int(event["sequence"]) > after_sequence
            ]
            return events, run.terminal

    def status(self) -> JsonObject:
        with self._lock:
            runs = tuple(run for run in self._runs.values() if run.process is not None)
        return runtime_status(runs, self._workspace_root)

    def shutdown(self) -> None:
        with self._lock:
            active = [
                (run.run_id, run.generation)
                for run in self._runs.values()
                if run.process is not None and not run.reaped
            ]
        for run_id, generation in active:
            self.cancel(run_id, generation)

    def _read_stdout(self, run: PipelineRun) -> None:
        process = run.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            event = parse_pipeline_event(line)
            with run.condition:
                event_name = event.get("event")
                if event_name == "execution_cancelled":
                    continue
                if run.cancellation_requested and event_name in _CANCELLED_EVENT_FILTER:
                    continue
                self._append_event_locked(run, event)

    def _read_stderr(self, run: PipelineRun) -> None:
        process = run.process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            clean_line = line.strip()
            if clean_line:
                with run.condition:
                    run.stderr_lines.append(clean_line)
                    del run.stderr_lines[:-20]

    def _wait_for_process(
        self,
        run: PipelineRun,
        stdout_reader: Thread,
        stderr_reader: Thread,
    ) -> None:
        process = run.process
        if process is None:
            return
        return_code = process.wait()
        stdout_reader.join(timeout=2)
        stderr_reader.join(timeout=2)
        cancelled = run.cancellation_requested or return_code == 130
        if cancelled:
            run.storage.owner.abort("cancelled", override_completed=True)
        with run.condition:
            run.reaped = True
            if cancelled:
                self._append_event_locked(run, {
                    "event": "execution_cancelled",
                    "termination_observed": True,
                    "reaped": True,
                })
                run.terminal_kind = "cancelled"
            else:
                has_terminal = any(
                    event.get("event") in TERMINAL_EVENTS for event in run.events
                )
                if not has_terminal:
                    detail = (
                        run.stderr_lines[-1]
                        if run.stderr_lines
                        else "pipeline exited without a terminal event"
                    )
                    self._append_event_locked(run, {
                        "event": "pipeline_error",
                        "message": detail,
                        "return_code": return_code,
                    })
                run.terminal_kind = (
                    "completed" if return_code == 0 and has_terminal else "failed"
                )
                if run.terminal_kind == "completed":
                    run.storage.owner.finalize("completed")
                else:
                    run.storage.owner.abort("failed", override_completed=True)
            run.terminal = True
            run.storage.write_terminal({
                "app_run_id": run.run_id,
                "generation": run.generation,
                "launch_nonce": run.identity.launch_nonce,
                "terminal_kind": run.terminal_kind,
                "termination_observed": True,
                "reaped": True,
                "termination_kill_sent": run.termination_kill_sent,
                "return_code": return_code,
            })
            run.condition.notify_all()

    def _append_event_locked(self, run: PipelineRun, event: JsonObject) -> None:
        durable_event = dict(event)
        durable_event["app_run_id"] = run.run_id
        durable_event["generation"] = run.generation
        durable_event["sequence"] = len(run.events)
        run.storage.write_event(durable_event)
        run.events.append(durable_event)
        run.condition.notify_all()

    def _signal_process(self, run: PipelineRun, sent_signal: signal.Signals) -> None:
        process = run.process
        if process is None:
            return
        try:
            os.killpg(process.pid, sent_signal)
            run.termination_kill_sent = True
        except ProcessLookupError:
            pass

    def _matching_run(self, run_id: str, generation: int) -> PipelineRun:
        run = self._run(run_id)
        if run.generation != generation:
            raise PipelineRequestError("stale_generation", "run generation does not match")
        return run

    def _run(self, run_id: str) -> PipelineRun:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                run = load_terminal_run(self._data_root, run_id)
                if run is not None:
                    self._runs[run_id] = run
        if run is None:
            raise PipelineRequestError("run_not_found", "run does not exist")
        return run

    @staticmethod
    def _launch_receipt(
        identity: PipelineIdentity,
        started_at: int,
        pid: int | None,
    ) -> JsonObject:
        return {
            "app_run_id": identity.run_id,
            "generation": identity.generation,
            "launch_nonce": identity.launch_nonce,
            "owner_boot_id": identity.owner_boot_id,
            "executable_path": sys.executable,
            "executable_digest": identity.executable_digest,
            "reserved_at_unix_ms": started_at,
            "identity": {
                "pid": pid,
                "process_start_time": str(started_at),
                "pgid": pid,
                "launch_nonce": identity.launch_nonce,
                "generation": identity.generation,
                "owner_boot_id": identity.owner_boot_id,
                "executable_digest": identity.executable_digest,
            },
        }

    @staticmethod
    def _cancel_acknowledgement(run: PipelineRun) -> JsonObject:
        return {
            "acknowledged": True,
            "app_run_id": run.run_id,
            "generation": run.generation,
            "termination_observed": run.reaped,
            "reaped": run.reaped,
            "kill_sent": run.termination_kill_sent,
        }
