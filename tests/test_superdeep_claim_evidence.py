from __future__ import annotations

import pytest

from src.evidence.artifact import EvidenceRef, Finding
from src.report.claim_matrix import build_claim_evidence_matrix, enforce_claim_evidence_gate
from src.research.karpathy_autoresearch import (
    SourceAuditViolation,
    build_research_quality_audit,
)
from src.research.planner import ResearchPlan


TOPIC = "딸기 농가용 저비용 분자진단 키트 시장성"


def _ref(
    ref_id: str,
    *,
    title: str,
    quote: str,
    kind: str = "web",
    url: str = "https://example.org/source",
) -> EvidenceRef:
    return EvidenceRef(
        id=ref_id,
        source_url=url,
        source_title=title,
        quote=quote,
        source_grade="B",
        provenance={"kind": kind, "metadata": {"query": TOPIC, "source_text": quote}},
        access_status="abstract_only",
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        brief_id="brief-superdeep-claim-evidence",
        topic_anchor=TOPIC,
        queries=[
            TOPIC,
            f"{TOPIC} peer reviewed LAMP PCR plant pathogen field validation",
            f"{TOPIC} Korea farmer adoption pricing market statistics",
        ],
        evidence_targets=["market adoption", "field validation"],
    )


def test_claim_evidence_gate_requires_each_atomic_claim_to_have_non_mock_citation() -> None:
    refs = [
        _ref(
            "paper-1",
            title="Strawberry LAMP field validation",
            quote="A strawberry plant disease LAMP assay reported field validation sensitivity and specificity metrics.",
            kind="academic",
        )
    ]
    findings = [
        Finding(
            claim="A strawberry plant disease LAMP assay reported field validation sensitivity and specificity metrics.",
            support=refs,
            confidence=0.8,
        ),
        Finding(
            claim="Korean farms will buy the kit at high margins without further evidence.",
            support=[],
            confidence=0.2,
        ),
    ]

    matrix = build_claim_evidence_matrix(findings, refs)

    assert matrix.unsupported_count == 1
    with pytest.raises(SourceAuditViolation, match="unsupported claim blocked report"):
        enforce_claim_evidence_gate(matrix, depth="superdeep")


def test_claim_evidence_gate_does_not_count_rejected_sources_as_supported() -> None:
    refs = [
        _ref(
            "bad-search-echo",
            title=TOPIC,
            quote="검색 결과 페이지가 제출된 딸기 농가용 저비용 분자진단 키트 시장성 쿼리를 반복한다.",
            kind="government",
            url="https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=strawberry-diagnostics-market",
        )
    ]
    findings = [
        Finding(
            claim="A search-results page cannot prove strawberry diagnostics market demand.",
            support=refs,
            confidence=0.8,
        )
    ]
    audit = build_research_quality_audit(findings, _plan())
    accepted_ids = {item.source_id for item in audit.source_evaluations if item.accepted}

    matrix = build_claim_evidence_matrix(findings, refs, accepted_evidence_ids=accepted_ids)
    summary = enforce_claim_evidence_gate(matrix, depth="shallow")

    assert accepted_ids == set()
    assert matrix.supported_count == 0
    assert matrix.partial_count == 1
    assert summary["passed"] is False
