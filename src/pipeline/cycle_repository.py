"""Crash-recoverable append-only storage for scientific cycle reductions."""
from __future__ import annotations

import base64
import binascii
import contextlib
import fcntl
import html
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterator, Mapping

from .scientific_contracts import GENESIS_HASH, ContractError, canonical_id_array, canonical_json, command_digest, content_record, decode_json_object, deterministic_id, event_frame_hash, byte_digest, digest, normalize_question, validate_protocol_action
from .scientific_cycle import CycleError, Reduction, ScientificCycleReducer, initial_state
from .scientific_handoff import create_export_package, get_export_package
from src.runtime.paths import get_muchanipo_home
from .external_result_ingest import (
    ExternalResultIngest,
    ExternalResultIngestError,
    ImportQuota,
    resolve_staged_blob_ids,
)


class RepositoryError(RuntimeError): pass
class RepositoryCorrupt(RepositoryError): pass
class IdempotencyConflict(RepositoryError): pass
class RevisionConflict(RepositoryError): pass
class CommitOutcomeUnknown(RepositoryError): pass
class AckMismatch(RepositoryError): pass
class CursorMismatch(RepositoryError): pass
class ExportTooLarge(RepositoryError): pass


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _line(value: Mapping[str, Any]) -> bytes: return canonical_json(value) + b"\n"


