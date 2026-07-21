from __future__ import annotations

import copy
import pytest

from src.pipeline.scientific_cycle import GateUnsatisfied, ScientificCycleReducer, initial_state
from src.pipeline.scientific_contracts import ContractError, Responsibility, byte_digest, canonical_json, validate_continue_payload
from src.report.scientific_projector import ScientificReportProjector


CYCLE_ID = "cycle_00000000000000000000000000000000"


def actor() -> dict[str, object]:
    return {"actor_kind": "human", "display_name": "Operator", "organization": None, "role": "reviewer",
            "assertion_source": "operator_entry", "verification_status": "operator_asserted_unverified",
            "authority_scope": {"kind": "none", "scope": None}, "external_reference": None}


def boundary() -> dict[str, str]:
    return {"kind": "cognitive_only", "description": "cognitive only"}


def state():
    return initial_state(CYCLE_ID, "Question?", "ai-scientist.v1", boundary(), actor())


def stage(kind: str, **extra: object) -> dict[str, object]:
    return {"kind": kind, "accountable_party": actor(),
            "performers": [{"kind": "human", "name": "Operator", "version": None, "external_reference": None}],
            "execution_kind": "cognitive", "automation_mode": "manual", "boundary": boundary(),
            "started_at": "2026-07-19T00:00:00.000000Z", "completed_at": "2026-07-19T00:00:01.000000Z", **extra}


def continue_action(operation: str, input: dict[str, object]) -> dict[str, object]:
    return {"name": "cycle.continue", "payload": {"expected_revision": 0, "operation": operation, "stage_input": input}}


def landscape() -> dict[str, object]:
    return stage("landscape.complete", invalidate_current_proposal=False, landscape_artifacts=[{
        "title": "Landscape", "summary": "Committed sources", "source_artifact_ids": [], "limitations": ["Unverified sources"]
    }])


def claim() -> dict[str, object]:
    return {
        "artifact_type": "claim",
        "statement": "Claim",
        "falsification_criteria": "Measure outcome",
        "evidence_artifact_ids": [],
        "parent_claim_ids": [],
        "rank": 1,
        "limitations": [
            "Unvalidated candidate; rank is prioritization, not support.",
            "Evidence text is explicitly unlinked to committed artifacts.",
        ],
    }

def novelty_disposition(requirement_id: str, scope_hash: str, claim_ids: list[str]) -> dict[str, object]:
    return {
        "expected_revision": 0, "requirement_id": requirement_id, "actor": actor(),
        "asserted_at": "2026-07-19T00:00:00.000000Z", "status": "satisfied",
        "rationale": "Reviewed current claim.", "scope_hash": scope_hash,
        "details": {"claim_ids": claim_ids, "judgment": "Novel", "limitations": ["Unverified"]},
    }



def test_forged_verified_authority_is_rejected_at_ingress():
    forged = actor() | {"verification_status": "verified"}
    with pytest.raises(ContractError, match="invalid actor assertion"):
        initial_state(CYCLE_ID, "Question?", "ai-scientist.v1", boundary(), forged)


def test_named_landscape_and_claim_records_are_immutable_and_current():
    reducer = ScientificCycleReducer()
    first = reducer.apply(state(), continue_action("landscape.complete", landscape()))
    first_state_bytes = canonical_json(first.state)
    prior_records = copy.deepcopy(first.state["records"])

    second = reducer.apply(first.state, continue_action("hypothesis.complete", stage(
        "hypothesis.complete", invalidate_current_proposal=False, claims=[claim()])))
    records = second.state["records"]
    landscape_stage = records[first.result["stage_id"]]
    hypothesis_stage = records[second.result["stage_id"]]
    assert canonical_json(first.state) == first_state_bytes
    assert {record_id: records[record_id] for record_id in prior_records} == prior_records
    assert landscape_stage["content"]["artifact_ids"]
    assert hypothesis_stage["content"]["artifact_ids"] == second.state["current"]["claims"]
    assert all(records[record_id]["record_type"] in {"landscape_artifact", "claim"}
               for record_id in landscape_stage["content"]["artifact_ids"] + hypothesis_stage["content"]["artifact_ids"])


