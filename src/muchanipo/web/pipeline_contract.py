from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
from threading import Condition

from src.muchanipo.terminal_runtime.artifacts import StagedArtifactOwner


JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]

RUN_ID_PATTERN = re.compile(
    r"^run(?:_[0-9a-f]{32}|-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
)
VALID_PIPELINES = frozenset({"full", "stub"})
VALID_DEPTHS = frozenset({"shallow", "deep", "max", "superdeep"})
DIRECT_ENVIRONMENT_KEYS = frozenset({
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MIMO_API_KEY",
    "MIMO_BASE_URL",
    "MIMO_MODEL",
    "OPENCODE_API_KEY",
    "OPENCODE_GO_API_KEY",
    "OPENCODE_USE_CLI",
    "PLANNOTATOR_API_KEY",
    "SEMANTIC_SCHOLAR_API_KEY",
    "UNPAYWALL_EMAIL",
    "XIAOMI_MIMO_API_KEY",
    "XIAOMI_MIMO_BASE_URL",
})


@dataclass(slots=True)
class PipelineRequestError(ValueError):
    code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class PipelineIdentity:
    run_id: str
    generation: int
    launch_nonce: str
    owner_boot_id: str
    executable_digest: str


@dataclass(frozen=True, slots=True)
class PipelineRunStorage:
    owner: StagedArtifactOwner

    @property
    def launch_path(self) -> Path:
        return self.owner.generation_root / "web-launch.json"

    @property
    def events_dir(self) -> Path:
        return self.owner.generation_root / "web-events"

    @property
    def terminal_path(self) -> Path:
        return self.owner.generation_root / "web-terminal.json"

    @property
    def handshake_path(self) -> Path:
        return self.owner.generation_root / "execution-handshake.json"

    @property
    def cancel_path(self) -> Path:
        return self.owner.generation_root / "execution-cancel.json"

    @property
    def finalizer_path(self) -> Path:
        return self.owner.generation_root / "execution-finalizer.json"

    def write_launch(self, receipt: JsonObject) -> None:
        _atomic_json(self.launch_path, receipt)

    def write_event(self, event: JsonObject) -> None:
        sequence = event.get("sequence")
        if not isinstance(sequence, int):
            raise RuntimeError("durable pipeline event requires an integer sequence")
        _atomic_json(self.events_dir / f"{sequence:020d}.json", event)

    def load_events(self) -> list[JsonObject]:
        if not self.events_dir.is_dir():
            return []
        return [_read_json(path) for path in sorted(self.events_dir.glob("*.json"))]

    def write_terminal(self, receipt: JsonObject) -> None:
        _atomic_json(self.terminal_path, receipt)

    def write_cancel(self, identity: PipelineIdentity) -> None:
        _atomic_json(
            self.cancel_path,
            {
                "app_run_id": identity.run_id,
                "generation": identity.generation,
                "launch_nonce": identity.launch_nonce,
                "owner_boot_id": identity.owner_boot_id,
                "executable_digest": identity.executable_digest,
            },
        )


@dataclass(slots=True)
class PipelineRun:
    """Mutable process record guarded by its condition and the runtime lock."""

    identity: PipelineIdentity
    process: subprocess.Popen[str] | None
    storage: PipelineRunStorage
    started_at_unix_ms: int
    launch_receipt: JsonObject
    condition: Condition = field(default_factory=Condition)
    events: list[JsonObject] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    terminal: bool = False
    reaped: bool = False
    cancellation_requested: bool = False
    termination_kill_sent: bool = False
    terminal_kind: str | None = None

    @property
    def run_id(self) -> str:
        return self.identity.run_id

    @property
    def generation(self) -> int:
        return self.identity.generation

    @property
    def report_path(self) -> Path:
        return self.storage.owner.staging_dir / "REPORT.md"

    def receipt(self) -> JsonObject:
        receipt = dict(self.launch_receipt)
        receipt.update({
            "phase": "terminal" if self.reaped else "running",
            "terminal_kind": self.terminal_kind,
            "termination_observed": self.reaped,
            "reaped": self.reaped,
            "termination_kill_sent": self.termination_kill_sent,
        })
        return receipt


def validate_launch(run_id: str, topic: str, pipeline: str, depth: str) -> None:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise PipelineRequestError("invalid_run_id", "run_id is invalid")
    if not topic or len(topic) > 20_000:
        raise PipelineRequestError("invalid_topic", "topic must contain 1 to 20000 characters")
    if pipeline not in VALID_PIPELINES:
        raise PipelineRequestError("invalid_pipeline", "pipeline must be full or stub")
    if depth not in VALID_DEPTHS:
        raise PipelineRequestError("invalid_depth", "research depth is invalid")


def sanitize_environment(environment: Mapping[str, str]) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for key, value in environment.items():
        allowed = key.startswith("MUCHANIPO_") or key in DIRECT_ENVIRONMENT_KEYS
        if not allowed or len(key) > 128 or len(value) > 32_768:
            raise PipelineRequestError(
                "invalid_environment",
                f"environment key is not allowed: {key}",
            )
        sanitized[key] = value
    return sanitized


def next_generation(data_root: Path, run_id: str) -> int:
    active_path = data_root / "runs" / run_id / "active-generation.json"
    if not active_path.exists():
        return 1
    active = _read_json(active_path)
    generation = active.get("generation")
    if not isinstance(generation, int) or generation < 1:
        raise RuntimeError("active generation receipt is invalid")
    return generation + 1


def load_terminal_run(data_root: Path, run_id: str) -> PipelineRun | None:
    active_path = data_root / "runs" / run_id / "active-generation.json"
    if not active_path.exists():
        return None
    active = _read_json(active_path)
    generation = active.get("generation")
    nonce = active.get("launch_nonce")
    if not isinstance(generation, int) or not isinstance(nonce, str):
        raise RuntimeError("active generation receipt is invalid")
    owner = StagedArtifactOwner(run_id, generation, nonce, data_root)
    storage = PipelineRunStorage(owner)
    if not storage.launch_path.exists() or not storage.terminal_path.exists():
        return None
    launch = _read_json(storage.launch_path)
    terminal = _read_json(storage.terminal_path)
    owner_boot_id = launch.get("owner_boot_id")
    executable_digest = launch.get("executable_digest")
    started_at = launch.get("reserved_at_unix_ms")
    if (
        not isinstance(owner_boot_id, str)
        or not isinstance(executable_digest, str)
        or not isinstance(started_at, int)
        or terminal.get("termination_observed") is not True
        or terminal.get("reaped") is not True
    ):
        raise RuntimeError("durable web terminal receipt is invalid")
    terminal_kind = terminal.get("terminal_kind")
    if not isinstance(terminal_kind, str):
        raise RuntimeError("durable web terminal kind is invalid")
    return PipelineRun(
        identity=PipelineIdentity(
            run_id,
            generation,
            nonce,
            owner_boot_id,
            executable_digest,
        ),
        process=None,
        storage=storage,
        started_at_unix_ms=started_at,
        launch_receipt=launch,
        events=storage.load_events(),
        terminal=True,
        reaped=True,
        termination_kill_sent=terminal.get("termination_kill_sent") is True,
        terminal_kind=terminal_kind,
    )


def _read_json(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid web runtime receipt: {path}") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RuntimeError(f"invalid web runtime receipt: {path}")
    return value


def _atomic_json(path: Path, payload: Mapping[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
