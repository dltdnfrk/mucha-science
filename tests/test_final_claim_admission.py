from __future__ import annotations

import pytest

from src.evidence.artifact import EvidenceRef
from src.report.final_claim_admission import (
    FinalClaimCandidate,
    FinalClaimStatus,
    adjudicate_final_claims,
    enforce_final_claim_admission,
)
from src.research.karpathy_autoresearch import SourceAuditViolation


def _evidence(identifier: str, quote: str) -> EvidenceRef:
    return EvidenceRef(
        id=identifier,
        source_url=f"https://doi.org/10.1000/{identifier}",
        source_title="Independent study",
        quote=quote,
        source_grade="A",
        provenance={"kind": "paper"},
    )


def test_final_claim_admission_rejects_same_topic_evidence_swap() -> None:
    reference = _evidence(
        "swap",
        "The study measured user satisfaction but did not report error reduction.",
    )

    admission = adjudicate_final_claims(
        (
            FinalClaimCandidate(
                chapter_no=2,
                claim="The intervention reduced error by 18%.",
                evidence_ids=("swap",),
            ),
        ),
        (reference,),
    )

    row = admission.rows[0]
    assert row.status is FinalClaimStatus.INSUFFICIENT
    assert row.supporting_evidence_ids == ()
    assert row.insufficient_evidence_ids == ("swap",)
    with pytest.raises(SourceAuditViolation, match="final claim admission blocked"):
        enforce_final_claim_admission(admission, depth="max", require_live=True)


def test_final_claim_admission_surfaces_korean_contradiction() -> None:
    reference = _evidence("korean-refute", "약물 X는 혈압을 높인다")

    admission = adjudicate_final_claims(
        (
            FinalClaimCandidate(
                chapter_no=3,
                claim="약물 X는 혈압을 낮춘다",
                evidence_ids=("korean-refute",),
            ),
        ),
        (reference,),
    )

    row = admission.rows[0]
    assert row.status is FinalClaimStatus.CONTRADICTED
    assert row.refuting_evidence_ids == ("korean-refute",)
    assert admission.contradicted_count == 1


def test_final_claim_admission_cites_only_semantically_supporting_evidence() -> None:
    support = _evidence(
        "support",
        "The randomized trial reported an 18% reduction in error.",
    )
    unrelated = _evidence("unrelated", "Cats sleep for many hours.")

    admission = adjudicate_final_claims(
        (
            FinalClaimCandidate(
                chapter_no=4,
                claim="The intervention reduced error by 18%.",
                evidence_ids=("support", "unrelated"),
            ),
        ),
        (support, unrelated),
    )

    row = admission.rows[0]
    assert row.status is FinalClaimStatus.SUPPORTED
    assert row.supporting_evidence_ids == ("support",)
    assert row.insufficient_evidence_ids == ("unrelated",)
    assert row.claim_id.startswith("final-claim-")


def test_final_claim_admission_allows_explicit_evidence_gap_without_fake_citation() -> None:
    admission = adjudicate_final_claims(
        (
            FinalClaimCandidate(
                chapter_no=5,
                claim="추가 검증이 필요한 위험 가설",
                evidence_ids=(),
                material=False,
            ),
        ),
        (),
    )

    row = admission.rows[0]
    assert row.status is FinalClaimStatus.EVIDENCE_GAP
    assert row.evidence_ids == ()
    assert enforce_final_claim_admission(
        admission,
        depth="max",
        require_live=True,
    )["passed"] is True