def test_claim_change_rescopes_and_rejects_stale_disposition_target():
    reducer = ScientificCycleReducer()
    current = reducer.apply(state(), continue_action("landscape.complete", landscape())).state
    current = reducer.apply(current, continue_action("hypothesis.complete", stage(
        "hypothesis.complete", invalidate_current_proposal=False, claims=[claim()]))).state
    old_requirement = current["requirements"]["novelty_value_judgment"]
    old_content = current["records"][old_requirement]["content"]
    updated = reducer.apply(current, continue_action("hypothesis.complete", stage(
        "hypothesis.complete", invalidate_current_proposal=False,
        claims=[claim() | {"statement": "Replacement claim"}]))).state
    new_requirement = updated["requirements"]["novelty_value_judgment"]
    assert new_requirement != old_requirement
    assert updated["records"][new_requirement]["content"]["supersedes_requirement_id"] == old_requirement
    with pytest.raises(GateUnsatisfied, match="disposition is stale"):
        reducer.apply(updated, {
            "name": "responsibility.novelty_value_judgment.disposition",
            "payload": novelty_disposition(old_requirement, old_content["scope_hash"], current["current"]["claims"]),
        })
    assert new_requirement not in updated["dispositions"]


def test_execution_not_run_becomes_current_export_handoff_stage():
    reducer = ScientificCycleReducer()
    current = reducer.apply(state(), continue_action("landscape.complete", landscape())).state
    current = reducer.apply(current, continue_action("hypothesis.complete", stage(
        "hypothesis.complete", invalidate_current_proposal=False, claims=[claim()]
    ))).state
    claims = current["current"]["claims"]
    proposal_reduction = reducer.apply(current, continue_action("proposal.complete", stage(
        "proposal.complete",
        proposal={
            "claim_ids": claims,
            "risks": ["External execution risk"],
            "acceptance_criteria": ["Externally reviewed result"],
            "handoff_boundary": {"kind": "export_only", "description": "external handoff only"},
        },
    )))
    proposal_id = proposal_reduction.state["current"]["proposal"]
    proposal = proposal_reduction.state["records"][proposal_id]
    not_run = {
        "kind": "execution.not_run",
        "proposal_id": proposal_id,
        "proposal_hash": proposal["content_hash"],
        "status": "not_run",
        "execution_kind": "not_run",
        "accountable_party": None,
        "performers": [],
        "automation_mode": "not_run",
        "boundary": {"kind": "export_only", "description": "external handoff only"},
        "started_at": None,
        "completed_at": None,
        "artifact_ids": [],
        "result_ids": [],
    }
    reduced = reducer.apply(
        proposal_reduction.state,
        continue_action("execution.not_run", not_run),
    )
    assert reduced.state["current"]["local_x"][proposal_id] == reduced.result["stage_id"]
def test_direct_result_submission_is_denied_without_repository_ingest_receipt():
    with pytest.raises(GateUnsatisfied, match="repository-owned verified import"):
        ScientificCycleReducer().apply(
            state(),
            {"name": "result.submit", "payload": {"controlled_import": {}}},
        )


