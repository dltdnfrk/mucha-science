from __future__ import annotations

from typing import Any, IO, Protocol

from ..events import (
    SCIENTIFIC_ACTIONS,
    SCIENTIFIC_PROTOCOL_VERSION,
    ScientificEnvelope,
    emit_scientific,
    parse_scientific_action,
)
from src.pipeline.cycle_repository import (
    AckMismatch,
    CommitOutcomeUnknown,
    CursorMismatch,
    CycleRepository,
    ExportTooLarge,
    IdempotencyConflict,
    RepositoryCorrupt,
    RevisionConflict,
)
from src.pipeline.external_result_ingest import ExternalResultIngestError, ImportQuota
from src.pipeline.scientific_contracts import deterministic_id
from src.pipeline.scientific_cycle import CycleError, GateUnsatisfied
from src.pipeline.scientific_handoff import HandoffError

from .protocol_output import (
    _repository_response,
    _scientific_error,
    _scientific_response,
    _scientific_snapshot,
)
from .scientific_config import _advertised_capabilities, _approved_import_roots


class _ProtocolSession(Protocol):
    repository: CycleRepository
    config: dict[str, Any]
    negotiated: bool
    client_instance_id: str | None
    request_ordinals: dict[str, int]
    ack_ordinals: dict[str, int]
    replay_blocked: set[str]
    server_instance_id: str


