"""Fail-closed loading and discovery for content-addressed domain packs."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Mapping

from src.pipeline.scientific_contracts import ContractError, canonical_json, decode_json_object
from src.platform_contracts import LicenseDecision, SourceRecord

_MANIFEST_FIELDS = {
    "name",
    "semver",
    "schema_version",
    "title",
    "license",
    "references",
    "files",
}
_LICENSE_FIELDS = {"expression", "terms_uri", "decision", "restrictions"}
_FILE_FIELDS = {"path", "sha256"}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)


class PackLoadError(ValueError):
    """Base class for a pack that cannot be safely activated."""


class ManifestValidationError(PackLoadError):
    """Raised when ``pack.json`` does not conform to the frozen schema."""


class IntegrityError(PackLoadError):
    """Raised when declared pack content is missing or has changed."""


class LicenseActivationError(PackLoadError):
    """Raised when policy does not permit activation of a pack's license."""


@dataclass(frozen=True)
class PackHandle:
    """The content-addressed identity callers record in provenance."""

    name: str
    version: str
    manifest_sha256: str
    restricted: bool


def _object(value: object, fields: set[str], name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ManifestValidationError(f"{name} must be an object")
    if set(value) != fields:
        raise ManifestValidationError(f"{name} must contain exactly {sorted(fields)}")
    return value


def _string(value: object, name: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value:
        suffix = " or null" if nullable else ""
        raise ManifestValidationError(f"{name} must be a nonempty string{suffix}")
    return value


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ManifestValidationError(f"{name} must be an array")
    return value


def _validate_manifest(value: object) -> tuple[Mapping[str, object], LicenseDecision]:
    manifest = _object(value, _MANIFEST_FIELDS, "manifest")
    _string(manifest["name"], "name")
    version = _string(manifest["semver"], "semver")
    if version is None or not _SEMVER.fullmatch(version):
        raise ManifestValidationError("semver must be a valid semantic version")
    if manifest["schema_version"] != "1":
        raise ManifestValidationError("unsupported schema_version")
    _string(manifest["title"], "title")

    license_data = _object(manifest["license"], _LICENSE_FIELDS, "license")
    _string(license_data["expression"], "license.expression")
    _string(license_data["terms_uri"], "license.terms_uri", nullable=True)
    try:
        decision = LicenseDecision(license_data["decision"])
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError("license.decision must be a LicenseDecision") from exc
    restrictions = _array(license_data["restrictions"], "license.restrictions")
    for restriction in restrictions:
        _string(restriction, "license.restrictions item")

    references = _array(manifest["references"], "references")
    for index, reference in enumerate(references):
        if not isinstance(reference, Mapping):
            raise ManifestValidationError(f"references[{index}] must be a SourceRecord")
        try:
            SourceRecord.from_payload(reference)
        except (ContractError, TypeError, ValueError) as exc:
            raise ManifestValidationError(f"references[{index}] must be a valid SourceRecord") from exc

    files = _array(manifest["files"], "files")
    if not files:
        raise ManifestValidationError("files must be nonempty")
    seen_paths: set[str] = set()
    for index, item in enumerate(files):
        file_data = _object(item, _FILE_FIELDS, f"files[{index}]")
        path = _string(file_data["path"], f"files[{index}].path")
        digest = _string(file_data["sha256"], f"files[{index}].sha256")
        if path is None or not _safe_relative_path(path):
            raise ManifestValidationError(f"files[{index}].path must be a safe relative POSIX path")
        if path == "pack.json":
            raise ManifestValidationError("pack.json cannot list itself as pack content")
        if path in seen_paths:
            raise ManifestValidationError(f"duplicate file path: {path}")
        seen_paths.add(path)
        if digest is None or not _DIGEST.fullmatch(digest):
            raise ManifestValidationError(f"files[{index}].sha256 must be a sha256 digest")
    return manifest, decision


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        "\\" not in value
        and not path.is_absolute()
        and value not in {"", "."}
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return "sha256:" + hasher.hexdigest()


def _verify_files(pack_dir: Path, manifest: Mapping[str, object]) -> None:
    root = pack_dir.resolve()
    files = manifest["files"]
    assert isinstance(files, list)
    for item in files:
        assert isinstance(item, Mapping)
        relative = item["path"]
        expected = item["sha256"]
        assert isinstance(relative, str) and isinstance(expected, str)
        candidate = pack_dir / relative
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise IntegrityError(f"pack file is missing or outside the pack: {relative}") from exc
        if not resolved.is_file():
            raise IntegrityError(f"pack content is not a regular file: {relative}")
        if _file_digest(resolved) != expected:
            raise IntegrityError(f"sha256 mismatch for pack file: {relative}")


def load_pack(pack_dir: str | Path, *, allow_restricted: bool = False) -> PackHandle:
    """Validate and activate one pack directory under the supplied license policy."""
    directory = Path(pack_dir)
    manifest_path = directory / "pack.json"
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise ManifestValidationError(f"cannot read manifest: {manifest_path}") from exc
    try:
        decoded = decode_json_object(raw)
        manifest, decision = _validate_manifest(decoded)
        manifest_bytes = canonical_json(manifest)
    except ManifestValidationError:
        raise
    except (ContractError, TypeError, ValueError) as exc:
        raise ManifestValidationError("pack.json is not valid canonicalizable JSON") from exc

    if decision in {LicenseDecision.UNKNOWN, LicenseDecision.DENIED}:
        raise LicenseActivationError(f"license decision {decision.value} refuses activation")
    if decision is LicenseDecision.RESTRICTED and not allow_restricted:
        raise LicenseActivationError("license decision RESTRICTED requires explicit override")

    _verify_files(directory, manifest)
    return PackHandle(
        name=str(manifest["name"]),
        version=str(manifest["semver"]),
        manifest_sha256="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        restricted=decision is LicenseDecision.RESTRICTED,
    )


def discover_packs(root: str | Path) -> tuple[Path, ...]:
    """Return immediate child directories containing ``pack.json``, sorted by name."""
    directory = Path(root)
    try:
        children = tuple(directory.iterdir())
    except OSError as exc:
        raise PackLoadError(f"cannot scan packs root: {directory}") from exc
    return tuple(sorted(
        (child for child in children if child.is_dir() and (child / "pack.json").is_file()),
        key=lambda path: path.name,
    ))


__all__ = [
    "IntegrityError",
    "LicenseActivationError",
    "ManifestValidationError",
    "PackHandle",
    "PackLoadError",
    "discover_packs",
    "load_pack",
]