def test_analysis_rejects_noncurrent_result_lineage_after_result_gate_is_available():
    reducer = ScientificCycleReducer()
    current = state()
    with pytest.raises(GateUnsatisfied, match="repository-owned verified import"):
        reducer.apply(current, {"name": "result.submit", "payload": {"controlled_import": {}}})

    committed = state()
    result_id = "controlled_import_result_00000000000000000000000000000000"
    committed["records"][result_id] = {
        "id": result_id, "record_type": "controlled_import_result", "content_hash": "sha256:" + "1" * 64,
        "content": {"fixture": "repository-committed receipt only"},
    }
    committed["current"]["results"] = [result_id]
    before = copy.deepcopy(committed)
    with pytest.raises(GateUnsatisfied, match="analysis must bind current results"):
        reducer.apply(committed, continue_action("analysis.complete", stage(
            "analysis.complete", result_ids=["controlled_import_result_11111111111111111111111111111111"],
            analysis_artifacts=[{"result_ids": [result_id], "claim_ids": [], "method": "Analysis",
                                 "findings": "Finding", "limitations": ["Unverified"]}])))
    assert committed == before


def test_report_bytes_are_reducer_derived_from_committed_projection():
    input = stage("write.interim", source_revision=0, source_artifact_ids=[], claim_ids=[], result_ids=[],
                  analysis_artifact_ids=[], limitations=["Committed limitation"])
    validate_continue_payload({"expected_revision": 0, "operation": "write.interim", "stage_input": input})
    with pytest.raises(ContractError):
        validate_continue_payload({"expected_revision": 0, "operation": "write.interim", "stage_input": input | {"projection": {}}})

    committed = state()
    committed["records"]["claim_fixture"] = {"record_type": "claim", "content": {"statement": "Committed claim"}}
    current_assessment = {
        "id": "assessment_fixture",
        "record_type": "validation_assessment",
        "content": {"assessment_state": "accepted"},
    }
    committed["records"]["assessment_fixture"] = current_assessment
    committed["assessments"]["assessment_fixture"] = current_assessment
    final_requirement = committed["requirements"]["final_accountability"]
    committed["records"][final_requirement]["content"]["final_accountability_nested"] = {"fabricated": "excluded"}
    report = ScientificReportProjector().compose_from_state(
        state=committed, source_revision=0, body_kind="interim", limitations=("Committed limitation",))
    import json
    decoded = json.loads(report.body_utf8)
    assert decoded["scientific"] == {"claim_fixture": {"statement": "Committed claim"}}
    assert decoded["validation"] == {"assessment_fixture": {"assessment_state": "accepted"}}
    assert "final_accountability" not in decoded["responsibilities"]["requirements"]
    assert b"final_accountability_nested" not in report.body_utf8
    assert report.body_hash == byte_digest(report.body_utf8)
def test_write_final_installs_exact_report_body_scope():
    committed = state()
    proposal_id = "proposal_11111111111111111111111111111111"
    analysis_id = "stage_22222222222222222222222222222222"
    artifact_id = "analysis_artifact_33333333333333333333333333333333"
    committed["records"][proposal_id] = {
        "id": proposal_id,
        "record_type": "proposal",
        "content": {},
    }
    committed["records"][artifact_id] = {
        "id": artifact_id,
        "record_type": "analysis_artifact",
        "content": {},
    }
    committed["records"][analysis_id] = {
        "id": analysis_id,
        "record_type": "stage",
        "content": {"artifact_ids": [artifact_id]},
    }
    committed["current"]["proposal"] = proposal_id
    committed["current"]["analysis"] = analysis_id

    reduction = ScientificCycleReducer().apply(
        committed,
        continue_action(
            "write.final",
            stage(
                "write.final",
                source_revision=0,
                source_artifact_ids=[],
                claim_ids=[],
                result_ids=[],
                analysis_artifact_ids=[artifact_id],
                limitations=["External results remain unverified."],
            ),
        ),
    )

    requirement_id = reduction.state["requirements"]["final_accountability"]
    requirement = reduction.state["records"][requirement_id]["content"]
    report_stage = reduction.state["records"][reduction.state["current"]["final_report"]]
    report_body = reduction.state["records"][report_stage["content"]["report_body_id"]]
    assert requirement["scope_kind"] == "report_body"
    assert requirement["scope_ids"] == [
        report_body["id"],
        report_body["content"]["body_hash"],
    ]