def dispatch_protocol_line(session: _ProtocolSession, line: str, stdout: IO[str]) -> None:
    config = session.config
    repository = session.repository
    action = parse_scientific_action(line)
    if action is None:
        _scientific_error(stdout, code="protocol_invalid", message="expected ai-scientist.v1 action envelope")
        return
    if action.name == "protocol.hello":
        if not config["enabled"]:
            _scientific_error(stdout, code="feature_disabled", message="ai-scientist is disabled", action=action)
            return
        if not config["protocol_capability"]:
            _scientific_error(stdout, code="capability_required", message="ai-scientist wire capability is disabled", action=action)
            return
        if SCIENTIFIC_PROTOCOL_VERSION not in action.payload["supported_versions"]:
            _scientific_error(stdout, code="protocol_unsupported", message="ai-scientist.v1 capability is required", action=action)
            return
        session.negotiated = True
        session.client_instance_id = action.payload["client_instance_id"]
        accepted_cursors = []
        for cursor in action.payload["cursors"]:
            try:
                repository.verified_replay(cursor["cycle_id"], cursor=cursor, max_events=1)
                accepted_cursors.append(dict(cursor))
            except CursorMismatch:
                _scientific_snapshot(stdout, action, snapshot=repository.state_snapshot(cursor["cycle_id"]), reason="cursor_mismatch")
            except (FileNotFoundError, RevisionConflict):
                continue
        _scientific_response(
            stdout, action, name="protocol.welcome.response",
            payload={"request_message_id": action.message_id, "selected_version": SCIENTIFIC_PROTOCOL_VERSION,
                     "connection_id": deterministic_id(
                         "connection",
                         {
                             "client_instance_id": session.client_instance_id,
                             "handshake_idempotency_key": action.payload["handshake_idempotency_key"],
                             "server_instance_id": session.server_instance_id,
                         },
                     ),
                     "server_instance_id": session.server_instance_id,
                     "capabilities": _advertised_capabilities(config),
                     "operation_modes": ["read_only" if config["emergency_read_only"] else "normal"],
                     "accepted_cursors": accepted_cursors},
        )
        return
    if not config["enabled"]:
        _scientific_error(stdout, code="feature_disabled", message="ai-scientist is disabled", action=action)
        return
    if not config["protocol_capability"] or not session.negotiated:
        _scientific_error(stdout, code="capability_required", message="protocol.hello is required before lifecycle commands", action=action)
        return
    client_instance_id = session.client_instance_id
    assert client_instance_id is not None
    if action.name not in SCIENTIFIC_ACTIONS:
        _scientific_error(stdout, code="unknown_action", message=f"unsupported scientific action: {action.name}", action=action)
        return
    if action.name in {"cycle.replay", "cycle.resume", "export.get", "report.render"}:
        payload = action.payload
        if payload["client_instance_id"] != client_instance_id or payload["request_ordinal"] <= session.request_ordinals.get(client_instance_id, 0):
            _scientific_error(stdout, code="validation_failed", message="stale client request ordinal", action=action)
            return
        session.request_ordinals[client_instance_id] = payload["request_ordinal"]
    elif action.name == "cycle.ack":
        payload = action.payload
        if payload["client_instance_id"] != client_instance_id or payload["ack_ordinal"] <= session.ack_ordinals.get(client_instance_id, 0):
            _scientific_error(stdout, code="ack_mismatch", message="stale client acknowledgement ordinal", action=action)
            return
        session.ack_ordinals[client_instance_id] = payload["ack_ordinal"]
    read_actions = {"cycle.replay", "cycle.resume", "report.render", "export.get", "cycle.ack"}
    if action.name == "result.submit":
        if (not config["allow_external_result_import"]
                or not _approved_import_roots(config)):
            _scientific_error(stdout, code="import_forbidden", message="external result import is not configured", action=action)
            return
        if config["emergency_read_only"]:
            _scientific_error(stdout, code="read_only", message="scientific mutations are disabled in emergency mode", action=action)
            return
    if action.name not in read_actions:
        if config["emergency_read_only"]:
            _scientific_error(stdout, code="read_only", message="scientific mutations are disabled in emergency mode", action=action)
            return
        if action.name == "cycle.start" and not config["allow_new_cycles"]:
            _scientific_error(stdout, code="feature_disabled", message="new scientific cycles are disabled", action=action)
            return
    try:
        if action.name == "cycle.start":  # noqa: SIM116  # noqa: IF_VARIANT_OK
            command = action.to_dict()
            _repository_response(stdout, repository.start_cycle(command))
        elif action.name == "cycle.replay":  # noqa: SIM116  # noqa: IF_VARIANT_OK
            cursor = action.payload["cursor"]
            cycle_id = cursor["cycle_id"]
            if cycle_id in session.replay_blocked:
                raise AckMismatch("acknowledgement is required before another replay")
            page = repository.verified_replay(cycle_id, cursor=cursor, max_events=action.payload["max_events"])
            session.replay_blocked.add(cycle_id)
            _scientific_response(
                stdout, action, name="cycle.replay.response",
                payload={"request_message_id": action.message_id, "cycle_id": cycle_id, **page},
                cycle_id=cycle_id, sequence=page["to_cursor"]["sequence"], revision=page["current_revision"],
            )
        elif action.name == "cycle.resume":  # noqa: SIM116  # noqa: IF_VARIANT_OK
            cycle_id = action.payload["cycle_id"]
            snapshot = repository.state_snapshot(cycle_id)
            try:
                page = repository.verified_replay(cycle_id, cursor=action.payload["cursor"], max_events=128)
            except CursorMismatch:
                _scientific_snapshot(stdout, action, snapshot=snapshot, reason="cursor_mismatch")
                page = repository.verified_replay(cycle_id, cursor=snapshot["checkpoint"], max_events=128)
            _scientific_response(
                stdout, action, name="cycle.resume.response",
                payload={"request_message_id": action.message_id, "cycle_id": cycle_id, "snapshot": snapshot,
                         "events": page["events"], "to_cursor": page["to_cursor"],
                         "current_revision": snapshot["state"]["revision"]},
                cycle_id=cycle_id, sequence=snapshot["checkpoint"]["sequence"],
                revision=snapshot["state"]["revision"],
            )
        elif action.name == "result.submit":  # noqa: SIM116  # noqa: IF_VARIANT_OK
            if not action.cycle_id:
                raise CycleError("result.submit requires cycle_id")
            command = action.to_dict()
            quota = ImportQuota(
                max_files=config["max_import_files"],
                max_file_bytes=config["max_import_bytes"],
                max_total_bytes=config["max_import_bytes"],
            )
            _repository_response(
                stdout,
                repository.submit_external_result(
                    command,
                    staging_root=repository.root / "staged-results",
                    quota=quota,
                ),
            )
        elif action.name == "export.create":  # noqa: SIM116  # noqa: IF_VARIANT_OK
            if not action.cycle_id:
                raise CycleError("export.create requires cycle_id")
            command = action.to_dict()
            _repository_response(stdout, repository.create_export(command))
        elif action.name == "export.get":  # noqa: SIM116  # noqa: IF_VARIANT_OK
            payload = repository.get_export(
                action.payload["export_id"],
                include_archive_bytes=action.payload["include_archive_bytes"],
            )
            emit_scientific(
                ScientificEnvelope(
                    kind="response",
                    name="export.get.response",
                    payload={"request_message_id": action.message_id, **payload},
                    cycle_id=None,
                    correlation_id=action.message_id,
                    causation_id=action.message_id,
                ),
                stream=stdout,
            )
        elif action.name == "report.render":  # noqa: SIM116  # noqa: IF_VARIANT_OK
            payload = action.payload
            rendered = repository.render_report(
                payload["cycle_id"],
                at_revision=payload["at_revision"],
                format=payload["format"],
                include_status_overlay=payload["include_status_overlay"],
            )
            snapshot = repository.state_snapshot(payload["cycle_id"])
            _scientific_response(
                stdout, action, name="report.render.response",
                payload={"request_message_id": action.message_id, **rendered},
                cycle_id=payload["cycle_id"], sequence=snapshot["checkpoint"]["sequence"],
                revision=payload["at_revision"],
            )
        elif action.name == "cycle.ack":
            checkpoint = action.payload["checkpoint"]
            acknowledgement = repository.acknowledge(
                checkpoint["cycle_id"], checkpoint=checkpoint, state_hash=action.payload["state_hash"],
            )
            session.replay_blocked.discard(checkpoint["cycle_id"])
            _scientific_response(
                stdout, action, name="cycle.acknowledged.response",
                payload={"request_message_id": action.message_id, **acknowledgement, "accepted": True},
                cycle_id=checkpoint["cycle_id"], sequence=checkpoint["sequence"],
                revision=repository.state_snapshot(checkpoint["cycle_id"])["state"]["revision"],
            )
        else:
            if not action.cycle_id:
                raise CycleError(f"{action.name} requires cycle_id")
            command = action.to_dict()
            _repository_response(stdout, repository.execute(command))
    except IdempotencyConflict as exc:
        _scientific_error(stdout, code="idempotency_conflict", message=str(exc), action=action)
    except CursorMismatch as exc:
        _scientific_error(stdout, code="cursor_mismatch", message=str(exc), action=action)
    except AckMismatch as exc:
        _scientific_error(stdout, code="ack_mismatch", message=str(exc), action=action)
    except RevisionConflict as exc:
        _scientific_error(stdout, code="revision_conflict", message=str(exc), action=action)
    except (GateUnsatisfied, HandoffError) as exc:
        _scientific_error(stdout, code="gate_unsatisfied", message=str(exc), action=action)
    except FileNotFoundError as exc:
        _scientific_error(stdout, code="not_found", message=str(exc), action=action)
    except RepositoryCorrupt as exc:
        _scientific_error(stdout, code="repository_corrupt", message=str(exc), action=action)
    except CommitOutcomeUnknown as exc:
        _scientific_error(stdout, code="commit_outcome_unknown", message=str(exc), action=action)
    except ExportTooLarge as exc:
        _scientific_error(stdout, code="export_too_large", message=str(exc), action=action)
    except ExternalResultIngestError as exc:
        _scientific_error(stdout, code="import_forbidden", message=str(exc), action=action)
    except CycleError as exc:
        _scientific_error(stdout, code="validation_failed", message=str(exc), action=action)
