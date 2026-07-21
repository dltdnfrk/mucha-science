from __future__ import annotations

import io
import json
from pathlib import Path
import pytest

from src.hitl.signoff_core import SignoffCore, SignoffError
from src.muchanipo.server import serve
from src.pipeline.cycle_repository import CycleRepository, ExportTooLarge
from src.pipeline.scientific_contracts import Responsibility, byte_digest, canonical_json
from src.pipeline.scientific_cycle import GateUnsatisfied, ScientificCycleReducer, initial_state
from src.pipeline.external_result_ingest import ingest_staged_external_result


CREATOR = {
    "actor_kind": "human", "display_name": "Operator", "organization": None, "role": None,
    "assertion_source": "operator_entry", "verification_status": "operator_asserted_unverified",
    "authority_scope": {"kind": "none", "scope": None}, "external_reference": None,
}
NORMAL_CONFIG = {
    "enabled": True,
    "protocol_capability": True,
    "allow_new_cycles": True,
    "allow_external_result_import": True,
    "emergency_read_only": False,
}


def action(name: str, *, payload: dict | None = None, cycle_id: str | None = None, key: str | None = None) -> str:
    resolved_payload = dict(payload or {})
    if name == "protocol.hello" and set(resolved_payload) == {"protocol_versions"}:
        key = key or "hello-1"
        resolved_payload = {
            "handshake_idempotency_key": key,
            "client_instance_id": "client_00000000000000000000000000000000",
            "supported_versions": resolved_payload["protocol_versions"],
            "capabilities": [],
            "projection": "scientific-cycle.v1",
            "cursors": [],
        }
    return json.dumps({
        "protocol": "muchanipo", "protocol_version": "ai-scientist.v1", "kind": "action", "name": name,
        "message_id": "message_00000000000000000000000000000000", "cycle_id": cycle_id,
        "correlation_id": "message_00000000000000000000000000000000", "causation_id": None, "sequence": 0, "revision": 0,
        "idempotency_key": key, "timestamp": "1970-01-01T00:00:00.000000Z",
        "payload": resolved_payload, "extensions": {},
    })


def read_scientific(
    stdin_text: str,
    tmp_path: Path,
    *,
    config: dict | None = None,
) -> tuple[list[str], list[dict]]:
    stdout = io.StringIO()
    assert serve(
        "legacy-topic",
        report_path=tmp_path / "unused.md",
        wait_for_input=False,
        stdout=stdout,
        stdin=io.StringIO(stdin_text),
        scientific_mode=True,
        repository=CycleRepository(tmp_path / "home"),
        scientific_config=NORMAL_CONFIG if config is None else config,
    ) == 0
    lines = stdout.getvalue().splitlines()
    return lines, [json.loads(line) for line in lines]


def start_payload(key: str = "create-1") -> dict:
    return {
        "creation_idempotency_key": key, "expected_revision": 0, "raw_question": "Question?",
        "contract_version": "ai-scientist.v1", "boundary": {"kind": "cognitive_only", "description": "local"},
        "creator": CREATOR,
    }


def test_scientific_mode_is_opt_in_and_legacy_stream_is_unchanged(tmp_path: Path):
    stdout = io.StringIO()
    serve("topic", report_path=tmp_path / "REPORT.md", wait_for_input=False, stdout=stdout, stdin=io.StringIO(), pipeline="stub")
    events = [event["event"] for event in map(json.loads, stdout.getvalue().splitlines())]
    # Without --scientific-mode the research stream is served untouched and no
    # ai-scientist envelope kind ever appears on the wire.
    assert events[:2] == ["phase_change", "phase_change"]
    for line in stdout.getvalue().splitlines():
        assert json.loads(line).get("protocol_version") != "ai-scientist.v1"


def test_activation_flags_fail_closed_before_and_after_negotiation(tmp_path: Path):
    hello = action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]})
    _, disabled = read_scientific(hello + "\n", tmp_path, config={})
    assert disabled[0]["payload"]["stable_code"] == "feature_disabled"

    _, no_capability = read_scientific(
        hello + "\n" + action("cycle.start", payload=start_payload(), key="create-1") + "\n",
        tmp_path,
        config={"enabled": True},
    )
    assert [event["payload"]["stable_code"] for event in no_capability] == ["capability_required", "capability_required"]


