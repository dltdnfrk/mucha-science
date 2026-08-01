from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.pipeline.scientific_contracts import ContractError, canonical_json
from src.platform_contracts import (
    ALL_ENUM_TYPES,
    ApprovalStatus,
    AssayCondition,
    AssayObservation,
    Claim,
    ClaimEvidenceLink,
    ClaimOrigin,
    CandidateRankingDecision,
    Constraint,
    Measurement,
    ObjectiveEvaluation,
    ObjectiveTerm,
    Prediction,
    QualityGateResult,
    SourceRecord,
    SourceSpan,
    UserQueryRevision,
)

TS = "2026-08-01T00:00:00.000000Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64

CONTENTS: dict[type[object], dict[str, object]] = {
    ObjectiveTerm: {
        "term_id": "potency",
        "objective_ref": {"id": "objective.potency", "version": "1", "sha256": HASH_A},
        "weight_units": 3,
        "parameters": {"direction": "higher", "bounds": {"max": "10", "min": "0"}},
    },
    Constraint: {
        "constraint_id": "synthesis",
        "owner": "PLATFORM_POLICY",
        "metric_ref": "metric.synthesis",
        "operator": "GTE",
        "threshold": {"value": "0.75", "unit": "probability"},
        "policy_ref": "safety-policy-v1",
    },
    ObjectiveEvaluation: {
        "objective_term_id": "potency",
        "status": "SCORED",
        "utility_ppm": 900_000,
        "gate_result_ids": ["gate-1"],
        "prediction_lineage_ref": "pred-1",
    },
    QualityGateResult: {
        "gate_id": "gate-1",
        "policy_ref": {"version": "structure-v1", "sha256": HASH_A},
        "subject_prediction_id": "pred-1",
        "metric": "structure_confidence",
        "observed_value": "0.42",
        "threshold_or_predicate": {"operator": "GTE", "value": "0.80"},
        "outcome": "FAIL",
        "reason": "LOW_STRUCTURE_CONFIDENCE",
    },
    CandidateRankingDecision: {
        "candidate_id": "candidate-1",
        "query_revision_id": "query-revision-1",
        "disposition": "RANKED",
        "objective_evaluations": [{
            "objective_term_id": "potency",
            "status": "SCORED",
            "utility_ppm": 900_000,
            "gate_result_ids": ["gate-1"],
            "prediction_lineage_ref": "pred-1",
        }],
        "abstention_reasons": [],
        "gate_result_ids": ["gate-1"],
        "required_next_evidence": [],
        "composite_score_ppm": 900_000,
    },
    UserQueryRevision: {
        "query_id": "query-1",
        "parent_revision_id": None,
        "application_type": "CONTAINED_LAB",
        "objectives": [{
            "term_id": "potency",
            "objective_ref": {"id": "objective.potency", "version": "1", "sha256": HASH_A},
            "weight_units": 3,
            "parameters": {"bounds": {"min": "0", "max": "10"}, "direction": "higher"},
        }],
        "user_constraints": [],
        "change_set": ["ADD_OBJECTIVE"],
        "actor": "scientist-1",
        "created_at": TS,
    },
    AssayObservation: {
        "evidence_tier": "PURIFIED_ENZYME",
        "origin": "PLATFORM_ASSAY",
        "candidate_id": "candidate-1",
        "target_id": "target-1",
        "endpoint_ref": "endpoint.ic50",
        "assay_condition_id": "condition-1",
        "result": {"kind": "POINT", "value": "2.5", "unit": "uM"},
        "raw_artifact_refs": ["artifact-1"],
        "replicate_group_ref": None,
        "source_record_id": None,
        "assay_started_at": TS,
        "observed_at": TS,
        "qc_status": "PASS",
    },
    Prediction: {
        "prediction_series_id": "series-1",
        "origin": "PLATFORM_COMPUTATION",
        "estimand": {"candidate_id": "candidate-1", "target_id": "target-1", "endpoint_ref": "endpoint.ic50", "unit": "uM", "condition_scope_hash": HASH_A},
        "result": {"kind": "POINT", "value": "2.0"},
        "issued_at": TS,
        "locked_at": TS,
        "invocation_lineage_hash": HASH_A,
        "revision": 1,
        "recomputes_prediction_id": None,
        "predictor_signature": HASH_A,
        "input_hashes": [HASH_A],
        "uncertainty": {"lower": "1.5", "upper": "2.5"},
        "objective_normalizer_hash": HASH_B,
        "calibration_model_hash": None,
        "epistemic_status": "RANKABLE_PREDICTION",
    },
    Measurement: {
        "observation_id": "observation-1",
        "originating_prediction_id": "prediction-1",
        "pairing_design": "PROSPECTIVE_LOCKED",
        "pair_relation": "DIRECT_ESTIMAND",
        "benchmark_split_role": "NONE",
        "pair_created_at": TS,
        "compatibility_check_ref": "compatibility-check-1",
    },
    SourceRecord: {
        "source_kind": "PUBLICATION",
        "namespace": "doi",
        "accession": "10.1000/example",
        "source_release": "2026-01",
        "version_status": "PINNED",
        "schema_version": "csl-1.0.2",
        "api_version": "v1",
        "canonical_uri": "https://doi.org/10.1000/example",
        "retrieved_at": TS,
        "artifact": {"sha256": HASH_A, "media_type": "application/pdf", "byte_size": 42},
        "license": {"expression": "CC-BY-4.0", "terms_uri": None, "terms_snapshot_sha256": None, "decision": "ALLOWED", "restrictions": [], "decided_by": None, "decided_at": None},
        "citation": {"id": "example", "title": "Example"},
        "provenance": {"parent_source_ids": [], "adapter_invocation_id": None},
    },
    AssayCondition: {
        "protocol_source_id": None,
        "assay_type_ref": "assay.binding",
        "matrix": {"vocabulary_term": "buffer", "source_or_species": None, "lot_or_batch": None, "preparation": "fresh"},
        "test_system": {"organism_or_isolate_refs": [], "inoculum": None, "candidate_concentration": "2 uM"},
        "environment": {"temperature": "298 K", "duration": "1 h", "pH": "7.4", "sampling_schedule": None},
        "modifiers": [{"role": "BUFFER", "substance_ref_or_name": "PBS", "concentration": "1x"}],
        "controls": {"reporting_status": "REPORTED", "definitions": [{"type": "NEGATIVE", "material_ref_or_description": "vehicle", "expected_outcome": "no signal"}]},
        "replication": {"reporting_status": "REPORTED", "biological_n": 3, "technical_n": 2, "unit_of_replication": "well", "randomization": "blocked", "blinding": "single"},
        "instrument_or_method_ref": "method-1",
    },
    SourceSpan: {
        "source_id": "source-1",
        "artifact_sha256": HASH_A,
        "selector": {"type": "UTF8_BYTE_RANGE", "value": {"start": 0, "end": 12}},
        "quoted_text_sha256": HASH_B,
        "quoted_text": "example text",
    },
    ClaimEvidenceLink: {
        "source_span": {
            "source_id": "source-1", "artifact_sha256": HASH_A,
            "selector": {"type": "JSON_POINTER", "value": "/results/0"},
            "quoted_text_sha256": HASH_B, "quoted_text": None,
        },
        "entailment": "ENTAILED",
        "applicability": "DIRECT",
        "verifier": {"method": "HUMAN", "version": "1", "verified_by": "reviewer-1", "verified_at": TS},
    },
    Claim: {
        "proposition": {"display_text": "Candidate inhibits target", "subject_refs": ["candidate-1"], "predicate_ref": "inhibits", "object": {"target_ref": "target-1"}, "qualifiers": {}},
        "origin": "LITERATURE_EXTRACTION",
        "source_links": [{
            "source_span": {"source_id": "source-1", "artifact_sha256": HASH_A, "selector": {"type": "TABLE_CELL", "value": {"row": 2, "column": 3}}, "quoted_text_sha256": HASH_B, "quoted_text": "2.5 uM"},
            "entailment": "ENTAILED", "applicability": "DIRECT",
            "verifier": {"method": "HUMAN", "version": "1", "verified_by": "reviewer-1", "verified_at": TS},
        }],
        "supporting_record_refs": ["observation-1"],
        "status": "SUPPORTED",
        "approval": {"status": "APPROVED", "actor": "reviewer-1", "decided_at": TS},
        "supersedes_claim_id": None,
    },
}


