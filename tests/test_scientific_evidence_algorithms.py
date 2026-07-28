import copy
import json
from pathlib import Path

import pytest

import src.evidence.scientific_validation as scientific_validation
import src.pipeline.scientific_contracts as scientific_contracts
from src.council.schema import validate_council_report_v3
from src.evidence.artifact import EvidenceRef, Finding
from src.report.claim_matrix import build_claim_evidence_matrix


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "scientific_evidence_algorithms.v1.json"
CASE_IDS = (
    "exact",
    "paraphrase",
    "negation",
    "number_unit_mismatch",
    "population_comparator_time_mismatch",
    "support_refute",
    "unavailable",
    "stale",
    "retracted",
    "provider_partial_failure",
    "completed_one_batch_no_novelty",
    "cancellation_forbidden_late_completion",
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _base_report() -> dict:
    return {
        "schema_version": "v0.4.0",
        "personas": [{
            "agent_manifest": {
                "intent": "adjudicate evidence",
                "allowed_tools": ["read"],
                "required_outputs": ["claims"],
                "token_budget": 100,
                "reliability_score": 0.8,
            },
        }],
        "rounds": [{
            "stop_reason": "complete",
            "context_checksum": "sha256:test",
            "convergence": {
                "consensus_score": 1,
                "ambiguity": 0,
                "coverage": 1,
                "contradiction_count": 0,
                "confidence_mad": 0,
                "belief_delta": 0,
                "dominant_position_ratio": 1,
                "can_stop": True,
            },
            "ratchet": {
                "decision": "keep",
                "effect_size_mad": 0,
                "ratchet_score": 1,
                "deltas": [],
            },
        }],
        "citation_grounding": {
            "verified_claim_ratio": 1,
            "total_claim_count": 1,
            "unsupported_critical_claim_count": 0,
            "per_claim_verdict": [{
                "claim_id": "claim_66666666666666666666666666666666",
                "text": "The intervention changed the outcome.",
                "is_critical": True,
                "supporting_evidence_ids": [
                    "evidence_66666666666666666666666666666661",
                ],
                "verification_status": "supported",
            }],
        },
        "evidence": [{
            "id": "evidence_66666666666666666666666666666661",
            "type": "text",
            "source": "publisher",
            "quote": "changed",
            "quote_span": [0, 7],
            "hash": "sha256:support",
            "fetched_at": "2026-07-26T00:00:00Z",
        }],
        "final": {
            "scores": {
                "axes": {},
                "total": 1,
                "rubric_max": 1,
                "verdict": "PASS",
                "verdict_reason": "fixture",
            },
            "vault_metadata": {},
            "cost_trace": {},
        },
    }


def _case(case_id: str) -> dict:
    return next(case for case in _fixture()["cases"] if case["case_id"] == case_id)


def _required_callable(module, name: str):
    candidate = getattr(module, name, None)
    assert callable(candidate), f"missing required scientific-evidence API: {name}"
    return candidate


def test_fixture_freezes_exactly_the_approved_twelve_cases_without_automatic_nli() -> None:
    fixture = _fixture()

    assert fixture["schema_version"] == "scientific-evidence-algorithms.v1"
    assert fixture["polarity_source"] == "adjudicated"
    assert fixture["automatic_nli"] is False
    assert tuple(case["case_id"] for case in fixture["cases"]) == CASE_IDS
    assert all("adjudicated_supporting_evidence_ids" in case for case in fixture["cases"][:6])
    assert all("adjudicated_refuting_evidence_ids" in case for case in fixture["cases"][:6])


def test_cases_one_through_six_derive_stance_only_from_adjudicated_polarity() -> None:
    derive_stance = _required_callable(scientific_contracts, "derive_evidence_stance")

    for case in _fixture()["cases"][:6]:
        stance = derive_stance(
            case["adjudicated_supporting_evidence_ids"],
            case["adjudicated_refuting_evidence_ids"],
        )
        assert stance.value == case["expected_stance"]


def test_mixed_case_has_order_independent_deterministic_contradiction_id() -> None:
    relationship_id = _required_callable(
        scientific_contracts,
        "contradiction_relationship_id",
    )
    case = _case("support_refute")

    forward = relationship_id(
        case["claim_id"],
        case["adjudicated_supporting_evidence_ids"],
        case["adjudicated_refuting_evidence_ids"],
    )
    reverse = relationship_id(
        case["claim_id"],
        list(reversed(case["adjudicated_supporting_evidence_ids"])),
        list(reversed(case["adjudicated_refuting_evidence_ids"])),
    )

    assert forward == case["expected_contradiction_relationship_id"]
    assert reverse == forward


def test_lifecycle_mapping_preserves_state_and_projects_only_four_stances() -> None:
    stance_from_lifecycle = _required_callable(
        scientific_validation,
        "stance_from_lifecycle",
    )
    support_status = getattr(scientific_validation, "SupportStatus")

    for case in _fixture()["cases"][:10]:
        lifecycle_state = support_status(case["lifecycle_state"])
        assert lifecycle_state.value == case["lifecycle_state"]
        assert stance_from_lifecycle(lifecycle_state).value == case["expected_stance"]


def test_legacy_and_additive_reports_validate_without_migration() -> None:
    legacy = _base_report()
    assert validate_council_report_v3(legacy) == (True, [])

    additive = copy.deepcopy(legacy)
    additive["evidence"].append({
        "id": "evidence_66666666666666666666666666666662",
        "type": "text",
        "source": "publisher",
        "quote": "did not change",
        "quote_span": [8, 22],
        "hash": "sha256:refute",
        "fetched_at": "2026-07-26T00:00:00Z",
        "work_id": "doi:10.1234/example",
        "representation_id": "doi:10.1234/example@publisher-vor",
        "source_locator": {"kind": "html_anchor", "value": "results/table-2"},
        "dependence_group_id": "study:nct00000001",
        "publication_status": "published",
        "integrity_status": "no_notice_found",
        "integrity_checked_at": "2026-07-26T00:00:00Z",
        "integrity_source": "crossref:10.1234/example",
    })
    claim = additive["citation_grounding"]["per_claim_verdict"][0]
    claim.update({
        "refuting_evidence_ids": [
            "evidence_66666666666666666666666666666662",
        ],
        "stance": "mixed",
        "contradiction_relationship_id": _case("support_refute")[
            "expected_contradiction_relationship_id"
        ],
        "uncertainty": {
            "evidence_coverage": "moderate",
            "measurement": "unknown",
            "population_applicability": "high",
            "causal_identification": "high",
            "publication_integrity": "not_checked",
        },
    })

    assert validate_council_report_v3(additive) == (True, [])


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        ("missing_evidence", "does not reference report.evidence"),
        ("numeric_uncertainty", "must be one of"),
        ("malformed_locator", "source_locator must be an object"),
        ("retracted_without_notice", "integrity_source missing"),
    ),
)
def test_additive_report_fails_closed_for_invalid_relationships_and_metadata(
    mutation: str,
    expected_error: str,
) -> None:
    report = _base_report()
    claim = report["citation_grounding"]["per_claim_verdict"][0]
    evidence = report["evidence"][0]
    if mutation == "missing_evidence":
        claim["refuting_evidence_ids"] = ["evidence_99999999999999999999999999999999"]
    elif mutation == "numeric_uncertainty":
        claim["uncertainty"] = {
            "evidence_coverage": 0.8,
            "measurement": "unknown",
            "population_applicability": "unknown",
            "causal_identification": "unknown",
            "publication_integrity": "not_checked",
        }
    elif mutation == "malformed_locator":
        evidence["source_locator"] = "https://example.test/paper"
    else:
        evidence.update({
            "integrity_status": "retracted",
            "integrity_checked_at": "2026-07-26T00:00:00Z",
        })

    ok, errors = validate_council_report_v3(report)

    assert ok is False
    assert any(expected_error in error for error in errors)