def test_capability_mismatch_is_a_stable_error(tmp_path: Path):
    _, events = read_scientific(action("protocol.hello", payload={"protocol_versions": ["future.v2"]}) + "\n", tmp_path)
    assert events[0]["name"] == "command.rejected.error"
    assert events[0]["payload"]["stable_code"] == "protocol_unsupported"


def test_scientific_parser_rejects_duplicate_extra_and_profile_mismatch(tmp_path: Path):
    duplicate = action(
        "protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}
    ).replace(
        '"protocol": "muchanipo"',
        '"protocol": "muchanipo", "protocol": "muchanipo"',
        1,
    )
    extra = json.loads(action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}))
    extra["unexpected"] = True
    mismatch = action("protocol.hello", payload={
        "protocol_versions": ["ai-scientist.v1"], "normalization_profile": "different",
        "normalization_profile_version": "1",
    })
    _, events = read_scientific("\n".join([duplicate, json.dumps(extra), mismatch]) + "\n", tmp_path)
    assert [event["payload"]["stable_code"] for event in events] == ["protocol_invalid"] * 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sequence", 1.5),
        ("sequence", True),
        ("sequence", 9_007_199_254_740_992),
        ("message_id", "not-an-id"),
        ("timestamp", None),
    ],
)
def test_scientific_parser_rejects_each_lossy_envelope_field(tmp_path: Path, field: str, value: object):
    invalid = json.loads(action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}))
    invalid[field] = value
    _, events = read_scientific(json.dumps(invalid) + "\n", tmp_path)
    assert len(events) == 1
    assert events[0]["name"] == "command.rejected.error"
    assert events[0]["payload"]["stable_code"] == "protocol_invalid"
def test_forged_authority_envelope_is_protocol_invalid(tmp_path: Path):
    payload = start_payload()
    payload["creator"] = CREATOR | {"verification_status": "verified"}
    _, events = read_scientific(
        action("cycle.start", payload=payload, key="forged-authority") + "\n",
        tmp_path,
    )
    assert len(events) == 1
    assert events[0]["name"] == "command.rejected.error"
    assert events[0]["payload"]["stable_code"] == "protocol_invalid"



def test_normal_negotiation_starts_reads_and_replays_committed_response_bytes(tmp_path: Path):
    lines, events = read_scientific("\n".join([
        action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}),
        action("cycle.start", payload=start_payload(), key="create-1"),
        action("cycle.start", payload=start_payload(), key="create-1"),
    ]) + "\n", tmp_path)
    assert events[0]["name"] == "protocol.welcome.response"
    accepted_lines = [line for line in lines if '"name":"command.accepted.response"' in line]
    assert len(accepted_lines) == 2
    assert accepted_lines[0].encode("utf-8") == accepted_lines[1].encode("utf-8")

    cycle_id = events[1]["cycle_id"]
    snapshot = CycleRepository(tmp_path / "home").state_snapshot(cycle_id)
    _, replay = read_scientific("\n".join([
        action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}),
        action("cycle.replay", cycle_id=cycle_id, payload={
            "client_instance_id": "client_00000000000000000000000000000000",
            "request_ordinal": 1,
            "cursor": {
                "cycle_id": cycle_id,
                "sequence": 0,
                "event_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            },
            "max_events": 128,
        }),
        action("cycle.abort", cycle_id=cycle_id, key="abort-stale", payload={
            "expected_revision": 0,
            "actor": CREATOR,
            "reason": "stale request",
            "final_observation": "none",
        }),
    ]) + "\n", tmp_path)
    assert replay[1]["name"] == "cycle.replay.response"
    assert replay[1]["payload"]["to_cursor"] == snapshot["checkpoint"]
    assert replay[2]["payload"]["stable_code"] == "revision_conflict"


def test_new_cycle_and_import_gates_fail_closed(tmp_path: Path):
    config = NORMAL_CONFIG | {
        "allow_new_cycles": False,
        "allow_external_result_import": False,
    }
    _, events = read_scientific("\n".join([
        action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}),
        action("cycle.start", payload=start_payload(), key="create-1"),
        action("result.submit", payload={"controlled_import": {}}, key="import-1"),
    ]) + "\n", tmp_path, config=config)
    assert [event["payload"]["stable_code"] for event in events[1:]] == ["feature_disabled", "protocol_invalid"]