def completion_state() -> tuple[dict, dict[str, object]]:
    current = state()
    report_body_id = "report_body_11111111111111111111111111111111"
    report_stage_id = "stage_22222222222222222222222222222222"
    report_hash = "sha256:" + "a" * 64
    current["current"]["final_report"] = report_stage_id
    current["records"][report_body_id] = {"id": report_body_id, "content": {"body_hash": report_hash}}
    current["records"][report_stage_id] = {"id": report_stage_id, "content": {"report_body_id": report_body_id}}
    for responsibility in Responsibility:
        requirement_id = current["requirements"][responsibility.value]
        disposition_id = f"disposition_{responsibility.value}_11111111111111111111111111111111"
        details: dict[str, object] = {}
        status = "satisfied"
        if responsibility is Responsibility.QUESTION_SELECTION:
            details = {"selected_normalized_question": current["question"]}
        elif responsibility is Responsibility.EXCEPTION_INTERPRETATION:
            status = "not_applicable"
            details = {"no_exception_assertion": True, "deviations": []}
        elif responsibility is Responsibility.FINAL_ACCOUNTABILITY:
            details = {
                "report_body_id": report_body_id,
                "report_body_hash": report_hash,
                "reviewed_exact_bytes": True,
                "limitations_acknowledged": True,
            }
        current["records"][disposition_id] = {
            "id": disposition_id,
            "content": {
                "requirement_id": requirement_id,
                "responsibility": responsibility.value,
                "scope_hash": current["records"][requirement_id]["content"]["scope_hash"],
                "actor": {"actor_kind": "human"},
                "status": status,
                "details": details,
            },
        }
        current["dispositions"][requirement_id] = disposition_id
    return current, {
        "report_stage_id": report_stage_id,
        "report_body_id": report_body_id,
        "report_body_hash": report_hash,
        "final_accountability_requirement_id": current["requirements"][Responsibility.FINAL_ACCOUNTABILITY.value],
        "final_accountability_disposition_id": current["dispositions"][current["requirements"][Responsibility.FINAL_ACCOUNTABILITY.value]],
    }


@pytest.mark.parametrize("responsibility", list(Responsibility))
def test_completion_lifecycle_matrix_requires_each_current_human_gate(responsibility: Responsibility):
    reducer = ScientificCycleReducer()
    complete, data = completion_state()
    assert reducer._complete(copy.deepcopy(complete), data).state["terminal"] == "completed"

    requirement_id = complete["requirements"][responsibility.value]
    disposition_id = complete["dispositions"][requirement_id]
    invalid = copy.deepcopy(complete)
    invalid["records"][disposition_id]["content"]["status"] = "declined"
    with pytest.raises(GateUnsatisfied, match=responsibility.value):
        reducer._complete(invalid, data)

    stale = copy.deepcopy(complete)
    stale["dispositions"].pop(requirement_id)
    with pytest.raises(GateUnsatisfied, match=responsibility.value):
        reducer._complete(stale, data)
    superseded = copy.deepcopy(complete)
    superseded_requirement_id = requirement_id + "-replacement"
    superseded["records"][superseded_requirement_id] = {
        "id": superseded_requirement_id,
        "content": {"scope_hash": superseded["records"][requirement_id]["content"]["scope_hash"]},
    }
    superseded["requirements"][responsibility.value] = superseded_requirement_id
    with pytest.raises(GateUnsatisfied, match=responsibility.value):
        reducer._complete(superseded, data)

    nonhuman = copy.deepcopy(complete)
    nonhuman["records"][disposition_id]["content"]["actor"] = {"actor_kind": "organization"}
    with pytest.raises(GateUnsatisfied, match=responsibility.value):
        reducer._complete(nonhuman, data)


