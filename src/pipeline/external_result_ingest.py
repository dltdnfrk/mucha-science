"""Fail-closed import of bytes from externally completed work.

This module neither fetches URLs nor executes input, controls equipment, or
adjudicates validation levels.  It copies pre-staged regular files only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .scientific_contracts import (
    ActorAssertion,
    ContractError,
    ExternalReference,
    Outcome,
    actor_assertion_from_mapping,
    byte_digest,
    canonical_json,
    content_record,
    deterministic_id,
    decode_json_object,
    external_reference_from_mapping,
)


class ExternalResultIngestError(ValueError):
    """External result bytes or their caller assertions violate the import boundary."""


@dataclass(frozen=True)
class ImportQuota:
    """Strict caller-configured byte and artifact limits."""

    max_files: int = 32
    max_file_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_files < 1 or self.max_file_bytes < 1 or self.max_total_bytes < self.max_file_bytes:
            raise ExternalResultIngestError("invalid import quota")


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or key in copied:
                raise ExternalResultIngestError("canonical objects require unique string keys")
            copied[key] = _plain(item)
        return copied
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value


def _immutable_metadata(value: Mapping[str, Any]) -> Mapping[str, Any]:
    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            copied: dict[str, Any] = {}
            for key, nested in item.items():
                if not isinstance(key, str) or key in copied:
                    raise ExternalResultIngestError("metadata requires unique string keys")
                copied[key] = freeze(nested)
            return MappingProxyType(copied)
        if isinstance(item, tuple | list):
            return tuple(freeze(nested) for nested in item)
        return item

    frozen = freeze(value)
    try:
        canonical_json(frozen)
    except ContractError as exc:
        raise ExternalResultIngestError("metadata is not canonical") from exc
    return frozen


def _approved_source(path: str | Path, approved_roots: Sequence[str | Path]) -> tuple[int, int]:
    supplied = Path(path)
    if ".." in supplied.parts:
        raise ExternalResultIngestError("staged artifact contains lexical parent traversal")
    raw = supplied.absolute()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    for configured_root in approved_roots:
        root = Path(configured_root).absolute()
        try:
            relative = raw.relative_to(root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        directory_fd: int | None = None
        source_fd: int | None = None
        try:
            directory_fd = os.open(root, flags | os.O_DIRECTORY)
            if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
                raise OSError("approved root is not a directory")
            for part in relative.parts[:-1]:
                next_fd = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            source_fd = os.open(relative.parts[-1], flags, dir_fd=directory_fd)
            source_stat = os.fstat(source_fd)
        except OSError:
            if source_fd is not None:
                try:
                    os.close(source_fd)
                except OSError:
                    pass
            continue
        finally:
            if directory_fd is not None:
                try:
                    os.close(directory_fd)
                except OSError:
                    pass
        if not stat.S_ISREG(source_stat.st_mode):
            os.close(source_fd)
            raise ExternalResultIngestError("staged artifact must be a regular file")
        return source_fd, source_stat.st_size
    raise ExternalResultIngestError("staged artifact is outside approved roots or contains symbolic links")


def _close_sources(candidates: Sequence[tuple[int, int, str]]) -> None:
    for source_fd, _, _ in candidates:
        try:
            os.close(source_fd)
        except OSError:
            pass


def _hash_source(source_fd: int, expected_size: int, max_bytes: int) -> str:
    source_stat = os.fstat(source_fd)
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size != expected_size or expected_size > max_bytes:
        raise ExternalResultIngestError("staged artifact changed or exceeds quota")
    digest = hashlib.sha256()
    copied = 0
    while chunk := os.read(source_fd, 1024 * 1024):
        copied += len(chunk)
        if copied > max_bytes:
            raise ExternalResultIngestError("staged artifact exceeds quota during hash")
        digest.update(chunk)
    if copied != expected_size:
        raise ExternalResultIngestError("staged artifact changed during hash")
    os.lseek(source_fd, 0, os.SEEK_SET)
    return "sha256:" + digest.hexdigest()


def _hash_and_copy(source_fd: int, destination: Path, expected_size: int, expected_hash: str, max_bytes: int) -> int:
    source_stat = os.fstat(source_fd)
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size != expected_size or expected_size > max_bytes:
        raise ExternalResultIngestError("staged artifact changed or exceeds quota")
    copied = 0
    copied_hash = hashlib.sha256()
    with destination.open("xb") as output:
        while chunk := os.read(source_fd, 1024 * 1024):
            copied += len(chunk)
            if copied > max_bytes:
                raise ExternalResultIngestError("staged artifact exceeds quota during copy")
            output.write(chunk)
            copied_hash.update(chunk)
        output.flush()
        os.fsync(output.fileno())
    destination_hash = "sha256:" + copied_hash.hexdigest()
    if copied != expected_size or destination_hash != expected_hash:
        raise ExternalResultIngestError("staged artifact changed during copy")
    return copied
def stage_external_result(
    *,
    staged_files: Sequence[str | Path],
    approved_roots: Sequence[str | Path],
    staging_root: str | Path,
    quota: ImportQuota = ImportQuota(),
) -> Mapping[str, Any]:
    """Admit local files into an immutable, content-addressed staging store.

    This is intentionally a local API.  Negotiated protocol payloads name only
    the returned batch ID, manifest digest, and ordered artifact digests.
    """
    if not staged_files or len(staged_files) > quota.max_files:
        raise ExternalResultIngestError("artifact count exceeds quota")
    candidates: list[tuple[int, int, str]] = []
    try:
        for path in staged_files:
            source_fd, size = _approved_source(path, approved_roots)
            candidates.append((source_fd, size, ""))
            if size > quota.max_file_bytes:
                raise ExternalResultIngestError("artifact bytes exceed quota")
            candidates[-1] = (source_fd, size, _hash_source(source_fd, size, quota.max_file_bytes))
        if sum(size for _, size, _ in candidates) > quota.max_total_bytes:
            raise ExternalResultIngestError("artifact bytes exceed quota")
        root = Path(staging_root)
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise ExternalResultIngestError("staging root must be a real directory")
        batch_id = deterministic_id(
            "external_artifacts",
            {"staging_schema": "ai-scientist.staged-artifacts.v1", "sources": [
                {"byte_size": size, "content_hash": content_hash}
                for _, size, content_hash in candidates
            ]},
        )
        final_dir = root / batch_id
        artifacts = [
            {
                "blob_id": deterministic_id(
                    "external_blob",
                    {"batch_id": batch_id, "ordinal": index, "content_hash": content_hash},
                ),
                "filename": f"{index:04d}.bin",
                "byte_size": size,
                "content_hash": content_hash,
            }
            for index, (_, size, content_hash) in enumerate(candidates)
        ]
        manifest = {
            "schema_version": "ai-scientist.staged-artifacts.v1",
            "batch_id": batch_id,
            "artifacts": artifacts,
        }
        manifest_bytes = canonical_json(manifest)
        if final_dir.exists():
            _verify_staged_batch(
                staging_root=root,
                batch_id=batch_id,
                manifest_hash=byte_digest(manifest_bytes),
                blob_ids=[item["blob_id"] for item in artifacts],
                artifact_digests=[item["content_hash"] for item in artifacts],
                quota=quota,
            )
        else:
            stage = Path(tempfile.mkdtemp(prefix=f".{batch_id}.", dir=root))
            try:
                for index, (source_fd, size, content_hash) in enumerate(candidates):
                    _hash_and_copy(
                        source_fd, stage / f"{index:04d}.bin", size, content_hash, quota.max_file_bytes
                    )
                with (stage / "manifest.json").open("xb") as output:
                    output.write(manifest_bytes)
                    output.flush()
                    os.fsync(output.fileno())
                directory_fd = os.open(stage, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                os.rename(stage, final_dir)
                directory_fd = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise
        return MappingProxyType({
            "staged_batch_id": batch_id,
            "staged_manifest_hash": byte_digest(manifest_bytes),
            "staged_blob_ids": tuple(item["blob_id"] for item in artifacts),
            "staged_artifact_digests": tuple(item["content_hash"] for item in artifacts),
        })
    finally:
        _close_sources(candidates)


def _verify_staged_batch(
    *,
    staging_root: str | Path,
    batch_id: str,
    manifest_hash: str,
    blob_ids: Sequence[str],
    artifact_digests: Sequence[str],
    quota: ImportQuota,
) -> tuple[Path, ...]:
    """Resolve a staged batch without trusting caller-selected filesystem paths."""
    if (not isinstance(batch_id, str) or not batch_id.startswith("external_artifacts_")
            or Path(batch_id).name != batch_id
            or not isinstance(manifest_hash, str)
            or not isinstance(blob_ids, (list, tuple)) or not blob_ids
            or not isinstance(artifact_digests, (list, tuple)) or not artifact_digests
            or len(blob_ids) != len(artifact_digests)):
        raise ExternalResultIngestError("unknown staged artifact batch")
    root = Path(staging_root)
    final_dir = root / batch_id
    try:
        if root.is_symlink() or final_dir.is_symlink() or not final_dir.is_dir():
            raise ValueError
        manifest_path = final_dir / "manifest.json"
        if manifest_path.is_symlink():
            raise ValueError
        manifest_bytes = manifest_path.read_bytes()
        from .scientific_contracts import decode_json_object
        manifest = decode_json_object(manifest_bytes)
        artifacts = manifest["artifacts"]
        if (byte_digest(manifest_bytes) != manifest_hash
                or canonical_json(manifest) != manifest_bytes
                or set(manifest) != {"schema_version", "batch_id", "artifacts"}
                or manifest["schema_version"] != "ai-scientist.staged-artifacts.v1"
                or manifest["batch_id"] != batch_id
                or len(artifacts) != len(artifact_digests)
                or len(artifacts) > quota.max_files):
            raise ValueError
        paths: list[Path] = []
        total = 0
        for index, (artifact, blob_id, content_hash) in enumerate(zip(artifacts, blob_ids, artifact_digests)):
            filename = f"{index:04d}.bin"
            if (set(artifact) != {"blob_id", "filename", "byte_size", "content_hash"}
                    or artifact["filename"] != filename
                    or artifact["blob_id"] != blob_id
                    or artifact["content_hash"] != content_hash
                    or not isinstance(artifact["byte_size"], int)
                    or artifact["byte_size"] < 0
                    or artifact["byte_size"] > quota.max_file_bytes):
                raise ValueError
            source_fd, size = _approved_source(final_dir / filename, [root])
            try:
                if size != artifact["byte_size"] or _hash_source(source_fd, size, quota.max_file_bytes) != content_hash:
                    raise ValueError
            finally:
                os.close(source_fd)
            total += size
            paths.append(final_dir / filename)
        if total > quota.max_total_bytes:
            raise ValueError
        return tuple(paths)
    except (OSError, KeyError, TypeError, ValueError, ContractError) as exc:
        raise ExternalResultIngestError("unknown or tampered staged artifact batch") from exc


def resolve_staged_external_result(
    *,
    staging_root: str | Path,
    staged_batch_id: str,
    staged_manifest_hash: str,
    staged_blob_ids: Sequence[str],
    staged_artifact_digests: Sequence[str],
    quota: ImportQuota = ImportQuota(),
) -> tuple[Path, ...]:
    """Return verified store-owned file paths for repository-only import plumbing."""
    return _verify_staged_batch(
        staging_root=staging_root,
        batch_id=staged_batch_id,
        manifest_hash=staged_manifest_hash,
        blob_ids=staged_blob_ids,
        artifact_digests=staged_artifact_digests,
        quota=quota,
    )
def resolve_staged_blob_ids(
    *,
    staging_root: str | Path,
    staged_blob_ids: Sequence[str],
    quota: ImportQuota = ImportQuota(),
) -> tuple[Path, ...]:
    """Resolve opaque blob IDs from the controlled staging root only."""
    if not isinstance(staged_blob_ids, (list, tuple)) or not staged_blob_ids:
        raise ExternalResultIngestError("staged blob IDs are required")
    root = Path(staging_root)
    try:
        if root.is_symlink() or not root.is_dir():
            raise ValueError
        wanted = tuple(staged_blob_ids)
        if len(set(wanted)) != len(wanted):
            raise ValueError
        matches: list[tuple[Path, list[dict[str, Any]]]] = []
        for batch in root.iterdir():
            if batch.is_symlink() or not batch.is_dir():
                continue
            manifest_path = batch / "manifest.json"
            if manifest_path.is_symlink():
                continue
            manifest = decode_json_object(manifest_path.read_bytes())
            artifacts = manifest.get("artifacts")
            if (
                set(manifest) == {"schema_version", "batch_id", "artifacts"}
                and manifest["schema_version"] == "ai-scientist.staged-artifacts.v1"
                and manifest["batch_id"] == batch.name
                and isinstance(artifacts, list)
                and {item.get("blob_id") for item in artifacts} == set(wanted)
            ):
                matches.append((batch, artifacts))
        if len(matches) != 1:
            raise ValueError
        batch, artifacts = matches[0]
        by_id = {item["blob_id"]: item for item in artifacts}
        ordered = [by_id[blob_id] for blob_id in wanted]
        _verify_staged_batch(
            staging_root=root,
            batch_id=batch.name,
            manifest_hash=byte_digest(canonical_json({
                "schema_version": "ai-scientist.staged-artifacts.v1",
                "batch_id": batch.name,
                "artifacts": artifacts,
            })),
            blob_ids=[item["blob_id"] for item in artifacts],
            artifact_digests=[item["content_hash"] for item in artifacts],
            quota=quota,
        )
        return tuple(batch / item["filename"] for item in ordered)
    except (OSError, KeyError, TypeError, ValueError, ContractError) as exc:
        raise ExternalResultIngestError("unknown or tampered staged blob IDs") from exc

def _assert_accountability(actor: ActorAssertion | Mapping[str, Any], reference: ExternalReference | Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        actor_data = actor_assertion_from_mapping(_plain(actor))
        reference_data = external_reference_from_mapping(_plain(reference))
    except (ContractError, KeyError, TypeError, ValueError) as exc:
        raise ExternalResultIngestError("accountability assertions must use canonical actor and external-reference contracts") from exc
    if actor_data["actor_kind"] != "human":
        raise ExternalResultIngestError("an explicit external accountable human assertion is required")
    return actor_data, reference_data
def _existing_batch(final_dir: Path, batch_id: str, proposal_id: str, proposal_hash: str, expected_artifacts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bytes]:
    try:
        manifest_path = final_dir / "manifest.json"
        if final_dir.is_symlink() or manifest_path.is_symlink():
            raise ValueError
        manifest_bytes = manifest_path.read_bytes()
        from .scientific_contracts import decode_json_object
        manifest = decode_json_object(manifest_bytes)
        artifacts = manifest["artifacts"]
        if (set(manifest) != {"schema_version", "batch_id", "proposal_id", "proposal_hash", "artifacts"}
                or canonical_json(manifest) != manifest_bytes
                or manifest.get("schema_version") != "ai-scientist.external-artifacts.v1"
                or manifest.get("batch_id") != batch_id
                or manifest.get("proposal_id") != proposal_id
                or manifest.get("proposal_hash") != proposal_hash
                or artifacts != expected_artifacts):
            raise ValueError
        for artifact in artifacts:
            filename = artifact["filename"]
            artifact_path = final_dir / filename
            if (set(artifact) != {"artifact_id", "filename", "byte_size", "content_hash"}
                    or Path(filename).name != filename
                    or artifact_path.is_symlink()
                    or artifact_path.stat().st_size != artifact["byte_size"]
                    or byte_digest(artifact_path.read_bytes()) != artifact["content_hash"]):
                raise ValueError
        return artifacts, manifest_bytes
    except (OSError, KeyError, TypeError, ValueError, ContractError) as exc:
        raise ExternalResultIngestError("existing artifact batch conflicts with deterministic import") from exc


def ingest_external_result(
    *,
    state: Mapping[str, Any],
    staged_files: Sequence[str | Path],
    approved_roots: Sequence[str | Path],
    artifact_root: str | Path,
    proposal_id: str,
    proposal_hash: str,
    execution_kind: str,
    accountable_party: ActorAssertion | Mapping[str, Any],
    accountability_reference: ExternalReference | Mapping[str, Any],
    outcome: Outcome | str,
    limitations: Sequence[str],
    metadata: Mapping[str, Any],
    supersedes_result_id: str | None = None,
    quota: ImportQuota = ImportQuota(),
    _created_batches: set[Path] | None = None,
) -> Mapping[str, Any]:
    """Copy staged external bytes and return a content-addressed result submission.

    The returned mapping has no validation-level field: V-level adjudication is
    a separate later action and is never inferred from result outcome.
    """
    if execution_kind not in {"computational", "physical"}:
        raise ExternalResultIngestError("external result must be computational or physical")
    if not staged_files or len(staged_files) > quota.max_files:
        raise ExternalResultIngestError("artifact count exceeds quota")
    current = state.get("current", {})
    records = state.get("records", {})
    if current.get("proposal") != proposal_id:
        raise ExternalResultIngestError("result must bind the current proposal")
    proposal = records.get(proposal_id, {})
    if proposal.get("content_hash") != proposal_hash:
        raise ExternalResultIngestError("result proposal hash does not match current proposal")
    if supersedes_result_id is not None:
        previous = records.get(supersedes_result_id)
        if (not isinstance(previous, Mapping)
                or previous.get("record_type") != "result"
                or previous.get("content", {}).get("proposal_id") != proposal_id):
            raise ExternalResultIngestError("supersedes_result_id must name a result for the current proposal")
    if not isinstance(metadata, Mapping):
        raise ExternalResultIngestError("metadata must be a canonical object")
    try:
        normalized_outcome = Outcome(outcome).value
        canonical_metadata_value = _plain(_immutable_metadata(metadata))
        canonical_metadata = canonical_json(canonical_metadata_value)
    except (ValueError, ContractError) as exc:
        raise ExternalResultIngestError("outcome or metadata is not canonical") from exc
    if normalized_outcome == Outcome.NOT_APPLICABLE.value or not limitations or not all(isinstance(item, str) and item for item in limitations):
        raise ExternalResultIngestError("outcome and nonempty limitations are required")
    actor, reference = _assert_accountability(accountable_party, accountability_reference)

    candidates: list[tuple[int, int, str]] = []
    try:
        for path in staged_files:
            source_fd, size = _approved_source(path, approved_roots)
            candidates.append((source_fd, size, ""))
            if size > quota.max_file_bytes:
                raise ExternalResultIngestError("artifact bytes exceed quota")
            content_hash = _hash_source(source_fd, size, quota.max_file_bytes)
            candidates[-1] = (source_fd, size, content_hash)
        if sum(size for _, size, _ in candidates) > quota.max_total_bytes:
            raise ExternalResultIngestError("artifact bytes exceed quota")
        root = Path(artifact_root)
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise ExternalResultIngestError("artifact root must be a real directory")
        batch_seed = {
            "proposal_id": proposal_id,
            "proposal_hash": proposal_hash,
            "execution_kind": execution_kind,
            "outcome": normalized_outcome,
            "limitations": list(limitations),
            "supersedes_result_id": supersedes_result_id,
            "sources": [
                {"byte_size": size, "content_hash": content_hash}
                for _, size, content_hash in candidates
            ],
            "metadata_hash": byte_digest(canonical_metadata),
        }
        batch_id = deterministic_id("external_artifacts", batch_seed)
        final_dir = root / batch_id
        artifact_refs = [
            {
                "artifact_id": deterministic_id(
                    "artifact",
                    {"batch_id": batch_id, "ordinal": index, "content_hash": content_hash},
                ),
                "filename": f"{index:04d}.bin",
                "byte_size": size,
                "content_hash": content_hash,
            }
            for index, (_, size, content_hash) in enumerate(candidates)
        ]
        payload = {
            "proposal_id": proposal_id,
            "proposal_hash": proposal_hash,
            "execution_kind": execution_kind,
            "boundary": {"kind": "external_completed_import", "description": "Bytes describe work completed externally; Muchanipo did not execute it."},
            "accountable_party": actor,
            "accountability_reference": reference,
            "outcome": normalized_outcome,
            "limitations": list(limitations),
            "metadata": canonical_metadata_value,
            "artifact_refs": artifact_refs,
            "supersedes_result_id": supersedes_result_id,
        }
        try:
            result = content_record("result", payload, {"cycle_id": state.get("cycle_id"), "proposal_id": proposal_id, "artifact_batch_id": batch_id})
        except ContractError as exc:
            raise ExternalResultIngestError("result payload is not canonical") from exc
        manifest_bytes: bytes
        if final_dir.exists():
            if any(
                _hash_source(source_fd, size, quota.max_file_bytes) != content_hash
                for source_fd, size, content_hash in candidates
            ):
                raise ExternalResultIngestError("existing artifact batch conflicts with deterministic import")
            artifact_refs, manifest_bytes = _existing_batch(
                final_dir, batch_id, proposal_id, proposal_hash, artifact_refs
            )
        else:
            stage = Path(tempfile.mkdtemp(prefix=f".{batch_id}.", dir=root))
            try:
                for index, (source_fd, size, content_hash) in enumerate(candidates):
                    target = stage / f"{index:04d}.bin"
                    copied = _hash_and_copy(
                        source_fd, target, size, content_hash, quota.max_file_bytes
                    )
                    if copied != artifact_refs[index]["byte_size"]:
                        raise ExternalResultIngestError("staged artifact changed during copy")
                manifest = {"schema_version": "ai-scientist.external-artifacts.v1", "batch_id": batch_id, "proposal_id": proposal_id, "proposal_hash": proposal_hash, "artifacts": artifact_refs}
                manifest_bytes = canonical_json(manifest)
                with (stage / "manifest.json").open("xb") as output:
                    output.write(manifest_bytes)
                    output.flush()
                    os.fsync(output.fileno())
                directory_fd = os.open(stage, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                os.rename(stage, final_dir)
                if _created_batches is not None:
                    _created_batches.add(final_dir)
                directory_fd = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise
    finally:
        _close_sources(candidates)
    return MappingProxyType({"result": MappingProxyType(result), "artifact_refs": tuple(MappingProxyType(item) for item in artifact_refs), "artifact_batch": MappingProxyType({"id": batch_id, "path": str(final_dir), "manifest_hash": byte_digest(manifest_bytes)})})


def ingest_staged_external_result(
    *,
    state: Mapping[str, Any],
    staged_files: Sequence[str | Path],
    approved_roots: Sequence[str | Path],
    artifact_root: str | Path,
    request: Mapping[str, Any],
    quota: ImportQuota = ImportQuota(),
    _created_batches: set[Path] | None = None,
) -> Mapping[str, Any]:
    """Materialize a validated wire handoff without adding wire-controlled paths."""
    imported = ingest_external_result(
        state=state, staged_files=staged_files, approved_roots=approved_roots,
        artifact_root=artifact_root, proposal_id=request["proposal_id"],
        proposal_hash=request["proposal_hash"], execution_kind=request["execution_kind"],
        accountable_party=request["accountable_party"],
        accountability_reference=request["external_references"][0],
        outcome=Outcome.INCONCLUSIVE, limitations=("external result handoff",),
        metadata={"result_manifest": request["result_manifest"]},
        supersedes_result_id=request["supersedes_result_id"], quota=quota,
        _created_batches=_created_batches,
    )
    artifact_refs = [dict(item) for item in imported["artifact_refs"]]
    content = {
        "proposal_id": request["proposal_id"], "proposal_hash": request["proposal_hash"],
        "execution_kind": request["execution_kind"],
        "boundary": {"kind": "external_completed_import", "description": "Bytes describe work completed externally; Muchanipo did not execute it."},
        "accountable_party": _plain(request["accountable_party"]),
        "performers": [_plain(item) for item in request["performers"]],
        "started_at": request["started_at"], "completed_at": request["completed_at"],
        "external_references": [_plain(item) for item in request["external_references"]],
        "staged_blob_ids": list(request["staged_blob_ids"]),
        "result_manifest": _plain(request["result_manifest"]),
        "deviations": _plain(request["deviations"]), "artifact_refs": artifact_refs,
        "supersedes_result_id": request["supersedes_result_id"],
    }
    result = content_record(
        "result", content,
        {"cycle_id": state.get("cycle_id"), "proposal_id": request["proposal_id"],
         "artifact_batch_id": imported["artifact_batch"]["id"]},
    )
    return MappingProxyType({
        "result": MappingProxyType(result),
        "artifact_refs": tuple(MappingProxyType(item) for item in artifact_refs),
        "artifact_batch": imported["artifact_batch"],
    })

class ExternalResultIngest:
    """Configured importer with no network, code-execution, or equipment APIs."""

    def __init__(self, approved_roots: Sequence[str | Path], artifact_root: str | Path, quota: ImportQuota = ImportQuota()):
        self._approved_roots = tuple(approved_roots)
        self._artifact_root = Path(artifact_root)
        self._quota = quota
        self._created_batches: set[Path] = set()

    def cleanup_created_batch(self, verified: Mapping[str, Any]) -> None:
        """Remove only a batch this importer created for a rejected submission."""
        try:
            batch_path = Path(verified["artifact_batch"]["path"])
        except (KeyError, TypeError):
            return
        if batch_path not in self._created_batches:
            return
        self._created_batches.remove(batch_path)
        if batch_path.parent != self._artifact_root or batch_path.is_symlink():
            return
        shutil.rmtree(batch_path)

    def ingest(self, **kwargs: Any) -> Mapping[str, Any]:
        created: set[Path] = set()
        result = ingest_external_result(approved_roots=self._approved_roots, artifact_root=self._artifact_root, quota=self._quota, _created_batches=created, **kwargs)
        self._created_batches = created
        return result
    def ingest_staged(self, **kwargs: Any) -> Mapping[str, Any]:
        created: set[Path] = set()
        result = ingest_staged_external_result(
            approved_roots=self._approved_roots, artifact_root=self._artifact_root,
            quota=self._quota, _created_batches=created, **kwargs,
        )
        self._created_batches = created
        return result