def test_emergency_mode_denies_mutation_and_preserves_reads(tmp_path: Path):
    _, created = read_scientific("\n".join([
        action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}),
        action("cycle.start", payload=start_payload(), key="create-1"),
    ]) + "\n", tmp_path)
    cycle_id = created[1]["cycle_id"]
    snapshot = CycleRepository(tmp_path / "home").state_snapshot(cycle_id)

    emergency = NORMAL_CONFIG | {"emergency_read_only": True}
    _, events = read_scientific("\n".join([
        action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}),
        action("cycle.replay", cycle_id=cycle_id, payload={
            "client_instance_id": "client_00000000000000000000000000000000",
            "request_ordinal": 1,
            "cursor": {
                "cycle_id": cycle_id,
                "sequence": 0,
                "event_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            },
            "max_events": 128,
        }),
        action("cycle.start", payload=start_payload("create-2"), key="create-2"),
        action("cycle.ack", cycle_id=cycle_id, payload={
            "client_instance_id": "client_00000000000000000000000000000000",
            "ack_ordinal": 1,
            "checkpoint": snapshot["checkpoint"],
            "state_hash": snapshot["state_hash"],
        }),
    ]) + "\n", tmp_path, config=emergency)
    assert events[0]["payload"]["operation_modes"] == ["read_only"]
    assert events[1]["name"] == "cycle.replay.response"
    assert events[2]["payload"]["stable_code"] == "read_only"
    assert events[3]["name"] == "cycle.acknowledged.response"
    assert CycleRepository(tmp_path / "home").load(cycle_id)["revision"] == 1
def test_strict_read_actions_use_payload_targets_and_preserve_read_state(tmp_path: Path):
    class ReadRepository:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def get_export(self, export_id: str, *, include_archive_bytes: bool) -> dict:
            self.calls.append(("export", (export_id, include_archive_bytes)))
            if include_archive_bytes:
                raise ExportTooLarge("requested export archive exceeds 16 MiB")
            return {
                "export_id": export_id,
                "manifest": {"schema_version": "ai-scientist.handoff.v2"},
                "archive_hash": "sha256:" + "a" * 64,
                "byte_length": 7,
                "archive_base64": None,
            }

        def render_report(self, cycle_id: str, **kwargs: object) -> dict:
            self.calls.append(("report", (cycle_id, kwargs)))
            return {
                "cycle_id": cycle_id,
                "at_revision": 7,
                "format": "canonical_json",
                "body_utf8_or_json": {"body_utf8": "immutable body"},
                "body_hash": "sha256:" + "b" * 64,
                "status_overlay": None,
            }

        def state_snapshot(self, cycle_id: str) -> dict:
            self.calls.append(("snapshot", cycle_id))
            return {
                "checkpoint": {"cycle_id": cycle_id, "sequence": 9, "event_hash": "sha256:" + "c" * 64},
                "state": {"revision": 7},
            }

    repository = ReadRepository()
    client_id = "client_00000000000000000000000000000000"
    export_id = "export_00000000000000000000000000000000"
    cycle_id = "cycle_00000000000000000000000000000000"
    conflicting_envelope_cycle_id = "cycle_11111111111111111111111111111111"
    stdout = io.StringIO()
    assert serve(
        "legacy-topic",
        report_path=tmp_path / "unused.md",
        wait_for_input=False,
        stdout=stdout,
        stdin=io.StringIO("\n".join([
            action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}),
            action("export.get", cycle_id=conflicting_envelope_cycle_id, payload={
                "client_instance_id": client_id, "request_ordinal": 1, "export_id": export_id,
                "include_archive_bytes": False,
            }),
            action("export.get", payload={
                "client_instance_id": client_id, "request_ordinal": 1, "export_id": export_id,
                "include_archive_bytes": False,
            }),
            action("report.render", cycle_id=conflicting_envelope_cycle_id, payload={
                "client_instance_id": client_id, "request_ordinal": 2, "cycle_id": cycle_id,
                "at_revision": 7, "format": "canonical_json", "include_status_overlay": False,
            }),
            action("export.get", payload={
                "client_instance_id": client_id, "request_ordinal": 3, "export_id": export_id,
                "include_archive_bytes": True,
            }),
        ]) + "\n"),
        scientific_mode=True,
        repository=repository,  # type: ignore[arg-type]
        scientific_config=NORMAL_CONFIG,
    ) == 0
    events = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert events[1]["cycle_id"] is None
    assert events[1]["payload"] == {
        "request_message_id": events[1]["correlation_id"],
        "export_id": export_id,
        "manifest": {"schema_version": "ai-scientist.handoff.v2"},
        "archive_hash": "sha256:" + "a" * 64,
        "byte_length": 7,
        "archive_base64": None,
    }
    assert events[2]["payload"]["stable_code"] == "validation_failed"
    assert events[3]["cycle_id"] == cycle_id
    assert events[3]["payload"]["body_hash"] == "sha256:" + "b" * 64
    assert events[4]["payload"]["stable_code"] == "export_too_large"
    assert repository.calls == [
        ("export", (export_id, False)),
        ("report", (cycle_id, {
            "at_revision": 7, "format": "canonical_json", "include_status_overlay": False,
        })),
        ("snapshot", cycle_id),
        ("export", (export_id, True)),
    ]