def test_completion_rejects_not_applicable_outside_exception_interpretation():
    complete, data = completion_state()
    responsibility = Responsibility.SAFETY_ETHICS_REVIEW
    requirement_id = complete["requirements"][responsibility.value]
    complete["records"][complete["dispositions"][requirement_id]]["content"]["status"] = "not_applicable"
    with pytest.raises(GateUnsatisfied, match=responsibility.value):
        ScientificCycleReducer()._complete(complete, data)

def disposition_payload(requirement_id: str, scope_hash: str, details: dict[str, object]) -> dict[str, object]:
    return {
        "expected_revision": 0, "requirement_id": requirement_id, "actor": actor(),
        "asserted_at": "2026-07-19T00:00:00.000000Z", "status": "satisfied",
        "rationale": "Reviewed.", "scope_hash": scope_hash, "details": details,
    }


def test_export_ready_tracks_reducer_export_gates_without_mutation():
    reducer = ScientificCycleReducer()
    current = reducer.apply(state(), continue_action("landscape.complete", landscape())).state
    assert reducer.export_ready(current) is False
    current = reducer.apply(current, continue_action("hypothesis.complete", stage(
        "hypothesis.complete", invalidate_current_proposal=False, claims=[claim()]))).state
    claims = current["current"]["claims"]
    current = reducer.apply(current, continue_action("proposal.complete", stage(
        "proposal.complete",
        proposal={
            "claim_ids": claims,
            "risks": ["External execution risk"],
            "acceptance_criteria": ["Externally reviewed result"],
            "handoff_boundary": {"kind": "export_only", "description": "external handoff only"},
        },
    ))).state
    proposal_id = current["current"]["proposal"]
    proposal_hash = current["records"][proposal_id]["content_hash"]
    current = reducer.apply(current, continue_action("execution.not_run", {
        "kind": "execution.not_run", "proposal_id": proposal_id, "proposal_hash": proposal_hash,
        "status": "not_run", "execution_kind": "not_run", "accountable_party": None, "performers": [],
        "automation_mode": "not_run", "boundary": {"kind": "export_only", "description": "external handoff only"},
        "started_at": None, "completed_at": None, "artifact_ids": [], "result_ids": [],
    })).state
    assert reducer.export_ready(current) is False

    def scope(responsibility: str) -> tuple[str, str]:
        requirement_id = current["requirements"][responsibility]
        return requirement_id, current["records"][requirement_id]["content"]["scope_hash"]

    question_requirement, question_scope = scope("question_selection")
    current = reducer.apply(current, {
        "name": "responsibility.question_selection.disposition",
        "payload": disposition_payload(question_requirement, question_scope, {
            "selected_normalized_question": current["question"], "rejected_alternatives": [],
        }),
    }).state
    assert reducer.export_ready(current) is False
    safety_requirement, safety_scope = scope("safety_ethics_review")
    current = reducer.apply(current, {
        "name": "responsibility.safety_ethics_review.disposition",
        "payload": disposition_payload(safety_requirement, safety_scope, {
            "proposal_id": proposal_id, "proposal_hash": proposal_hash,
            "risk_findings": ["External execution risk"], "export_only_boundary_confirmed": True,
        }),
    }).state
    assert reducer.export_ready(current) is False
    execution_requirement, execution_scope = scope("execution_accountability")
    current = reducer.apply(current, {
        "name": "responsibility.execution_accountability.disposition",
        "payload": disposition_payload(execution_requirement, execution_scope, {
            "proposal_id": proposal_id, "proposal_hash": proposal_hash,
            "handoff_owner": actor(),
            "execution_boundary": {"kind": "export_only", "description": "external execution only"},
        }),
    }).state

    before_readiness_check = canonical_json(current)
    assert reducer.export_ready(current) is True
    assert canonical_json(current) == before_readiness_check

    aborted = reducer.apply(current, {
        "name": "cycle.abort",
        "payload": {"expected_revision": 0, "actor": actor(), "reason": "stop", "final_observation": "none"},
    }).state
    assert reducer.export_ready(aborted) is False
