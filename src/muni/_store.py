"""Thread-safe local persistence primitives for MUNI stores."""
from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Callable, Mapping, TypeVar

from src.platform_contracts import canonical_json

_T = TypeVar("_T")
_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class PersistenceIntegrityError(RuntimeError):
    """Raised when persisted MUNI data violates its storage shape."""


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _lock(path: Path) -> threading.RLock:
    key = _resolved(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _temporary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.{os.getpid()}.{threading.get_ident()}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    return Path(name)


def _write_bytes_unlocked(path: Path, content: bytes) -> None:
    temporary = _temporary(path)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Atomically replace one file using a unique same-process temporary."""
    path = _resolved(path)
    with _lock(path):
        _write_bytes_unlocked(path, content)


def _read_array_unlocked(path: Path, *, require_objects: bool) -> list[object]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersistenceIntegrityError(f"invalid JSON persistence store: {path}") from exc
    if not isinstance(value, list):
        raise PersistenceIntegrityError(f"persistence store must contain an array: {path}")
    if require_objects:
        for index, item in enumerate(value):
            if not isinstance(item, Mapping):
                raise PersistenceIntegrityError(
                    f"persistence store {path} has non-object element at index {index}"
                )
    return value


def read_json_array(path: Path, *, require_objects: bool = False) -> list[object]:
    """Read one JSON array while rejecting malformed persisted elements."""
    path = _resolved(path)
    with _lock(path):
        return _read_array_unlocked(path, require_objects=require_objects)


def update_json_array(
    path: Path,
    update: Callable[[list[object]], _T],
    *,
    require_objects: bool = False,
) -> _T:
    """Run a synchronized canonical read-modify-write transaction."""
    path = _resolved(path)
    with _lock(path):
        records = _read_array_unlocked(path, require_objects=require_objects)
        result = update(records)
        _write_bytes_unlocked(path, canonical_json(records) + b"\n")
        return result


def append_json_records(
    path: Path, *records: object, require_objects: bool = False
) -> None:
    """Append records to a canonical JSON array in one transaction."""
    def append(existing: list[object]) -> None:
        existing.extend(records)

    update_json_array(path, append, require_objects=require_objects)


def atomic_write_pair(first: tuple[Path, bytes], second: tuple[Path, bytes]) -> None:
    """Publish two files together and restore their prior bytes on failure."""
    pairs = tuple((_resolved(path), content) for path, content in (first, second))
    if pairs[0][0] == pairs[1][0]:
        raise ValueError("paired artifact paths must be distinct")
    with ExitStack() as stack:
        for path in sorted((pairs[0][0], pairs[1][0]), key=str):
            stack.enter_context(_lock(path))
        prior = {path: path.read_bytes() if path.exists() else None for path, _ in pairs}
        staged: list[tuple[Path, Path]] = []
        try:
            for path, content in pairs:
                temporary = _temporary(path)
                temporary.write_bytes(content)
                staged.append((temporary, path))
            for temporary, path in staged:
                os.replace(temporary, path)
        except Exception:
            for path, _ in pairs:
                previous = prior[path]
                if previous is None:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    _write_bytes_unlocked(path, previous)
            raise
        finally:
            for temporary, _ in staged:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