class CycleRepository:
    """File-backed repository.  The ledger is authority; snapshots are disposable."""
    def __init__(self, home: Path | str | None = None, *, reducer: ScientificCycleReducer | None = None) -> None:
        self.home = Path(home) if home is not None else get_muchanipo_home()
        self.root = self.home / "cycles"; self.reducer = reducer or ScientificCycleReducer()
        self._snapshot_repair_needed: set[str] = set()

    @contextlib.contextmanager
    def _lock(self, path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def start_cycle(self, command: Mapping[str, Any]) -> bytes:
        self._validate_mutation(command, "cycle.start")
        payload = command["payload"]
        key = command["idempotency_key"]
        creation_key = payload["creation_idempotency_key"]
        if not isinstance(key, str) or not key or not isinstance(creation_key, str) or not creation_key or creation_key != key:
            raise CycleError("start requires matching nonempty idempotency keys")
        raw_question = payload["raw_question"]
        normalized = normalize_question(raw_question)
        command_hash = command_digest("cycle.start", None, key, payload)
        with self._lock(self.root / ".lock"):
            registry = self.root / "registry" / (digest({"key": key})[7:] + ".json")
            cycle_id = deterministic_id("cycle", {"normalized_question": normalized, "creation_idempotency_key": key})
            directory = self.root / cycle_id
            if registry.exists():
                return self._creation_registry_response(registry, key, cycle_id, command_hash)
            if directory.exists() or directory.is_symlink():
                directory = self._existing_cycle_directory(cycle_id)
                with self._lock(directory / ".lock"):
                    state = self._load_locked(directory)
                    receipt = self._genesis_receipt(state, key)
                    if receipt is None or receipt["command_digest"] != command_hash:
                        raise RepositoryCorrupt("cycle genesis conflicts with creation registry")
                    response = self._receipt_response(receipt)
            else:
                state = initial_state(cycle_id, raw_question, payload["contract_version"], payload["boundary"], payload["creator"])
                response = self._response(cycle_id, 1, 1, command, {"cycle_id": cycle_id})
                event = {"protocol": "muchanipo", "protocol_version": "ai-scientist.v1", "kind": "event", "name": "cycle.started", "message_id": deterministic_id("event", {"cycle_id": cycle_id, "sequence": 1}), "cycle_id": cycle_id, "correlation_id": command["message_id"], "causation_id": command["message_id"], "sequence": 1, "revision": 1, "idempotency_key": key, "timestamp": command["timestamp"], "payload": {"normalized_question": normalized, "contract_version": payload["contract_version"], "created_records": list(state["records"]), "superseded_record_ids": [], "derived_current_refs": {}}, "extensions": self._frozen_action(command)}
                self._commit_new(directory, state, event, key, command_hash, response)
            directory = self._existing_cycle_directory(cycle_id)
            with self._lock(directory / ".lock"):
                receipt = self._genesis_receipt(self._load_locked(directory), key)
            if receipt is None:
                raise RepositoryCorrupt("cycle lacks creation receipt")
            record = {"registry_schema": "ai-scientist.creation-registry.v1", "creation_idempotency_key": key, "command_digest": command_hash, "cycle_id": cycle_id, "receipt_id": receipt["receipt_id"], "response_bytes_digest": byte_digest(response), "response_envelope_base64": base64.b64encode(response).decode("ascii")}
            self._atomic_json(registry, record)
            return response

    def execute(self, command: Mapping[str, Any]) -> bytes:
        self._validate_mutation(command)
        cycle_id = command["cycle_id"]
        payload = command["payload"]
        key = command["idempotency_key"]
        if not isinstance(cycle_id, str) or not isinstance(payload, Mapping) or not isinstance(key, str) or not key:
            raise CycleError("cycle command requires cycle_id, payload, and idempotency key")
        directory = self._existing_cycle_directory(cycle_id)
        with self._lock(directory / ".lock"):
            state = self._load_locked(directory)
            command_hash = command_digest(command["name"], cycle_id, key, payload)
            receipt = self._receipt(state, key)
            if receipt:
                if receipt["command_digest"] != command_hash: raise IdempotencyConflict("same key has different content")
                return self._receipt_response(receipt)
            if payload.get("expected_revision") != state["revision"]: raise RevisionConflict("expected revision is stale")
            reduction = self.reducer.apply(state, command)
            revision = state["revision"] + 1; sequence = state["sequence"] + 1
            response = self._response(cycle_id, sequence, revision, command, self._result_with_gates(reduction))
            event = {"protocol": "muchanipo", "protocol_version": "ai-scientist.v1", "kind": "event", "name": reduction.event_name, "message_id": deterministic_id("event", {"cycle_id": cycle_id, "sequence": sequence}), "cycle_id": cycle_id, "correlation_id": command["message_id"], "causation_id": command["message_id"], "sequence": sequence, "revision": revision, "idempotency_key": key, "timestamp": command["timestamp"], "payload": reduction.event_payload, "extensions": self._frozen_action(command)}
            self._commit(directory, reduction.state, event, key, command_hash, response)
            return response
    def submit_external_result(
        self,
        command: Mapping[str, Any],
        *,
        staging_root: str | Path,
        quota: ImportQuota,
    ) -> bytes:
        """Atomically bind a verified staged-blob import to the cycle ledger."""
        self._validate_mutation(command, "result.submit")
        cycle_id = command["cycle_id"]
        payload = command["payload"]
        request = payload
        key = command["idempotency_key"]
        if not isinstance(cycle_id, str) or not isinstance(payload, Mapping) or not isinstance(key, str) or not key:
            raise CycleError("result.submit requires a controlled staged handoff and idempotency key")
        directory = self._existing_cycle_directory(cycle_id)
        with self._lock(directory / ".lock"):
            state = self._load_locked(directory)
            command_hash = command_digest("result.submit", cycle_id, key, payload)
            receipt = self._receipt(state, key)
            if receipt:
                if receipt["command_digest"] != command_hash:
                    raise IdempotencyConflict("same key has different content")
                return self._receipt_response(receipt)
            if request.get("expected_revision") != state["revision"]:
                raise RevisionConflict("expected revision is stale")
            resolved_files = resolve_staged_blob_ids(
                staging_root=staging_root,
                staged_blob_ids=request["staged_blob_ids"],
                quota=quota,
            )
            importer = ExternalResultIngest(
                (staging_root,),
                directory / "external_artifacts",
                quota,
            )
            verified = importer.ingest_staged(
                state=state,
                staged_files=resolved_files,
                request=request,
            )
            try:
                self._verify_external_result_receipt(directory, state, verified)
                reduction = self.reducer.apply_verified_result(state, verified["result"])
            except Exception:
                importer.cleanup_created_batch(verified)
                raise
            sequence = state["sequence"] + 1
            revision = state["revision"] + 1
            response = self._response(cycle_id, sequence, revision, command, self._result_with_gates(reduction))
            event = {
                "protocol": "muchanipo", "protocol_version": "ai-scientist.v1",
                "kind": "event", "name": reduction.event_name,
                "message_id": deterministic_id("event", {"cycle_id": cycle_id, "sequence": sequence}),
                "cycle_id": cycle_id, "correlation_id": command["message_id"],
                "causation_id": command["message_id"], "sequence": sequence,
                "revision": revision, "idempotency_key": key,
                "timestamp": command["timestamp"],
                "payload": reduction.event_payload,
                "extensions": self._frozen_action(command, verified_result=verified["result"]),
            }
            self._commit(directory, reduction.state, event, key, command_hash, response)
            return response

    @staticmethod
    def _verify_external_result_receipt(
        directory: Path, state: Mapping[str, Any], verified: Mapping[str, Any],
    ) -> None:
        try:
            result = verified["result"]
            artifact_refs = list(verified["artifact_refs"])
            batch = verified["artifact_batch"]
            if set(verified) != {"result", "artifact_refs", "artifact_batch"}:
                raise ValueError
            batch_id = batch["id"]
            batch_path = directory / "external_artifacts" / batch_id
            if Path(batch["path"]) != batch_path or batch_path.is_symlink():
                raise ValueError
            manifest_bytes = (batch_path / "manifest.json").read_bytes()
            manifest = decode_json_object(manifest_bytes)
            if (byte_digest(manifest_bytes) != batch["manifest_hash"]
                    or canonical_json(manifest) != manifest_bytes
                    or manifest.get("batch_id") != batch_id
                    or manifest.get("proposal_id") != result["content"]["proposal_id"]
                    or manifest.get("proposal_hash") != result["content"]["proposal_hash"]
                    or manifest.get("artifacts") != artifact_refs
                    or result["content"].get("artifact_refs") != artifact_refs):
                raise ValueError
            expected = content_record(
                "result", result["content"],
                {"cycle_id": state["cycle_id"], "proposal_id": result["content"]["proposal_id"],
                 "artifact_batch_id": batch_id},
            )
            if dict(result) != expected:
                raise ValueError
            for artifact in artifact_refs:
                artifact_path = batch_path / artifact["filename"]
                if (artifact_path.is_symlink()
                        or byte_digest(artifact_path.read_bytes()) != artifact["content_hash"]
                        or artifact_path.stat().st_size != artifact["byte_size"]):
                    raise ValueError
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ExternalResultIngestError("external import receipt verification failed") from exc
    def create_export(self, command: Mapping[str, Any]) -> bytes:
        self._validate_mutation(command, "export.create")
        cycle_id = command["cycle_id"]
        key = command["idempotency_key"]
        if not isinstance(cycle_id, str) or not isinstance(key, str) or not key:
            raise CycleError("export.create requires cycle_id and idempotency key")
        directory = self._existing_cycle_directory(cycle_id)
        with self._lock(directory / ".lock"):
            state = self._load_locked(directory)
            command_hash = command_digest("export.create", cycle_id, key, command["payload"])
            receipt = self._receipt(state, key)
            if receipt:
                if receipt["command_digest"] != command_hash:
                    raise IdempotencyConflict("same key has different content")
                return self._receipt_response(receipt)
            if command["payload"].get("expected_revision", command.get("revision")) != state["revision"]:
                raise RevisionConflict("expected revision is stale")
            reduction = self.reducer.apply(state, command)
            package = create_export_package(reduction.state, directory / "exports", request=command["payload"])
            result = {**self._export_result(package), "gates": {"export_ready": self.reducer.export_ready(reduction.state)}}
            sequence = state["sequence"] + 1
            revision = state["revision"] + 1
            response = self._response(cycle_id, sequence, revision, command, result)
            event = {
                "protocol": "muchanipo", "protocol_version": "ai-scientist.v1",
                "kind": "event", "name": reduction.event_name,
                "message_id": deterministic_id("event", {"cycle_id": cycle_id, "sequence": sequence}),
                "cycle_id": cycle_id, "correlation_id": command["message_id"],
                "causation_id": command["message_id"], "sequence": sequence,
                "revision": revision, "idempotency_key": key,
                "timestamp": command["timestamp"],
                "payload": {
                    **reduction.event_payload,
                    "export_id": result["export_id"],
                    "manifest_hash": result["manifest_hash"],
                    "archive_blob_id": result["archive_blob_id"],
                    "archive_hash": result["archive_hash"],
                    "byte_length": result["byte_length"],
                },
                "extensions": self._frozen_action(command),
            }
            self._commit(directory, reduction.state, event, key, command_hash, response)
            return response

    def get_export(
        self,
        export_id: str,
        *,
        include_archive_bytes: bool,
    ) -> dict[str, Any]:
        if not isinstance(export_id, str):
            raise FileNotFoundError("committed export")
        for directory in self.root.iterdir() if self.root.exists() else ():
            if not directory.is_dir() or directory.is_symlink() or not directory.name.startswith("cycle_"):
                continue
            with self._lock(directory / ".lock"):
                state, _ = self._replay(directory, repair=False)
                for event in reversed(state["_events"]):
                    if event.get("name") != "export.created" or event.get("payload", {}).get("export_id") != export_id:
                        continue
                    package = get_export_package(directory / "exports", export_id)
                    if (
                        package["package_id"] != export_id
                        or any(
                            package[field] != event["payload"].get(field)
                            for field in ("manifest_hash", "archive_blob_id", "archive_hash", "byte_length")
                        )
                    ):
                        raise RepositoryCorrupt("committed export does not match published package")
                    archive_base64 = None
                    if include_archive_bytes:
                        if package["byte_length"] > 16 * 1024 * 1024:
                            raise ExportTooLarge("requested export archive exceeds 16 MiB")
                        archive = (directory / "exports" / export_id / "archive.zip").read_bytes()
                        if len(archive) != package["byte_length"] or byte_digest(archive) != package["archive_hash"]:
                            raise RepositoryCorrupt("committed export archive does not match published package")
                        archive_base64 = base64.b64encode(archive).decode("ascii")
                    return {
                        "export_id": export_id,
                        "manifest": dict(package["manifest"]),
                        "archive_hash": package["archive_hash"],
                        "byte_length": package["byte_length"],
                        "archive_base64": archive_base64,
                    }
        raise FileNotFoundError("committed export")

    def render_report(
        self,
        cycle_id: str,
        *,
        at_revision: int,
        format: str,
        include_status_overlay: bool,
    ) -> dict[str, Any]:
        directory = self._existing_cycle_directory(cycle_id)
        with self._lock(directory / ".lock"):
            state, _ = self._replay(directory, repair=False)
            if at_revision != state["revision"]:
                raise RevisionConflict("requested report revision is stale")
            current = state.get("current", {})
            stage_id = current.get("final_report") or current.get("interim_report")
            stage = state.get("records", {}).get(stage_id)
            body_id = stage.get("content", {}).get("report_body_id") if isinstance(stage, Mapping) else None
            body = state.get("records", {}).get(body_id)
            content = body.get("content") if isinstance(body, Mapping) else None
            if not isinstance(content, Mapping) or not isinstance(content.get("body_utf8"), str):
                raise CycleError("current immutable report body is absent")
            body_utf8 = content["body_utf8"]
            body_hash = content.get("body_hash")
            if body_hash != byte_digest(body_utf8.encode("utf-8")):
                raise RepositoryCorrupt("current report body hash mismatch")
            if format == "markdown":
                rendered: str | dict[str, Any] = body_utf8
            elif format == "canonical_json":
                rendered = {
                    "cycle_id": cycle_id,
                    "at_revision": at_revision,
                    "report_body_id": body_id,
                    "body_utf8": body_utf8,
                    "body_hash": body_hash,
                }
            elif format == "html":
                rendered = "<!doctype html><html><body><pre>" + html.escape(body_utf8) + "</pre></body></html>"
            else:
                raise CycleError("unsupported report format")
            overlay = None
            if include_status_overlay:
                overlay = {
                    "terminal": state.get("terminal"),
                    "sequence": state["sequence"],
                    "revision": state["revision"],
                    "event_hash": state["_event_hash"],
                }
            return {
                "cycle_id": cycle_id,
                "at_revision": at_revision,
                "format": format,
                "body_utf8_or_json": rendered,
                "body_hash": body_hash,
                "status_overlay": overlay,
            }

    def state_snapshot(self, cycle_id: str) -> dict[str, Any]:
        """Return a verified immutable-state projection and its exact checkpoint."""
        directory = self._existing_cycle_directory(cycle_id)
        with self._lock(directory / ".lock"):
            state, _ = self._replay(directory, repair=False)
            return self._snapshot_payload(state)

    def verified_replay(
        self, cycle_id: str, *, cursor: Mapping[str, Any], max_events: int,
    ) -> dict[str, Any]:
        """Read only the verified ledger suffix named by an exact cursor."""
        if not isinstance(max_events, int) or isinstance(max_events, bool) or not 1 <= max_events <= 128:
            raise CycleError("max_events must be between 1 and 128")
        directory = self._existing_cycle_directory(cycle_id)
        with self._lock(directory / ".lock"):
            state, events = self._replay(directory, repair=False)
            if cursor.get("cycle_id") != cycle_id:
                raise CycleError("cursor cycle_id does not match requested cycle")
            sequence = cursor.get("sequence")
            event_hash = cursor.get("event_hash")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
                raise CycleError("invalid cursor sequence")
            if sequence > state["sequence"]:
                raise RevisionConflict("cursor is ahead of the ledger")
            expected_hash = GENESIS_HASH if sequence == 0 else digest(events[sequence - 1])
            if event_hash != expected_hash:
                raise CursorMismatch("cursor hash does not match the ledger")
            page = events[sequence:sequence + max_events]
            to_sequence = sequence + len(page)
            to_hash = GENESIS_HASH if to_sequence == 0 else digest(events[to_sequence - 1])
            return {
                "from_cursor": dict(cursor),
                "to_cursor": {"cycle_id": cycle_id, "sequence": to_sequence, "event_hash": to_hash},
                "events": page,
                "has_more": to_sequence < state["sequence"],
                "current_revision": state["revision"],
            }

    @staticmethod
    def _snapshot_payload(state: Mapping[str, Any]) -> dict[str, Any]:
        public = {key: value for key, value in state.items() if key not in {"_events", "_event_hash"}}
        checkpoint = {
            "cycle_id": state["cycle_id"], "sequence": state["sequence"],
            "event_hash": state["_event_hash"],
        }
        return {"checkpoint": checkpoint, "state_hash": digest(public), "state": public}

    def acknowledge(
        self, cycle_id: str, *, checkpoint: Mapping[str, Any], state_hash: str,
    ) -> dict[str, Any]:
        snapshot = self.state_snapshot(cycle_id)
        if dict(checkpoint) != snapshot["checkpoint"] or state_hash != snapshot["state_hash"]:
            raise AckMismatch("acknowledgement checkpoint or state hash does not match current ledger")
        return {"checkpoint": snapshot["checkpoint"], "state_hash": snapshot["state_hash"]}
    @staticmethod
    def _export_result(package: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "export_id": package["package_id"],
            "manifest": dict(package["manifest"]),
            "manifest_hash": package["manifest_hash"],
            "archive_blob_id": package["archive_blob_id"],
            "archive_hash": package["archive_hash"],
            "byte_length": package["byte_length"],
        }

    def load(self, cycle_id: str) -> dict[str, Any]:
        directory = self._existing_cycle_directory(cycle_id)
        with self._lock(directory / ".lock"):
            return self._load_locked(directory)

    def repair_snapshot(self, cycle_id: str) -> dict[str, Any]:
        directory = self._existing_cycle_directory(cycle_id)
        with self._lock(directory / ".lock"):
            state = self._load_locked(directory)
            self._write_snapshot(directory, state)
            self._snapshot_repair_needed.discard(cycle_id)
            return state

    def snapshot_repair_needed(self, cycle_id: str) -> bool:
        """Whether this repository observed a committed ledger without its snapshot."""
        return cycle_id in self._snapshot_repair_needed
    def _existing_cycle_directory(self, cycle_id: str) -> Path:
        try:
            canonical_id_array((cycle_id,))
        except ContractError as exc:
            raise CycleError("cycle_id must be an exact protocol ID") from exc
        directory = self.root / cycle_id
        if directory.parent != self.root or directory.is_symlink():
            raise RepositoryCorrupt("cycle directory must be a direct non-symlink child")
        if not directory.is_dir():
            raise FileNotFoundError(cycle_id)
        if directory.resolve().parent != self.root.resolve():
            raise RepositoryCorrupt("cycle directory escapes repository root")
        return directory

    @staticmethod
    def _validate_mutation(command: Mapping[str, Any], expected_name: str | None = None) -> None:
        try:
            validate_protocol_action(command)
        except (ContractError, KeyError, TypeError) as exc:
            raise CycleError("mutation requires a validated closed protocol envelope") from exc
        if expected_name is not None and command["name"] != expected_name:
            raise CycleError(f"expected {expected_name} command")

    def _load_locked(self, directory: Path) -> dict[str, Any]:
        """Replay and repair while the cycle lock is already held."""
        state, _ = self._replay(directory, repair=True)
        if not self._snapshot_matches_state(directory / "manifest.json", state):
            self._write_snapshot(directory, state)
        self._snapshot_repair_needed.discard(directory.name)
        return state

    @staticmethod
    def _frozen_action(
        command: Mapping[str, Any], *, verified_result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist only the immutable reducer input needed for authoritative replay."""
        frozen: dict[str, Any] = {
            "name": command["name"],
            "payload": dict(command["payload"]),
        }
        if verified_result is not None:
            frozen["verified_result"] = dict(verified_result)
        return {"frozen_action": frozen}

    @staticmethod
    def _event_payload_without_receipt(event: Mapping[str, Any]) -> dict[str, Any]:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise RepositoryCorrupt("event payload is invalid")
        return {key: value for key, value in payload.items() if key != "command_receipt"}

    def _response(self, cycle_id: str, sequence: int, revision: int, command: Mapping[str, Any], result: Any) -> bytes:
        timestamp = command["timestamp"]
        request_message_id = command["message_id"]
        return canonical_json({
            "protocol": "muchanipo",
            "protocol_version": "ai-scientist.v1",
            "kind": "response",
            "name": "command.accepted.response",
            "message_id": deterministic_id("response", {"cycle_id": cycle_id, "sequence": sequence}),
            "cycle_id": cycle_id,
            "correlation_id": request_message_id,
            "causation_id": request_message_id,
            "sequence": sequence,
            "revision": revision,
            "idempotency_key": command.get("idempotency_key"),
            "timestamp": timestamp,
            "payload": {"request_message_id": request_message_id, "result": result},
            "extensions": {},
        })

    def _result_with_gates(self, reduction: Reduction) -> dict[str, Any]:
        """Attach server-derived current gate status to an accepted-command result."""
        result = dict(reduction.result) if isinstance(reduction.result, Mapping) else {"value": reduction.result}
        result["gates"] = {"export_ready": self.reducer.export_ready(reduction.state)}
        return result

    def _receipt(self, state: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
        for event in reversed(state.get("_events", [])):
            receipt = event["payload"].get("command_receipt")
            if receipt and receipt["idempotency_key"] == key: return receipt
        return None

    @staticmethod
    def _receipt_response(receipt: Mapping[str, Any]) -> bytes:
        encoded = receipt.get("response_envelope_base64")
        expected_digest = receipt.get("response_bytes_digest")
        if not isinstance(encoded, str) or not isinstance(expected_digest, str):
            raise RepositoryCorrupt("invalid command receipt")
        try:
            response = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise RepositoryCorrupt("invalid command receipt") from exc
        if base64.b64encode(response).decode("ascii") != encoded or byte_digest(response) != expected_digest:
            raise RepositoryCorrupt("invalid command receipt")
        return response

    def _genesis_receipt(self, state: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
        events = state.get("_events", [])
        if not events:
            return None
        receipt = events[0].get("payload", {}).get("command_receipt")
        if isinstance(receipt, Mapping) and receipt.get("idempotency_key") == key:
            return receipt
        return None

    def _creation_registry_response(self, registry: Path, key: str, expected_cycle_id: str, command_hash: str) -> bytes:
        try:
            raw = registry.read_bytes()
            record = decode_json_object(raw)
            if not isinstance(record, Mapping) or canonical_json(record) != raw:
                raise RepositoryCorrupt("invalid creation registry")
            required = {"registry_schema", "creation_idempotency_key", "command_digest", "cycle_id",
                        "receipt_id", "response_bytes_digest", "response_envelope_base64"}
            if set(record) != required or record.get("registry_schema") != "ai-scientist.creation-registry.v1":
                raise RepositoryCorrupt("invalid creation registry")
            if record.get("creation_idempotency_key") != key:
                raise RepositoryCorrupt("creation registry key mismatch")
            if not all(isinstance(record.get(field), str) for field in required):
                raise RepositoryCorrupt("invalid creation registry")
        except (OSError, ValueError, TypeError) as exc:
            raise RepositoryCorrupt("invalid creation registry") from exc
        if record["command_digest"] != command_hash:
            raise IdempotencyConflict("same key has different content")
        if record["cycle_id"] != expected_cycle_id:
            raise RepositoryCorrupt("creation registry cycle mismatch")
        directory = self._existing_cycle_directory(record["cycle_id"])
        with self._lock(directory / ".lock"):
            state = self._load_locked(directory)
        receipt = self._genesis_receipt(state, key)
        if receipt is None or any(receipt.get(field) != record[field] for field in (
            "receipt_id", "command_digest", "response_bytes_digest", "response_envelope_base64"
        )):
            raise RepositoryCorrupt("creation registry does not match genesis receipt")
        return self._receipt_response(record)

    def _snapshot_matches_state(self, snapshot: Path, state: Mapping[str, Any]) -> bool:
        if not snapshot.exists():
            return False
        try:
            raw = snapshot.read_bytes()
            value = decode_json_object(raw)
            public = {key: value for key, value in state.items() if key not in {"_events", "_event_hash"}}
            checkpoint = {"cycle_id": state["cycle_id"], "sequence": state["sequence"],
                          "event_hash": state.get("_event_hash", GENESIS_HASH)}
            expected = {"snapshot_id": deterministic_id("snapshot", checkpoint), "checkpoint": checkpoint,
                        "state_hash": digest(public), "state": public}
            expected["snapshot_hash"] = digest({"checkpoint": checkpoint, "state_hash": expected["state_hash"],
                                                "state": public})
            return isinstance(value, Mapping) and canonical_json(value) == raw and value == expected
        except (OSError, ValueError, TypeError):
            return False

    def _commit_new(self, directory: Path, state: dict[str, Any], event: dict[str, Any], key: str, command_hash: str, response: bytes) -> None:
        directory.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=directory.name + ".tmp-", dir=directory.parent))
        try:
            (temporary / "blobs" / "sha256").mkdir(parents=True); (temporary / "exports").mkdir(); (temporary / "quarantine").mkdir()
            self._commit(temporary, state, event, key, command_hash, response)
            os.replace(temporary, directory); _fsync_directory(directory.parent)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def _commit(self, directory: Path, state: dict[str, Any], event: dict[str, Any], key: str, command_hash: str, response: bytes) -> None:
        receipt = {"receipt_id": deterministic_id("receipt", {"cycle_id": event["cycle_id"], "key": key, "command_digest": command_hash}), "idempotency_key": key, "request_message_id": event["causation_id"], "command_digest": command_hash, "response_envelope_base64": base64.b64encode(response).decode("ascii"), "response_bytes_digest": byte_digest(response)}
        event["payload"] = dict(event["payload"]) | {"command_receipt": receipt}
        previous = state.get("_event_hash", GENESIS_HASH); event["previous_event_hash"] = previous
        frame = {"record_type": "event", "frame_version": 1, "frame_id": deterministic_id("frame", {"cycle_id": event["cycle_id"], "sequence": event["sequence"]}), "frame_hash": "", "event": event}
        frame["frame_hash"] = event_frame_hash(frame)
        marker = {"record_type": "commit", "frame_version": 1, "frame_id": frame["frame_id"], "frame_hash": frame["frame_hash"], "event_hash": digest(event)}
        try:
            with (directory / "ledger.jsonl").open("ab") as ledger:
                ledger.write(_line(frame)); ledger.write(_line(marker)); ledger.flush(); os.fsync(ledger.fileno())
        except OSError as exc: raise CommitOutcomeUnknown("ledger fsync outcome unknown") from exc
        state["revision"] = event["revision"]; state["sequence"] = event["sequence"]; state.setdefault("_events", []).append(event); state["_event_hash"] = marker["event_hash"]
        try:
            self._write_snapshot(directory, state)
        except Exception:
            self._snapshot_repair_needed.add(event["cycle_id"])

    def _write_snapshot(self, directory: Path, state: Mapping[str, Any]) -> None:
        public = {k: v for k, v in state.items() if k not in {"_events", "_event_hash"}}
        checkpoint = {"cycle_id": state["cycle_id"], "sequence": state["sequence"], "event_hash": state.get("_event_hash", GENESIS_HASH)}
        snapshot = {"snapshot_id": deterministic_id("snapshot", checkpoint), "checkpoint": checkpoint, "state_hash": digest(public), "state": public}
        snapshot["snapshot_hash"] = digest({"checkpoint": checkpoint, "state_hash": snapshot["state_hash"], "state": public})
        self._atomic_json(directory / "manifest.json", snapshot)

    def _atomic_json(self, path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("wb") as out: out.write(canonical_json(value)); out.flush(); os.fsync(out.fileno())
        os.replace(temporary, path); _fsync_directory(path.parent)

    def _replay(self, directory: Path, *, repair: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        ledger = directory / "ledger.jsonl"
        raw = ledger.read_bytes() if ledger.exists() else b""
        lines = raw.splitlines(keepends=True); valid_end = 0; events: list[dict[str, Any]] = []; previous = GENESIS_HASH
        index = 0
        while index + 1 < len(lines):
            try:
                if not lines[index].endswith(b"\n") or not lines[index + 1].endswith(b"\n"): break
                frame, marker = decode_json_object(lines[index]), decode_json_object(lines[index + 1])
                if canonical_json(frame) + b"\n" != lines[index] or canonical_json(marker) + b"\n" != lines[index + 1]: raise RepositoryCorrupt("noncanonical ledger frame")
                if frame.get("record_type") != "event" or marker.get("record_type") != "commit" or frame.get("frame_hash") != event_frame_hash(frame): raise RepositoryCorrupt("invalid frame hash")
                event = frame["event"]
                if marker.get("frame_id") != frame.get("frame_id") or marker.get("frame_hash") != frame.get("frame_hash") or marker.get("event_hash") != digest(event): raise RepositoryCorrupt("invalid commit marker")
                if event.get("previous_event_hash") != previous or event.get("sequence") != len(events) + 1 or event.get("revision") != len(events) + 1: raise RepositoryCorrupt("ledger continuity failure")
                receipt = event.get("payload", {}).get("command_receipt")
                if not isinstance(receipt, Mapping):
                    raise RepositoryCorrupt("invalid command receipt")
                self._receipt_response(receipt)
                events.append(event); previous = marker["event_hash"]; valid_end += len(lines[index]) + len(lines[index + 1]); index += 2
            except (ValueError, KeyError, TypeError) as exc: raise RepositoryCorrupt("interior ledger corruption") from exc
        if index != len(lines):
            if not repair: raise RepositoryCorrupt("trailing incomplete ledger")
            (directory / "quarantine").mkdir(exist_ok=True)
            (directory / "quarantine" / "ledger-tail.jsonl").write_bytes(raw[valid_end:])
            with ledger.open("r+b") as out: out.truncate(valid_end); out.flush(); os.fsync(out.fileno())
        if not events: raise RepositoryCorrupt("missing genesis event")
        first = events[0]
        frozen = first.get("extensions", {}).get("frozen_action")
        if not isinstance(frozen, Mapping) or frozen.get("name") != "cycle.start" or not isinstance(frozen.get("payload"), Mapping):
            raise RepositoryCorrupt("genesis event lacks frozen start facts")
        start = frozen["payload"]
        first_receipt = first["payload"].get("command_receipt")
        if (not isinstance(first_receipt, Mapping)
                or first_receipt.get("command_digest") != command_digest(
                    "cycle.start", None, first["idempotency_key"], start)):
            raise RepositoryCorrupt("genesis receipt does not bind frozen facts")
        try:
            state = initial_state(
                first["cycle_id"], start["raw_question"], start["contract_version"],
                start["boundary"], start["creator"],
            )
        except (KeyError, TypeError, ValueError, ContractError) as exc:
            raise RepositoryCorrupt("invalid frozen genesis facts") from exc
        if self._event_payload_without_receipt(first) != {
            "normalized_question": normalize_question(start["raw_question"]),
            "contract_version": start["contract_version"],
            "created_records": list(state["records"]),
            "superseded_record_ids": [],
            "derived_current_refs": {},
        }:
            raise RepositoryCorrupt("genesis facts do not reduce to its event")
        for event in events[1:]:
            frozen = event.get("extensions", {}).get("frozen_action")
            if not isinstance(frozen, Mapping) or not isinstance(frozen.get("name"), str) or not isinstance(frozen.get("payload"), Mapping):
                raise RepositoryCorrupt("event lacks frozen reducer facts")
            action = {"name": frozen["name"], "payload": frozen["payload"]}
            receipt = event["payload"].get("command_receipt")
            if (not isinstance(receipt, Mapping)
                    or receipt.get("command_digest") != command_digest(
                        frozen["name"], event["cycle_id"], event["idempotency_key"], frozen["payload"])):
                raise RepositoryCorrupt("receipt does not bind frozen reducer facts")
            # Present the exact pre-command revision/sequence the live mutation
            # observed so revision-bound reducer facts replay identically.
            state["revision"] = event["revision"] - 1
            state["sequence"] = event["sequence"] - 1
            try:
                if frozen["name"] == "result.submit":
                    result = frozen.get("verified_result")
                    if not isinstance(result, Mapping):
                        raise RepositoryCorrupt("result event lacks verified result facts")
                    reduction = self.reducer.apply_verified_result(state, result)
                elif frozen["name"] == "export.create":
                    reduction = self.reducer.apply(state, action)
                    package = get_export_package(directory / "exports", event["payload"].get("export_id"))
                    expected = {
                        **reduction.event_payload,
                        "export_id": package["package_id"],
                        "manifest_hash": package["manifest_hash"],
                        "archive_blob_id": package["archive_blob_id"],
                        "archive_hash": package["archive_hash"],
                        "byte_length": package["byte_length"],
                    }
                    if event.get("name") != reduction.event_name or self._event_payload_without_receipt(event) != expected:
                        raise RepositoryCorrupt("export facts do not match authoritative reduction")
                    state = reduction.state
                else:
                    reduction = self.reducer.apply(state, action)
            except RepositoryCorrupt:
                raise
            except (CycleError, ContractError, KeyError, TypeError, ValueError) as exc:
                raise RepositoryCorrupt("event reducer facts are invalid") from exc
            if reduction is not None and frozen["name"] != "export.create":
                if (reduction.event_name != event.get("name")
                        or reduction.event_payload != self._event_payload_without_receipt(event)):
                    raise RepositoryCorrupt("event facts do not match authoritative reduction")
                state = reduction.state
        state["revision"] = events[-1]["revision"]
        state["sequence"] = events[-1]["sequence"]
        state["_events"] = events
        state["_event_hash"] = previous
        return state, events