def test_signoff_scope_hashes_are_canonical_and_requirement_identity_binds_scope() -> None:
    core = SignoffCore("cycle_00000000000000000000000000000000")
    first = core.rescope(
        Responsibility.QUESTION_SELECTION,
        "claim_set",
        ("claim_00000000000000000000000000000000",),
    )
    second = core.rescope(
        Responsibility.QUESTION_SELECTION,
        "evidence_set",
        ("evidence_00000000000000000000000000000000",),
    )

    assert first.scope_hash != second.scope_hash
    assert first.requirement_id != second.requirement_id
    with pytest.raises(SignoffError, match="canonical scope"):
        core.rescope(
            Responsibility.QUESTION_SELECTION,
            "claim_set",
            ("claim_00000000000000000000000000000000",),
            "sha256:" + "0" * 64,
        )
    with pytest.raises(SignoffError, match="canonical scope"):
        SignoffCore.validate_disposition_input(
            requirement={
                "id": first.requirement_id,
                "responsibility": first.responsibility.value,
                "scope_kind": first.scope_kind,
                "scope_ids": list(first.scope_ids),
                "scope_hash": "sha256:" + "0" * 64,
            },
            existing_disposition=None,
            responsibility=first.responsibility.value,
            payload={
                "requirement_id": first.requirement_id,
                "scope_hash": "sha256:" + "0" * 64,
            },
        )
def test_completed_stage_rejects_organization_only_accountability() -> None:
    organization = CREATOR | {
        "actor_kind": "organization",
        "display_name": "Muchanipo Research",
        "organization": "Muchanipo Research",
    }
    stage_input = {
        "kind": "landscape.complete",
        "accountable_party": organization,
        "performers": [{"kind": "organization", "name": "Muchanipo Research", "version": None, "external_reference": None}],
        "execution_kind": "cognitive",
        "automation_mode": "manual",
        "boundary": {"kind": "cognitive_only", "description": "literature review"},
        "started_at": "2026-07-19T00:00:00.000000Z",
        "completed_at": "2026-07-19T00:00:01.000000Z",
        "invalidate_current_proposal": False,
        "landscape_artifacts": [{
            "title": "Landscape",
            "summary": "Committed source",
            "source_artifact_ids": [],
            "limitations": ["Unverified source"],
        }],
    }
    state = initial_state(
        "cycle_00000000000000000000000000000000",
        "Question?",
        "ai-scientist.v1",
        {"kind": "cognitive_only", "description": "local"},
        CREATOR,
    )

    with pytest.raises(GateUnsatisfied, match="human accountable party"):
        ScientificCycleReducer().apply(state, {
            "name": "cycle.continue",
            "payload": {
                "expected_revision": 0,
                "operation": "landscape.complete",
                "stage_input": stage_input,
            },
        })