@pytest.mark.parametrize("record_type,content", CONTENTS.items(), ids=lambda item: getattr(item, "__name__", "content"))
def test_every_record_round_trips_and_has_stable_content_identity(record_type: type[object], content: dict[str, object]) -> None:
    first = record_type.from_content(content)  # type: ignore[attr-defined]
    second = record_type.from_content(dict(reversed(tuple(content.items()))))  # type: ignore[attr-defined]

    assert first == second
    assert first.content_hash == second.content_hash  # type: ignore[attr-defined]
    assert first.record_id == second.record_id  # type: ignore[attr-defined]
    assert record_type.from_payload(first.to_payload()) == first  # type: ignore[attr-defined]
    assert record_type.from_json(first.to_json()) == first  # type: ignore[attr-defined]
    assert first.to_json() == canonical_json(first.to_payload())  # type: ignore[attr-defined]

    changed = dict(content)
    if record_type is ClaimEvidenceLink:
        changed["verifier"] = {**content["verifier"], "verified_by": "reviewer-2"}  # type: ignore[dict-item]
    elif record_type is Claim:
        changed["proposition"] = {**content["proposition"], "display_text": "Different proposition"}  # type: ignore[dict-item]
    else:
        identity_fields = {
            ObjectiveTerm: "term_id", Constraint: "constraint_id",
            ObjectiveEvaluation: "objective_term_id", QualityGateResult: "gate_id",
            CandidateRankingDecision: "candidate_id", UserQueryRevision: "query_id",
            AssayObservation: "endpoint_ref", Prediction: "prediction_series_id",
            Measurement: "observation_id", SourceRecord: "namespace",
            AssayCondition: "assay_type_ref", SourceSpan: "source_id",
        }
        field = identity_fields[record_type]
        changed[field] = f"{content[field]}-changed"
    assert record_type.from_content(changed).content_hash != first.content_hash  # type: ignore[attr-defined]


