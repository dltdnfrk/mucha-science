"""Creation and minimal local persistence for MUNI Study contracts."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import unicodedata

from src.muni._store import atomic_write_bytes
from src.muni_contracts import Study, TargetSelection
from src.packs_loader import load_pack
from src.platform_contracts import canonical_json

_TARGET_MAX_LENGTH = 256
_PURPOSE_MAX_LENGTH = 1024
_PROVENANCE_MAX_LENGTH = 1024
_STUDY_ID = re.compile(r"muni_study_[0-9a-f]{32}\Z")
_REGISTRY: dict[tuple[Path, str], Study] = {}


class StudyValidationError(ValueError):
    """Raised when a Study entrypoint value has an invalid format."""


def _normalize(value: str, field: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise StudyValidationError(f"{field} must be a string")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise StudyValidationError(f"{field} must not contain control characters")
    normalized = " ".join(value.split())
    if not normalized:
        raise StudyValidationError(f"{field} must be non-empty after stripping whitespace")
    if len(normalized) > max_length:
        raise StudyValidationError(f"{field} must be at most {max_length} characters")
    return normalized


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _pack_identity(pack_ref: str) -> str:
    handle = load_pack(pack_ref)
    return canonical_json(asdict(handle)).decode("utf-8")


def create_study(
    target_crop: str,
    target_pathogen: str,
    purpose: str,
    pack_ref: str | None = None,
) -> Study:
    """Create a Study from caller-selected targets without target lookup rules."""
    crop = _normalize(target_crop, "target_crop", max_length=_TARGET_MAX_LENGTH)
    pathogen = _normalize(target_pathogen, "target_pathogen", max_length=_TARGET_MAX_LENGTH)
    intent = _normalize(purpose, "purpose", max_length=_PURPOSE_MAX_LENGTH)
    loaded_pack_ref = _pack_identity(pack_ref) if pack_ref is not None else None
    return Study.from_content(
        {
            "target_crop": crop,
            "target_pathogen": pathogen,
            "purpose": intent,
            "created_at": _timestamp(),
            "pack_ref": loaded_pack_ref,
        }
    )


def create_target_selection(
    target_crop: str,
    target_pathogen: str,
    *,
    selected_by: str,
    note: str,
) -> TargetSelection:
    """Record the lab-supplied selection and its explicit provenance."""
    return TargetSelection(
        target_crop=_normalize(target_crop, "target_crop", max_length=_TARGET_MAX_LENGTH),
        target_pathogen=_normalize(
            target_pathogen, "target_pathogen", max_length=_TARGET_MAX_LENGTH
        ),
        selected_by=_normalize(
            selected_by, "selected_by", max_length=_PROVENANCE_MAX_LENGTH
        ),
        note=_normalize(note, "note", max_length=_PROVENANCE_MAX_LENGTH),
    )


def _root(root: str | Path | None) -> Path:
    configured = root if root is not None else os.environ.get("MUNI_DATA_ROOT", ".muni")
    return Path(configured).expanduser().resolve()


def _study_path(study_id: str, root: str | Path | None) -> tuple[Path, Path]:
    if not isinstance(study_id, str) or not _STUDY_ID.fullmatch(study_id):
        raise StudyValidationError("study_id must be a canonical MUNI Study identifier")
    registry_root = _root(root)
    return registry_root, registry_root / "studies" / f"{study_id}.json"


def save_study(study: Study, root: str | Path | None = None) -> Path:
    """Atomically save a Study under the configured registry root."""
    if not isinstance(study, Study):
        raise TypeError("study must be a Study")
    registry_root, path = _study_path(study.study_id, root)
    atomic_write_bytes(path, study.to_json() + b"\n")
    _REGISTRY[(registry_root, study.study_id)] = study
    return path


def load_study(study_id: str, root: str | Path | None = None) -> Study:
    """Load and validate a Study from the configured registry."""
    registry_root, path = _study_path(study_id, root)
    raw = path.read_bytes().strip()
    cached = _REGISTRY.get((registry_root, study_id))
    if cached is not None and cached.to_json() == raw:
        return cached
    study = Study.from_json(raw)
    _REGISTRY[(registry_root, study_id)] = study
    return study


def list_studies(root: str | Path | None = None) -> tuple[Study, ...]:
    """List validated Studies in stable identifier order."""
    registry_root = _root(root)
    directory = registry_root / "studies"
    if not directory.exists():
        return ()
    studies = [load_study(path.stem, root=registry_root) for path in directory.glob("*.json")]
    return tuple(sorted(studies, key=lambda study: study.study_id))