def install_completion_dispositions(state: dict, final_details: dict[str, object]) -> None:
    state["question"] = "Question?"
    state["requirements"] = {}
    state["dispositions"] = {}
    for responsibility in Responsibility:
        requirement_id = "requirement-" + responsibility.value
        disposition_id = "disposition-" + responsibility.value
        details: dict[str, object] = {
            "selected_normalized_question": "Question?",
        } if responsibility is Responsibility.QUESTION_SELECTION else {}
        if responsibility is Responsibility.FINAL_ACCOUNTABILITY:
            requirement_id = "requirement-final"
            disposition_id = "disposition-final"
            details = final_details
        state["requirements"][responsibility.value] = requirement_id
        state["dispositions"][requirement_id] = disposition_id
        state["records"][requirement_id] = {
            "id": requirement_id,
            "content": {"scope_hash": "sha256:" + responsibility.value[0] * 64},
        }
        state["records"][disposition_id] = {
            "id": disposition_id,
            "content": {
                "requirement_id": requirement_id,
                "responsibility": responsibility.value,
                "scope_hash": "sha256:" + responsibility.value[0] * 64,
                "actor": {"actor_kind": "human"},
                "status": "satisfied",
                "details": details,
            },
        }


@pytest.mark.parametrize(
    "details",
    [
        {
            "report_body_id": "report-body-stale",
            "report_body_hash": "sha256:" + "a" * 64,
            "reviewed_exact_bytes": True,
            "limitations_acknowledged": True,
        },
        {
            "report_body_id": "report-body-current",
            "report_body_hash": "sha256:" + "b" * 64,
            "reviewed_exact_bytes": True,
            "limitations_acknowledged": True,
        },
    ],
)
def test_cycle_completion_requires_final_disposition_to_bind_current_report_body(
    details: dict[str, object],
) -> None:
    body_hash = "sha256:" + "a" * 64
    state = {
        "current": {"final_report": "stage-final"},
        "records": {
            "stage-final": {"id": "stage-final", "content": {"report_body_id": "report-body-current"}},
            "report-body-current": {
                "id": "report-body-current",
                "content": {"body_hash": body_hash},
            },
            "disposition-final": {
                "id": "disposition-final",
                "content": {"status": "satisfied", "details": details},
            },
        },
        "requirements": {Responsibility.FINAL_ACCOUNTABILITY.value: "requirement-final"},
        "dispositions": {"requirement-final": "disposition-final"},
        "terminal": None,
    }
    install_completion_dispositions(state, details)
    action_payload = {
        "expected_revision": 0,
        "operation": "cycle.complete",
        "stage_input": {
            "kind": "cycle.complete",
            "report_stage_id": "stage-final",
            "report_body_id": "report-body-current",
            "report_body_hash": body_hash,
            "final_accountability_requirement_id": "requirement-final",
            "final_accountability_disposition_id": "disposition-final",
        },
    }

    with pytest.raises(GateUnsatisfied, match="final accountability is not current"):
        ScientificCycleReducer().apply(state, {"name": "cycle.continue", "payload": action_payload})


def test_cycle_completion_accepts_final_disposition_bound_to_current_report_body() -> None:
    body_hash = "sha256:" + "a" * 64
    details = {
        "report_body_id": "report-body-current",
        "report_body_hash": body_hash,
        "reviewed_exact_bytes": True,
        "limitations_acknowledged": True,
    }
    state = {
        "current": {"final_report": "stage-final"},
        "records": {
            "stage-final": {"id": "stage-final", "content": {"report_body_id": "report-body-current"}},
            "report-body-current": {
                "id": "report-body-current",
                "content": {"body_hash": body_hash},
            },
            "disposition-final": {
                "id": "disposition-final",
                "content": {"status": "satisfied", "details": details},
            },
        },
        "requirements": {Responsibility.FINAL_ACCOUNTABILITY.value: "requirement-final"},
        "dispositions": {"requirement-final": "disposition-final"},
        "terminal": None,
    }
    install_completion_dispositions(state, details)

    reduction = ScientificCycleReducer().apply(state, {
        "name": "cycle.continue",
        "payload": {
            "expected_revision": 0,
            "operation": "cycle.complete",
            "stage_input": {
                "kind": "cycle.complete",
                "report_stage_id": "stage-final",
                "report_body_id": "report-body-current",
                "report_body_hash": body_hash,
                "final_accountability_requirement_id": "requirement-final",
                "final_accountability_disposition_id": "disposition-final",
            },
        },
    })

    assert reduction.state["terminal"] == "completed"
