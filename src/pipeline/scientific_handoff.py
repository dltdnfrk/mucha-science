"""Deterministic export-only handoff packages for externally performed experiments.

This module only writes descriptions for an external party.  It does not
authorize, schedule, command, or execute computational or physical work.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import io
import os
from pathlib import Path
import shutil
import tempfile
from types import MappingProxyType
from typing import Any, Mapping
import zipfile

from .scientific_contracts import (
    ContractError,
    StageBoundary,
    actor_assertion_from_mapping,
    byte_digest,
    canonical_json,
    deterministic_id,
)


class HandoffError(ValueError):
    """An export-only handoff cannot be created from the supplied ledger."""


EXPORT_BOUNDARY = (
    "Muchanipo exports this package only. It does not authorize, schedule, "
    "command, or execute experiments; all computational and physical work is external."
)


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value


def _record(state: Mapping[str, Any], record_id: str, label: str) -> Mapping[str, Any]:
    record = state.get("records", {}).get(record_id)
    if not isinstance(record, Mapping) or not isinstance(record.get("content"), Mapping):
        raise HandoffError(f"current {label} record is absent")
    return record


def _current_export_inputs(state: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    current = state.get("current")
    if not isinstance(current, Mapping):
        raise HandoffError("ledger has no current references")
    landscape = _record(state, current.get("landscape"), "landscape")
    hypothesis = _record(state, current.get("hypothesis"), "hypothesis")
    proposal = _record(state, current.get("proposal"), "proposal")
    proposal_id = proposal["id"]
    local_x_id = current.get("local_x", {}).get(proposal_id) if isinstance(current.get("local_x"), Mapping) else None
    local_x = _record(state, local_x_id, "local X=not_run")
    content = local_x["content"]
    if content.get("stage") != "X" or content.get("status") != "not_run" or content.get("execution_kind") != "not_run":
        raise HandoffError("current proposal requires local X=not_run")
    return landscape, hypothesis, proposal, local_x


def _current_gates(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    requirements = state.get("requirements")
    dispositions = state.get("dispositions")
    if not isinstance(requirements, Mapping) or not isinstance(dispositions, Mapping):
        raise HandoffError("ledger has no current responsibility dispositions")
    gates: dict[str, dict[str, Any]] = {}
    for responsibility in (
        "safety_ethics_review",
        "execution_accountability",
        "question_selection",
    ):
        requirement_id = requirements.get(responsibility)
        disposition_id = dispositions.get(requirement_id)
        requirement = _record(state, requirement_id, f"{responsibility} requirement")
        disposition = _record(state, disposition_id, f"{responsibility} disposition")
        content = disposition["content"]
        if (requirement["content"].get("responsibility") != responsibility
                or content.get("responsibility") != responsibility
                or content.get("requirement_id") != requirement_id
                or content.get("status") != "satisfied"):
            raise HandoffError(f"current {responsibility} disposition is not satisfied")
        details = content.get("details")
        if not isinstance(details, Mapping):
            raise HandoffError(f"current {responsibility} disposition details are invalid")
        if responsibility == "safety_ethics_review":
            if details.get("export_only_boundary_confirmed") is not True:
                raise HandoffError("current safety_ethics_review disposition does not confirm export_only boundary")
        elif responsibility == "execution_accountability":
            try:
                _ = actor_assertion_from_mapping(details["handoff_owner"])
                execution_boundary = StageBoundary(
                    str(details["execution_boundary"]["kind"]),
                    str(details["execution_boundary"]["description"]),
                )
            except (KeyError, TypeError, ValueError, ContractError) as exc:
                raise HandoffError("current execution_accountability disposition lacks valid handoff semantics") from exc
            if execution_boundary.kind != "export_only":
                raise HandoffError("current execution_accountability disposition is not export_only")
        elif responsibility == "question_selection":
            if details.get("selected_normalized_question") != state.get("question"):
                raise HandoffError("current question_selection disposition does not select the cycle question")
        gates[responsibility] = {
            "requirement_id": requirement_id,
            "disposition_id": disposition_id,
            "content_hash": disposition["content_hash"],
            "actor": _plain(content.get("actor")),
            "details": _plain(details),
        }
    return gates


def _export_request(state: Mapping[str, Any], request: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate the immutable record selection bound into an export package."""
    if request is None or not request:
        return {}
    fields = {
        "expected_revision", "format", "artifact_ids", "report_body_id",
        "redaction_profile_id", "external_reference_ids",
    }
    if set(request) != fields or request.get("format") != "scientific-export.v1":
        raise HandoffError("export request fields are frozen")
    if request.get("expected_revision") != state.get("revision"):
        raise HandoffError("export request revision is stale")
    artifact_ids = request.get("artifact_ids")
    references = request.get("external_reference_ids")
    if (not isinstance(artifact_ids, list) or not isinstance(references, list)
            or not all(isinstance(value, str) for value in artifact_ids + references)
            or not isinstance(request.get("report_body_id"), (str, type(None)))
            or not isinstance(request.get("redaction_profile_id"), (str, type(None)))):
        raise HandoffError("export request record selection is invalid")
    records = state.get("records")
    selected_ids = [*artifact_ids, *references]
    if request["redaction_profile_id"] is not None:
        selected_ids.append(request["redaction_profile_id"])
    if not isinstance(records, Mapping) or any(value not in records for value in selected_ids):
        raise HandoffError("export request references an absent record")
    body_id = request["report_body_id"]
    if body_id is not None:
        body = _record(state, body_id, "report body")
        content = body["content"]
        body_utf8 = content.get("body_utf8")
        if (not isinstance(body_utf8, str)
                or content.get("body_hash") != byte_digest(body_utf8.encode("utf-8"))):
            raise HandoffError("export request names a mutable report body")
    return {
        "expected_revision": request["expected_revision"],
        "format": request["format"],
        "artifact_ids": list(artifact_ids),
        "report_body_id": body_id,
        "redaction_profile_id": request["redaction_profile_id"],
        "external_reference_ids": list(references),
    }
