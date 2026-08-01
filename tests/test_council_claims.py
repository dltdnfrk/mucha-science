from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.platform_contracts import (
    ApprovalStatus,
    ClaimEvidenceLink,
    ClaimOrigin,
    SourceSpan,
)
from src.research_integration import (
    ClaimDisplayClass,
    PackReflectionError,
    approve_claim,
    claim_display_class,
    claims_from_council_output,
    literature_claim,
    reflect_claim_into_pack,
)

TS = "2026-08-01T00:00:00.000000Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _proposition(text: str = "Candidate inhibits target") -> dict[str, object]:
    return {
        "display_text": text,
        "subject_refs": ["candidate-1"],
        "predicate_ref": "inhibits",
        "object": {"target_ref": "target-1"},
        "qualifiers": {},
    }


def _link(entailment: str, applicability: str = "DIRECT", source: str = "source-1") -> ClaimEvidenceLink:
    span = SourceSpan.from_content(
        {
            "source_id": source,
            "artifact_sha256": HASH_A,
            "selector": {"type": "UTF8_BYTE_RANGE", "value": {"start": 0, "end": 12}},
            "quoted_text_sha256": HASH_B,
            "quoted_text": "candidate inhibits target",
        }
    )
    return ClaimEvidenceLink.from_content(
        {
            "source_span": span.to_content(),
            "entailment": entailment,
            "applicability": applicability,
            "verifier": {
                "method": "HUMAN",
                "version": "1",
                "verified_by": "reviewer-1",
                "verified_at": TS,
            },
        }
    )


def test_round_result_shape_converts_each_deliberated_statement_to_pending_council_claim() -> None:
    round_result = SimpleNamespace(
        layer_id="L4_risk",
        chapter_title="Risk",
        key_claim="The proposed route needs containment.",
        body_claims=["A release assay should precede scale-up."],
        evidence_ref_ids=["council-ref-1"],
        confidence_score=0.72,
        disagreements=["Containment level remains disputed."],
        next_actions=["Specify release criteria."],
    )

    claims = claims_from_council_output(round_result)

    assert [claim.proposition["display_text"] for claim in claims] == [
        "The proposed route needs containment.",
        "A release assay should precede scale-up.",
    ]
    assert all(claim.origin is ClaimOrigin.COUNCIL for claim in claims)
    assert all(claim.approval["status"] == ApprovalStatus.PENDING.value for claim in claims)
    assert all(claim.status.value == "UNKNOWN" for claim in claims)
    assert all(claim.source_links == () for claim in claims)
    assert all(claim.supporting_record_refs == ("council-ref-1",) for claim in claims)


def test_council_session_shape_uses_consensus_without_running_pipeline() -> None:
    session_output = SimpleNamespace(
        report_id="report-1",
        council_id="council-report-1",
        consensus="Proceed only after validating the containment boundary.",
        rounds=[],
        disagreements=["Validation scope is unresolved."],
        next_actions=["Define validation scope."],
    )

    (claim,) = claims_from_council_output(session_output)

    assert claim.proposition["display_text"] == session_output.consensus
    assert claim.proposition["qualifiers"]["council_id"] == "council-report-1"


@pytest.mark.parametrize(
    "forbidden_field,forbidden_value",
    [("evidence_tier", "PURIFIED_ENZYME"), ("is_empirical_evidence", True)],
)
def test_council_conversion_rejects_empirical_evidence_classification(
    forbidden_field: str, forbidden_value: object
) -> None:
    output = {
        "key_claim": "A reasoning-only claim.",
        "body_claims": [],
        forbidden_field: forbidden_value,
    }

    with pytest.raises(ValueError, match="Council claims cannot be empirical evidence"):
        claims_from_council_output(output)


def test_human_approval_permits_workflow_use_but_never_adds_an_evidence_tier() -> None:
    pending = claims_from_council_output({"key_claim": "Review this recommendation."})[0]

    approved = approve_claim(pending, actor="scientist-1", decided_at=TS)

    assert approved.approval == {
        "status": ApprovalStatus.APPROVED.value,
        "actor": "scientist-1",
        "decided_at": TS,
    }
    assert approved.source_links == ()
    assert "evidence_tier" not in approved.to_payload()
    with pytest.raises(TypeError):
        approve_claim(pending, actor="scientist-1", decided_at=TS, evidence_tier="LYSATE")  # type: ignore[call-arg]


def test_literature_claim_requires_applicable_entailment_to_be_supported() -> None:
    supported = literature_claim(_proposition(), [_link("ENTAILED", "DIRECT")])
    inapplicable = literature_claim(_proposition(), [_link("ENTAILED", "OUT_OF_SCOPE")])

    assert supported.status.value == "SUPPORTED"
    assert inapplicable.status.value == "UNKNOWN"


def test_literature_conflicts_are_mixed_even_when_entailing_spans_are_majority() -> None:
    links = [
        _link("ENTAILED", source="source-1"),
        _link("ENTAILED", source="source-2"),
        _link("CONTRADICTED", source="source-3"),
    ]

    claim = literature_claim(_proposition(), links)

    assert claim.status.value == "MIXED"


def test_literature_not_enough_information_is_unknown() -> None:
    claim = literature_claim(
        _proposition(),
        [_link("ENTAILED"), _link("NOT_ENOUGH_INFORMATION", source="source-2")],
    )

    assert claim.status.value == "UNKNOWN"


def test_display_class_distinguishes_literature_from_council_reasoning() -> None:
    literature = literature_claim(_proposition(), [_link("ENTAILED")])
    council = claims_from_council_output({"key_claim": "Reasoned recommendation."})[0]

    assert claim_display_class(literature) is ClaimDisplayClass.LITERATURE_BACKED
    assert claim_display_class(council) is ClaimDisplayClass.REASONING


def test_pack_reflection_admits_only_approved_claims() -> None:
    pending = claims_from_council_output({"key_claim": "Review before pack use."})[0]
    approved = approve_claim(pending, actor="scientist-1", decided_at=TS)

    payload = reflect_claim_into_pack(approved, {"domain": "enzyme-design", "knowledge": []})

    assert payload["domain"] == "enzyme-design"
    assert payload["knowledge"] == [
        {"claim": approved.to_payload(), "display_class": ClaimDisplayClass.REASONING.value}
    ]
    with pytest.raises(PackReflectionError, match="APPROVED"):
        reflect_claim_into_pack(pending, {"knowledge": []})


def test_pack_reflection_refuses_rejected_claim() -> None:
    pending = claims_from_council_output({"key_claim": "Do not use this."})[0]
    rejected_content = pending.to_content()
    rejected_content["approval"] = {
        "status": ApprovalStatus.REJECTED.value,
        "actor": "scientist-1",
        "decided_at": TS,
    }
    rejected = type(pending).from_content(rejected_content)

    with pytest.raises(PackReflectionError, match="APPROVED"):
        reflect_claim_into_pack(rejected, {"knowledge": []})
