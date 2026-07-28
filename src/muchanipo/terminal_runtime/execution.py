from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, IO

_REQUIRED_ENV = (
    "MUCHANIPO_APP_RUN_ID",
    "MUCHANIPO_EXECUTION_GENERATION",
    "MUCHANIPO_EXECUTION_NONCE",
    "MUCHANIPO_OWNER_BOOT_ID",
    "MUCHANIPO_EXECUTABLE_DIGEST",
    "MUCHANIPO_EXECUTION_HANDSHAKE_PATH",
    "MUCHANIPO_EXECUTION_CANCEL_PATH",
)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    app_run_id: str
    generation: int
    launch_nonce: str
    owner_boot_id: str
    executable_digest: str
    handshake_path: Path
    cancel_path: Path
    finalizer_path: Path | None

    @classmethod
    def from_env(cls) -> ExecutionContext | None:
        present = {name: os.environ.get(name) for name in _REQUIRED_ENV}
        if not any(present.values()):
            return None
        missing = [name for name, value in present.items() if not value]
        if missing:
            raise RuntimeError(
                "execution generation contract is incomplete: " + ", ".join(missing)
            )
        generation = int(present["MUCHANIPO_EXECUTION_GENERATION"] or "0")
        if generation <= 0:
            raise RuntimeError("execution generation must be positive")
        expected_digest = str(present["MUCHANIPO_EXECUTABLE_DIGEST"])
        with Path(sys.executable).resolve().open("rb") as executable:
            actual_digest = hashlib.file_digest(executable, "sha256").hexdigest()
        if actual_digest != expected_digest:
            raise RuntimeError("execution executable digest does not match child interpreter")
        finalizer = os.environ.get("MUCHANIPO_EXECUTION_FINALIZER_PATH")
        return cls(
            app_run_id=str(present["MUCHANIPO_APP_RUN_ID"]),
            generation=generation,
            launch_nonce=str(present["MUCHANIPO_EXECUTION_NONCE"]),
            owner_boot_id=str(present["MUCHANIPO_OWNER_BOOT_ID"]),
            executable_digest=expected_digest,
            handshake_path=Path(str(present["MUCHANIPO_EXECUTION_HANDSHAKE_PATH"])),
            cancel_path=Path(str(present["MUCHANIPO_EXECUTION_CANCEL_PATH"])),
            finalizer_path=Path(finalizer) if finalizer else None,
        )

    def write_handshake(self) -> None:
        payload = {
            "pid": os.getpid(),
            "process_start_time": _process_start_time(os.getpid()),
            "pgid": os.getpgid(0),
            "launch_nonce": self.launch_nonce,
            "generation": self.generation,
            "owner_boot_id": self.owner_boot_id,
            "executable_digest": self.executable_digest,
        }
        _atomic_json(self.handshake_path, payload)

    def tag(self, event: dict[str, Any]) -> dict[str, Any]:
        return {**event, "generation": self.generation}

    def cancellation_requested(self) -> bool:
        if not self.cancel_path.exists():
            return False
        try:
            payload = json.loads(self.cancel_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return (
            payload.get("app_run_id") == self.app_run_id
            and payload.get("generation") == self.generation
            and payload.get("launch_nonce") == self.launch_nonce
        )

    def assert_terminal_available(self) -> None:
        if self.finalizer_path is not None and self.finalizer_path.exists():
            raise RuntimeError("terminal finalizer was already claimed")

    def claim_terminal(self, terminal_event: str) -> None:
        if self.finalizer_path is None:
            return
        self.finalizer_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.finalizer_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as error:
            raise RuntimeError("terminal finalizer was already claimed") from error
        with os.fdopen(descriptor, "w", encoding="utf-8") as marker:
            json.dump(
                {
                    "app_run_id": self.app_run_id,
                    "generation": self.generation,
                    "launch_nonce": self.launch_nonce,
                    "terminal_event": terminal_event,
                },
                marker,
                ensure_ascii=False,
            )
            marker.write("\n")
            marker.flush()
            os.fsync(marker.fileno())
        _fsync_directory(self.finalizer_path.parent)


class GenerationJSONLineWriter:
    def __init__(self, stream: IO[str], context: ExecutionContext) -> None:
        self.stream = stream
        self.context = context
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._write_line(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._write_line(self._buffer)
            self._buffer = ""
        self.stream.flush()

    def _write_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self.stream.write(line + "\n")
            return
        if isinstance(payload, dict) and isinstance(payload.get("event"), str):
            payload = self.context.tag(payload)
            self.stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        else:
            self.stream.write(line + "\n")


def current_generation() -> int | None:
    context = ExecutionContext.from_env()
    return context.generation if context else None


def _process_start_time(pid: int) -> str:
    result = subprocess.run(
        ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not value:
        raise RuntimeError("execution process start time was empty")
    return value


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