def test_uncertainty_is_ordinal_and_rejects_probability_like_numbers() -> None:
    uncertainty_type = getattr(scientific_contracts, "OrdinalUncertainty", None)
    uncertainty_level = getattr(scientific_contracts, "UncertaintyLevel", None)
    assert uncertainty_type is not None, "missing required OrdinalUncertainty contract"
    assert uncertainty_level is not None, "missing required UncertaintyLevel contract"

    uncertainty = uncertainty_type(
        uncertainty_level.MODERATE,
        uncertainty_level.UNKNOWN,
        uncertainty_level.HIGH,
        uncertainty_level.HIGH,
        uncertainty_level.NOT_CHECKED,
    )
    assert uncertainty.evidence_coverage.value == "moderate"
    with pytest.raises(scientific_contracts.ContractError):
        uncertainty_type(0.8, "unknown", "unknown", "unknown", "not_checked")


def test_claim_matrix_additively_projects_stance_and_refuting_ids() -> None:
    reference = EvidenceRef(
        id="evidence-support",
        source_url="https://doi.org/10.1234/support",
        source_title="Support",
        quote="supports",
        source_grade="A",
        provenance={"kind": "paper"},
    )

    row = build_claim_evidence_matrix(
        [Finding("supported claim", [reference], confidence=0.9)],
        [reference],
    ).rows[0]

    assert row.stance == "supports_claim"
    assert row.refuting_source_ids == ()
    assert row.to_dict()["refuting_evidence_ids"] == []


def test_operational_oracles_freeze_partial_no_novelty_and_cancellation_edges() -> None:
    partial = _case("provider_partial_failure")
    outcomes = {item["outcome"] for item in partial["provider_outcomes"]}
    assert outcomes == {"completed", "failed"}
    assert partial["expected_provider_aggregate"] == "partial"
    assert partial["expected_run_state"] == "needs_review"

    no_novelty = _case("completed_one_batch_no_novelty")
    assert no_novelty["counter_batch_complete"] is True
    assert all(
        not no_novelty[field]
        for field in (
            "accepted_source_additions",
            "accepted_claim_additions",
            "contradiction_additions",
        )
    )
    assert no_novelty["expected_stop_allowed"] is True

    cancelled = _case("cancellation_forbidden_late_completion")
    assert cancelled["cancel_request_accepted"] is True
    assert cancelled["termination_observed"] is True
    assert cancelled["late_completion_attempted"] is True
    assert cancelled["expected_late_completion_accepted"] is False