def test_verified_results_materialize_metadata_and_canonicalize_correction_lineage(tmp_path: Path) -> None:
    proposal_id = "proposal_0123456789abcdef0123456789abcdef"
    proposal_content = {"artifact_type": "proposal"}
    proposal_hash = byte_digest(canonical_json(proposal_content))
    state = initial_state(
        "cycle_0123456789abcdef0123456789abcdef",
        "Question?",
        "ai-scientist.v1",
        {"kind": "cognitive_only", "description": "local"},
        CREATOR,
    )
    state["records"][proposal_id] = {
        "id": proposal_id,
        "record_type": "proposal",
        "content": proposal_content,
        "content_hash": proposal_hash,
    }
    state["current"]["proposal"] = proposal_id
    approved = tmp_path / "approved"
    approved.mkdir()
    artifact_root = tmp_path / "artifacts"
    reference = {
        "reference_type": "lab_log", "issuer": "External Lab", "title": "Completed run",
        "uri_or_identifier": "lab-log-1", "content_hash": "sha256:" + "b" * 64,
        "assertion_source": "external_reference", "verification_status": "external_reference_unverified",
        "authority_scope": {"kind": "none", "scope": None},
    }

    def verified(name: str, metadata: dict, supersedes_result_id: str | None = None):
        staged = approved / name
        staged.write_bytes(name.encode("utf-8"))
        blob_suffix = name.encode("utf-8").hex().ljust(32, "0")[:32]
        return ingest_staged_external_result(
            state=state,
            staged_files=[staged],
            approved_roots=[approved],
            artifact_root=artifact_root,
            request={
                "proposal_id": proposal_id,
                "proposal_hash": proposal_hash,
                "execution_kind": "computational",
                "accountable_party": CREATOR,
                "performers": [{
                    "kind": "organization",
                    "name": "External Lab",
                    "version": None,
                    "external_reference": reference,
                }],
                "started_at": "2026-07-19T00:00:00.000000Z",
                "completed_at": "2026-07-19T01:00:00.000000Z",
                "external_references": [reference],
                "staged_blob_ids": [f"external_blob_{blob_suffix}"],
                "result_manifest": metadata,
                "deviations": [],
                "supersedes_result_id": supersedes_result_id,
            },
        )["result"]

    reducer = ScientificCycleReducer()
    imported = [verified("first.bin", {}), verified("second.bin", {"nested": {"values": [1, 2]}})]
    for result in sorted(imported, key=lambda item: item["id"], reverse=True):
        state = reducer.apply_verified_result(state, result).state

    assert state["current"]["results"] == sorted(item["id"] for item in imported)
    assert isinstance(state["records"][imported[1]["id"]]["content"]["result_manifest"]["nested"]["values"], list)

    superseded = state["current"]["results"][0]
    correction = verified("correction.bin", {"nested": {"corrected": True}}, superseded)
    state = reducer.apply_verified_result(state, correction).state

    expected_results = sorted(({item["id"] for item in imported} - {superseded}) | {correction["id"]})
    assert state["current"]["results"] == expected_results
    requirement = state["records"][state["requirements"][Responsibility.EXCEPTION_INTERPRETATION.value]]
    assert requirement["content"]["scope_ids"] == expected_results