def test_all_declared_enums_reject_unknown_values() -> None:
    assert len(ALL_ENUM_TYPES) == 31
    for enum_type in ALL_ENUM_TYPES:
        assert tuple(enum_type)
        with pytest.raises(ValueError):
            enum_type("NOT_A_REAL_VALUE")


@pytest.mark.parametrize("record_type,content", CONTENTS.items(), ids=lambda item: getattr(item, "__name__", "content"))
def test_every_payload_validator_rejects_missing_and_extra_fields(record_type: type[object], content: dict[str, object]) -> None:
    missing = dict(content)
    missing.pop(next(iter(missing)))
    with pytest.raises(ContractError):
        record_type.from_content(missing)  # type: ignore[attr-defined]
    with pytest.raises(ContractError):
        record_type.from_content({**content, "unexpected": True})  # type: ignore[attr-defined]


def test_prediction_cannot_be_assigned_an_evidence_tier() -> None:
    with pytest.raises(ContractError):
        Prediction.from_content({**CONTENTS[Prediction], "evidence_tier": "PURIFIED_ENZYME"})


def test_conflicting_applicable_source_links_cannot_claim_supported_status() -> None:
    contradicted_link = {
        **CONTENTS[ClaimEvidenceLink],
        "entailment": "CONTRADICTED",
    }
    conflicting = {
        **CONTENTS[Claim],
        "source_links": [CONTENTS[ClaimEvidenceLink], contradicted_link],
        "status": "SUPPORTED",
    }

    with pytest.raises(ContractError, match="derived source-link status MIXED"):
        Claim.from_content(conflicting)

    valid = Claim.from_content({**conflicting, "status": "MIXED"})
    with pytest.raises(ContractError, match="derived source-link status MIXED"):
        Claim.from_payload({**valid.to_payload(), "status": "SUPPORTED"})


def test_council_claim_cannot_be_assigned_an_evidence_tier() -> None:
    council = {**CONTENTS[Claim], "origin": ClaimOrigin.COUNCIL.value, "source_links": [], "status": "UNKNOWN", "approval": {"status": ApprovalStatus.APPROVED.value, "actor": "reviewer-1", "decided_at": TS}}
    Claim.from_content(council)
    with pytest.raises(ContractError):
        Claim.from_content({**council, "evidence_tier": "PURIFIED_ENZYME"})


def test_nested_enum_and_shape_validation_is_strict() -> None:
    invalid = [
        (AssayObservation, {**CONTENTS[AssayObservation], "evidence_tier": "UNKNOWN_TIER"}),
        (Constraint, {**CONTENTS[Constraint], "operator": "NE"}),
        (SourceRecord, {**CONTENTS[SourceRecord], "license": {**CONTENTS[SourceRecord]["license"], "decision": "MAYBE"}}),  # type: ignore[index]
        (AssayCondition, {**CONTENTS[AssayCondition], "controls": {"reporting_status": "REPORTED", "definitions": [{"type": "PLACEBO", "material_ref_or_description": "x", "expected_outcome": "y"}]}}),
        (SourceSpan, {**CONTENTS[SourceSpan], "selector": {"type": "LINE_RANGE", "value": "1-2"}}),
    ]
    for record_type, content in invalid:
        with pytest.raises(ContractError):
            record_type.from_content(content)


def test_records_are_frozen_and_ids_are_verified_on_deserialization() -> None:
    prediction = Prediction.from_content(CONTENTS[Prediction])
    with pytest.raises(FrozenInstanceError):
        prediction.revision = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        prediction.result["value"] = "tampered"  # type: ignore[index]
    with pytest.raises(ContractError):
        Prediction.from_payload({**prediction.to_payload(), "prediction_id": "pred_tampered"})


def test_canonical_json_is_independent_of_nested_dictionary_order() -> None:
    left = ObjectiveTerm.from_content(CONTENTS[ObjectiveTerm])
    reordered = {
        **CONTENTS[ObjectiveTerm],
        "parameters": {"bounds": {"min": "0", "max": "10"}, "direction": "higher"},
    }
    right = ObjectiveTerm.from_content(reordered)
    assert left.to_json() == right.to_json()
