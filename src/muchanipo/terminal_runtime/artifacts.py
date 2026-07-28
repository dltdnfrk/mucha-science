from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _tree_hash(directory: Path) -> str | None:
    if not directory.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(directory).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return "sha256:" + digest.hexdigest()


def _safe_component(value: str, *, field: str) -> str:
    if not value or any(
        not (character.isascii() and (character.isalnum() or character in "-_"))
        for character in value
    ):
        raise RuntimeError(f"{field} is not a safe path component")
    return value


@dataclass(frozen=True, slots=True)
class StagedArtifactOwner:
    app_run_id: str
    generation: int
    launch_nonce: str
    home: Path

    @property
    def run_root(self) -> Path:
        return self.home / "runs" / _safe_component(self.app_run_id, field="app_run_id")

    @property
    def generation_root(self) -> Path:
        return self.run_root / f"generation-{self.generation}"

    @property
    def staging_dir(self) -> Path:
        return self.generation_root / "staging"

    @property
    def final_dir(self) -> Path:
        return self.generation_root / "final"

    @property
    def receipt_path(self) -> Path:
        return self.generation_root / "run-receipt.json"

    @property
    def _active_path(self) -> Path:
        return self.run_root / "active-generation.json"

    @property
    def _lock_path(self) -> Path:
        return self.run_root / ".artifacts.lock"

    @contextlib.contextmanager
    def _lock(self) -> Iterator[None]:
        self.run_root.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def prepare(self) -> None:
        with self._lock():
            active = self._read_json(self._active_path)
            active_generation = int(active.get("generation", 0)) if active else 0
            if active_generation > self.generation:
                raise RuntimeError("execution generation is older than the active generation")
            if active_generation == self.generation and active:
                if active.get("launch_nonce") != self.launch_nonce:
                    raise RuntimeError("active generation launch nonce does not match")
            else:
                _atomic_json(
                    self._active_path,
                    {
                        "app_run_id": self.app_run_id,
                        "generation": self.generation,
                        "launch_nonce": self.launch_nonce,
                    },
                )
            receipt = self._read_json(self.receipt_path)
            if receipt and receipt.get("terminal_reason") == "completed":
                return
            self.generation_root.mkdir(parents=True, exist_ok=True)
            self.staging_dir.mkdir(parents=True, exist_ok=True)

    def stage_text(self, relative_path: str, content: str) -> Path:
        path = self._staging_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def assert_active(self) -> None:
        active = self._read_json(self._active_path)
        if (
            not active
            or active.get("app_run_id") != self.app_run_id
            or active.get("generation") != self.generation
            or active.get("launch_nonce") != self.launch_nonce
        ):
            raise RuntimeError("execution is not the active generation")

    def finalize(self, terminal_reason: str) -> dict[str, Any]:
        with self._lock():
            receipt = self._read_json(self.receipt_path)
            if receipt:
                return receipt
            self.assert_active()
            staging_hash = _tree_hash(self.staging_dir)
            if staging_hash is None:
                raise RuntimeError("staging directory is absent")
            if self.final_dir.exists():
                raise RuntimeError("final artifact directory already exists without a receipt")
            os.replace(self.staging_dir, self.final_dir)
            _fsync_directory(self.generation_root)
            final_hash = _tree_hash(self.final_dir)
            if final_hash != staging_hash:
                raise RuntimeError("atomic artifact promotion changed the staged tree hash")
            receipt = self._receipt(
                terminal_reason=terminal_reason,
                staging_hash=staging_hash,
                final_hash=final_hash,
            )
            _atomic_json(self.receipt_path, receipt)
            return receipt

    def abort(
        self,
        terminal_reason: str,
        *,
        override_completed: bool = False,
    ) -> dict[str, Any]:
        with self._lock():
            receipt = self._read_json(self.receipt_path)
            if receipt and not override_completed:
                return receipt
            staging_hash = _tree_hash(self.staging_dir)
            if staging_hash is None and receipt:
                prior_hash = receipt.get("staging_hash")
                staging_hash = prior_hash if isinstance(prior_hash, str) else None
            if self.staging_dir.exists():
                shutil.rmtree(self.staging_dir)
            if self.final_dir.exists():
                shutil.rmtree(self.final_dir)
            receipt = self._receipt(
                terminal_reason=terminal_reason,
                staging_hash=staging_hash,
                final_hash=None,
            )
            _atomic_json(self.receipt_path, receipt)
            return receipt

    def final_path(self, staging_path: Path) -> Path:
        return self.final_dir / staging_path.relative_to(self.staging_dir)

    def _staging_path(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("staged artifact path must remain inside staging")
        return self.staging_dir / relative

    def _receipt(
        self,
        *,
        terminal_reason: str,
        staging_hash: str | None,
        final_hash: str | None,
    ) -> dict[str, Any]:
        return {
            "schema": "muchanipo.run-receipt.v1",
            "app_run_id": self.app_run_id,
            "generation": self.generation,
            "launch_nonce": self.launch_nonce,
            "staging_hash": staging_hash,
            "final_hash": final_hash,
            "terminal_reason": terminal_reason,
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"invalid artifact owner record: {path}") from error
        if not isinstance(value, dict):
            raise RuntimeError(f"invalid artifact owner record: {path}")
        return value