def _selected_export_records(
    state: Mapping[str, Any], request: Mapping[str, Any],
) -> list[dict[str, Any]]:
    record_ids = [
        *request.get("artifact_ids", []),
        *request.get("external_reference_ids", []),
    ]
    if request.get("redaction_profile_id") is not None:
        record_ids.append(request["redaction_profile_id"])
    if request.get("report_body_id") is not None:
        record_ids.append(request["report_body_id"])
    selected: list[dict[str, Any]] = []
    for record_id in record_ids:
        item = _record(state, record_id, "export-selected")
        selected.append({
            "id": item["id"],
            "content_hash": item["content_hash"],
            "content": _plain(item["content"]),
        })
    return selected

def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_fsynced(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _deterministic_archive(files: Mapping[str, bytes]) -> bytes:
    """Produce stable ZIP bytes without host timestamps, permissions, or ordering."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED, strict_timestamps=True) as archive:
        for name in sorted(files):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_STORED
            archive.writestr(entry, files[name])
    return out.getvalue()


def _redaction_profile(state: Mapping[str, Any], request: Mapping[str, Any]) -> Mapping[str, Any] | None:
    profile_id = request.get("redaction_profile_id")
    if profile_id is None:
        return None
    profile = _record(state, profile_id, "redaction profile")
    return {"record_id": profile["id"], "content_hash": profile["content_hash"]}


def _unverified_external_references(state: Mapping[str, Any], request: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"record_id": record["id"], "content_hash": record["content_hash"]}
        for record in (
            _record(state, record_id, "external reference")
            for record_id in sorted(request.get("external_reference_ids", []))
        )
    ]


def _archive_metadata(archive: bytes) -> dict[str, Any]:
    archive_hash = byte_digest(archive)
    return {
        "archive_blob_id": deterministic_id("blob", {"media_type": "application/zip", "sha256": archive_hash}),
        "archive_hash": archive_hash,
        "byte_length": len(archive),
    }

def create_export_package(
    state: Mapping[str, Any],
    export_root: str | Path,
    *,
    request: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Create one immutable, atomically published external handoff package.

    Existing packages are never altered.  A failure before the final directory
    rename leaves only an orphaned staging directory, never a visible package.
    """
    landscape, hypothesis, proposal, local_x = _current_export_inputs(state)
    gates = _current_gates(state)
    export_request = _export_request(state, request)
    selected_records = _selected_export_records(state, export_request)
    proposal_content = dict(proposal["content"])
    boundary = proposal_content.get("handoff_boundary")
    if not isinstance(boundary, Mapping) or boundary.get("kind") != "export_only":
        raise HandoffError("proposal must have an export_only handoff boundary")
    try:
        StageBoundary(str(boundary["kind"]), str(boundary["description"]))
    except (KeyError, ContractError) as exc:
        raise HandoffError("proposal handoff boundary is invalid") from exc

    claim_ids = proposal_content.get("claim_ids")
    if not isinstance(claim_ids, list) or not all(isinstance(claim_id, str) for claim_id in claim_ids):
        raise HandoffError("proposal must carry exact claim lineage")
    claims = []
    for claim_id in claim_ids:
        claim = _record(state, claim_id, "proposal claim")
        claims.append({"id": claim["id"], "content_hash": claim["content_hash"], "content": dict(claim["content"])})
    lineage = {
        "landscape": {"id": landscape["id"], "content_hash": landscape["content_hash"]},
        "hypothesis": {"id": hypothesis["id"], "content_hash": hypothesis["content_hash"]},
        "proposal": {"id": proposal["id"], "content_hash": proposal["content_hash"]},
        "claims": claims,
        "local_x": {"id": local_x["id"], "content_hash": local_x["content_hash"], "status": "not_run"},
    }
    package_inputs = {
        "cycle_id": state.get("cycle_id"),
        "export_request": export_request,
        "selected_records": selected_records,
        "boundary": {"kind": "export_only", "statement": EXPORT_BOUNDARY, "proposal_boundary": dict(boundary)},
        "proposal": proposal_content,
        "lineage": lineage,
        "risks": proposal_content.get("risks", []),
        "acceptance_criteria": proposal_content.get("acceptance_criteria", []),
        "ledger_gates": gates,
    }
    artifact_bytes = canonical_json({
        "proposal": proposal_content, "lineage": lineage,
        "boundary": package_inputs["boundary"], "export_request": export_request,
        "selected_records": selected_records,
    })
    manifest_content = {
        **package_inputs,
        "accountability": "Safety and execution accountability are derived only from current satisfied ledger dispositions.",
        "files": [{
            "relative_path": "handoff.json",
            "byte_length": len(artifact_bytes),
            "sha256": byte_digest(artifact_bytes),
            "source_record_id": proposal["id"],
            "source_record_hash": proposal["content_hash"],
            "redaction_profile": _redaction_profile(state, export_request),
            "unverified_external_references": _unverified_external_references(state, export_request),
        }],
    }
    manifest_bytes = canonical_json({
        "schema_version": "ai-scientist.handoff.v2",
        "manifest_content": manifest_content,
    })
    manifest_hash = byte_digest(manifest_bytes)
    export_id = deterministic_id("export", {"manifest_hash": manifest_hash})
    archive = _deterministic_archive({"handoff.json": artifact_bytes, "manifest.json": manifest_bytes})
    archive_metadata = _archive_metadata(archive)
    files = {"handoff.json": artifact_bytes, "manifest.json": manifest_bytes, "archive.zip": archive}
    root = Path(export_root)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise HandoffError("export root must be a real directory")
    final_path = root / export_id
    if final_path.exists():
        try:
            existing = get_export_package(root, export_id)
        except HandoffError as exc:
            raise HandoffError("existing export package conflicts with deterministic inputs") from exc
        if (existing["manifest_hash"] != manifest_hash
                or any(existing[key] != archive_metadata[key] for key in archive_metadata)):
            raise HandoffError("existing export package conflicts with deterministic inputs")
        return existing
    stage = Path(tempfile.mkdtemp(prefix=f".tmp-{export_id}-", dir=root))
    try:
        for name, data in files.items():
            _write_fsynced(stage / name, data)
        _fsync_directory(stage)
        try:
            os.rename(stage, final_path)
        except FileExistsError:
            try:
                existing = get_export_package(root, export_id)
            except HandoffError as exc:
                raise HandoffError("existing export package conflicts with deterministic inputs") from exc
            if (existing["manifest_hash"] != manifest_hash
                    or any(existing[key] != archive_metadata[key] for key in archive_metadata)):
                raise HandoffError("existing export package conflicts with deterministic inputs")
            return existing
        _fsync_directory(root)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return get_export_package(root, export_id)


def get_export_package(export_root: str | Path, package_id: str) -> Mapping[str, Any]:
    """Read and fully validate an already-published immutable package."""
    root = Path(export_root).resolve(strict=True)
    candidate = root / package_id
    if candidate.is_symlink():
        raise HandoffError("export package contains a symbolic link")
    package = candidate.resolve(strict=True)
    if package.parent != root or not package.is_dir():
        raise HandoffError("export package is outside the export root")
    paths = {name: package / name for name in ("manifest.json", "handoff.json", "archive.zip")}
    if any(path.is_symlink() for path in paths.values()):
        raise HandoffError("export package contains symbolic links")
    try:
        manifest_bytes = paths["manifest.json"].read_bytes()
        handoff = paths["handoff.json"].read_bytes()
        archive = paths["archive.zip"].read_bytes()
        from .scientific_contracts import decode_json_object
        decoded = decode_json_object(manifest_bytes)
        content = decoded.get("manifest_content")
        if (canonical_json(decoded) != manifest_bytes
                or decoded.get("schema_version") != "ai-scientist.handoff.v2"
                or not isinstance(content, Mapping)
                or deterministic_id("export", {"manifest_hash": byte_digest(manifest_bytes)}) != package_id):
            raise ValueError
        files = content.get("files")
        if not isinstance(files, list) or files != sorted(files, key=lambda item: item["relative_path"]):
            raise ValueError
        expected = {
            "relative_path": "handoff.json", "byte_length": len(handoff),
            "sha256": byte_digest(handoff),
        }
        if (len(files) != 1
                or any(files[0].get(key) != value for key, value in expected.items())
                or not isinstance(files[0].get("source_record_id"), str)
                or not isinstance(files[0].get("source_record_hash"), str)):
            raise ValueError
        with zipfile.ZipFile(io.BytesIO(archive), "r") as zipped:
            if zipped.namelist() != ["handoff.json", "manifest.json"]:
                raise ValueError
            if zipped.read("handoff.json") != handoff or zipped.read("manifest.json") != manifest_bytes:
                raise ValueError
        metadata = _archive_metadata(archive)
    except (ContractError, OSError, TypeError, ValueError, zipfile.BadZipFile) as exc:
        raise HandoffError("export package is invalid") from exc
    public_manifest = {"schema_version": decoded["schema_version"], **dict(content)}
    return MappingProxyType({
        "package_id": package_id, "path": str(package),
        "manifest": MappingProxyType(public_manifest),
        "manifest_hash": byte_digest(manifest_bytes), **metadata,
    })


class ScientificHandoff:
    """Small façade for command handlers; it deliberately has no execution API."""

    def __init__(self, export_root: str | Path):
        self._export_root = Path(export_root)

    def create(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        return create_export_package(state, self._export_root)

    def get(self, package_id: str) -> Mapping[str, Any]:
        return get_export_package(self._export_root, package_id)