def test_disposition_supersession_replaces_exact_scope_or_leaves_pending():
    reducer = ScientificCycleReducer()

    def seeded() -> tuple[dict, str, str]:
        state = initial_state(
            "cycle_" + "0" * 32, "Question?", "ai-scientist.v1",
            {"kind": "cognitive_only", "description": "local"}, CREATOR,
        )
        requirement_id = state["requirements"][Responsibility.QUESTION_SELECTION.value]
        scope_hash = state["records"][requirement_id]["content"]["scope_hash"]
        recorded = reducer.apply(state, {
            "name": "responsibility.question_selection.disposition",
            "payload": {
                "expected_revision": 0, "requirement_id": requirement_id,
                "scope_hash": scope_hash, "actor": CREATOR,
                "asserted_at": "2026-07-19T00:00:00.000000Z",
                "status": "satisfied", "rationale": "selected the question",
                "details": {
                    "selected_normalized_question": "Question?",
                    "rejected_alternatives": [],
                },
            },
        }).state
        return recorded, requirement_id, recorded["dispositions"][requirement_id]

    def supersede_payload(requirement_id: str, disposition_id: str, replacement: dict | None) -> dict:
        return {
            "expected_revision": 0,
            "responsibility": Responsibility.QUESTION_SELECTION.value,
            "requirement_id": requirement_id,
            "superseded_disposition_id": disposition_id,
            "rationale": "require a fresh decision",
            "replacement_disposition": replacement,
        }

    pending_state, old_requirement_id, old_disposition_id = seeded()
    pending = reducer.apply(
        pending_state, {"name": "responsibility.disposition.supersede",
                        "payload": supersede_payload(old_requirement_id, old_disposition_id, None)},
    )
    pending_requirement_id = pending.state["requirements"][Responsibility.QUESTION_SELECTION.value]
    assert pending_requirement_id != old_requirement_id
    assert pending_requirement_id not in pending.state["dispositions"]
    assert pending.state["records"][pending_requirement_id]["content"]["supersedes_requirement_id"] == old_requirement_id
    assert set(pending.event_payload) == {
        "responsibility", "old_requirement_id", "new_requirement_id",
        "superseded_disposition_id", "replacement_disposition_id", "created_records",
        "superseded_record_ids", "derived_current_refs",
    }

    replacement_state, old_requirement_id, old_disposition_id = seeded()
    replacement = {
        "expected_revision": 0, "requirement_id": pending_requirement_id,
        "scope_hash": pending.state["records"][pending_requirement_id]["content"]["scope_hash"],
        "actor": CREATOR, "asserted_at": "2026-07-19T00:00:00.000000Z",
        "status": "satisfied", "rationale": "fresh decision",
        "details": {"selected_normalized_question": "Question?", "rejected_alternatives": []},
    }
    replaced = reducer.apply(
        replacement_state, {"name": "responsibility.disposition.supersede",
                            "payload": supersede_payload(old_requirement_id, old_disposition_id, replacement)},
    )
    assert replaced.state["requirements"][Responsibility.QUESTION_SELECTION.value] == pending_requirement_id
    replacement_disposition_id = replaced.state["dispositions"][pending_requirement_id]
    assert replaced.event_payload["replacement_disposition_id"] == replacement_disposition_id
    assert replaced.event_payload["created_records"] == [pending_requirement_id, replacement_disposition_id]
    assert replaced.state["records"][replacement_disposition_id]["content"]["requirement_id"] == pending_requirement_id

    state, requirement_id, disposition_id = seeded()
    with pytest.raises(GateUnsatisfied, match="requirement is not current"):
        reducer.apply(state, {"name": "responsibility.disposition.supersede", "payload": supersede_payload(
            requirement_id[:-1] + "1", disposition_id, None,
        )})
    with pytest.raises(GateUnsatisfied, match="disposition is not current"):
        reducer.apply(state, {"name": "responsibility.disposition.supersede", "payload": supersede_payload(
            requirement_id, disposition_id[:-1] + "1", None,
        )})
    wrong_scope = {**replacement, "scope_hash": "sha256:" + "f" * 64}
    with pytest.raises(GateUnsatisfied, match="scope hash"):
        reducer.apply(state, {"name": "responsibility.disposition.supersede", "payload": supersede_payload(
            requirement_id, disposition_id, wrong_scope,
        )})
    wrong_role = {**replacement, "details": {
        "proposal_id": "proposal_00000000000000000000000000000000",
        "proposal_hash": "sha256:" + "1" * 64, "risk_findings": [],
        "export_only_boundary_confirmed": True,
    }}
    with pytest.raises(GateUnsatisfied, match="details are frozen"):
        reducer.apply(state, {"name": "responsibility.disposition.supersede", "payload": supersede_payload(
            requirement_id, disposition_id, wrong_role,
        )})