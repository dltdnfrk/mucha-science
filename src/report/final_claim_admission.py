"""Fail-closed admission for claims that appear in the final report."""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Any

from src.evidence.artifact import EvidenceRef
from src.research.evaluation import ClaimLabel, classify_claim_evidence


@unique
class FinalClaimStatus(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient"
    EVIDENCE_GAP = "evidence_gap"


@dataclass(frozen=True, slots=True)
class FinalClaimCandidate:
    chapter_no: int
    claim: str
    evidence_ids: tuple[str, ...] = ()
    material: bool = True

    def __post_init__(self) -> None:
        if self.chapter_no < 1:
            raise ValueError("final claim chapter number must be positive")
        if not self.claim.strip():
            raise ValueError("final claim text must not be empty")
        object.__setattr__(self, "claim", " ".join(self.claim.split()))
        object.__setattr__(self, "evidence_ids", tuple(dict.fromkeys(self.evidence_ids)))


@dataclass(frozen=True, slots=True)
class FinalClaimVerdict:
    claim_id: str
    chapter_no: int
    claim: str
    material: bool
    status: FinalClaimStatus
    evidence_ids: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...] = ()
    refuting_evidence_ids: tuple[str, ...] = ()
    insufficient_evidence_ids: tuple[str, ...] = ()
    missing_evidence_ids: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "chapter_no": self.chapter_no,
            "claim": self.claim,
            "material": self.material,
            "status": self.status.value,
            "evidence_ids": list(self.evidence_ids),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "refuting_evidence_ids": list(self.refuting_evidence_ids),
            "insufficient_evidence_ids": list(self.insufficient_evidence_ids),
            "missing_evidence_ids": list(self.missing_evidence_ids),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class FinalClaimAdmission:
    rows: tuple[FinalClaimVerdict, ...]

    @property
    def material_rows(self) -> tuple[FinalClaimVerdict, ...]:
        return tuple(row for row in self.rows if row.material)

    @property
    def supported_count(self) -> int:
        return sum(row.status is FinalClaimStatus.SUPPORTED for row in self.material_rows)

    @property
    def contradicted_count(self) -> int:
        return sum(row.status is FinalClaimStatus.CONTRADICTED for row in self.material_rows)

    @property
    def conflicting_count(self) -> int:
        return sum(row.status is FinalClaimStatus.CONFLICTING for row in self.material_rows)

    @property
    def insufficient_count(self) -> int:
        return sum(row.status is FinalClaimStatus.INSUFFICIENT for row in self.material_rows)

    @property
    def supported_ratio(self) -> float:
        if not self.material_rows:
            return 1.0
        return self.supported_count / len(self.material_rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": len(self.rows),
            "material_claim_count": len(self.material_rows),
            "supported_count": self.supported_count,
            "contradicted_count": self.contradicted_count,
            "conflicting_count": self.conflicting_count,
            "insufficient_count": self.insufficient_count,
            "supported_ratio": round(self.supported_ratio, 3),
            "rows": [row.to_dict() for row in self.rows],
        }


def adjudicate_final_claims(
    candidates: Sequence[FinalClaimCandidate],
    evidence_refs: Sequence[EvidenceRef],
    *,
    eligible_evidence_ids: Iterable[str] | None = None,
) -> FinalClaimAdmission:
    """Adjudicate each emitted claim against source text, never citation presence.

    This deterministic verifier is intentionally conservative. It is the local
    fail-closed baseline before any optional model-based verifier.
    """

    refs_by_id = {reference.id: reference for reference in evidence_refs}
    eligible = set(eligible_evidence_ids) if eligible_evidence_ids is not None else None
    occurrences: Counter[tuple[int, str]] = Counter()
    rows: list[FinalClaimVerdict] = []
    for candidate in candidates:
        key = (candidate.chapter_no, candidate.claim)
        occurrences[key] += 1
        claim_id = _claim_id(candidate, occurrences[key])
        if not candidate.material:
            rows.append(
                FinalClaimVerdict(
                    claim_id=claim_id,
                    chapter_no=candidate.chapter_no,
                    claim=candidate.claim,
                    material=False,
                    status=FinalClaimStatus.EVIDENCE_GAP,
                    evidence_ids=(),
                    reason="claim is an explicit evidence gap or process disclosure",
                )
            )
            continue

        support: list[str] = []
        refute: list[str] = []
        insufficient: list[str] = []
        missing: list[str] = []
        projected: list[str] = []
        for evidence_id in candidate.evidence_ids:
            reference = refs_by_id.get(evidence_id)
            if reference is None or (eligible is not None and evidence_id not in eligible):
                missing.append(evidence_id)
                continue
            projected.append(evidence_id)
            source_text = _source_text(reference)
            label = classify_claim_evidence(candidate.claim, source_text)
            if label is ClaimLabel.SUPPORTS:
                support.append(evidence_id)
            elif label is ClaimLabel.REFUTES:
                refute.append(evidence_id)
            else:
                insufficient.append(evidence_id)

        if support and refute:
            status = FinalClaimStatus.CONFLICTING
            reason = "eligible evidence both supports and refutes the final claim"
        elif refute:
            status = FinalClaimStatus.CONTRADICTED
            reason = "eligible evidence refutes the final claim"
        elif support:
            status = FinalClaimStatus.SUPPORTED
            reason = "at least one eligible source span supports the final claim"
        else:
            status = FinalClaimStatus.INSUFFICIENT
            reason = (
                "cited evidence is missing or does not semantically support the final claim"
                if candidate.evidence_ids
                else "final claim has no cited evidence"
            )

        rows.append(
            FinalClaimVerdict(
                claim_id=claim_id,
                chapter_no=candidate.chapter_no,
                claim=candidate.claim,
                material=True,
                status=status,
                evidence_ids=tuple(projected),
                supporting_evidence_ids=tuple(support),
                refuting_evidence_ids=tuple(refute),
                insufficient_evidence_ids=tuple(insufficient),
                missing_evidence_ids=tuple(missing),
                reason=reason,
            )
        )
    return FinalClaimAdmission(rows=tuple(rows))


def enforce_final_claim_admission(
    admission: FinalClaimAdmission,
    *,
    depth: str,
    require_live: bool,
) -> dict[str, Any]:
    """Block strict/live publication unless every material claim is supported."""

    strict = require_live or str(depth or "").strip().casefold() in {"max", "superdeep"}
    passed = (
        bool(admission.rows)
        and admission.contradicted_count == 0
        and admission.conflicting_count == 0
        and admission.insufficient_count == 0
        and admission.supported_ratio == 1.0
    )
    summary = {"passed": passed, "strict": strict, **admission.to_dict()}
    if strict and not passed:
        from src.research.karpathy_autoresearch import SourceAuditViolation

        blocked = next(
            (
                row
                for row in admission.material_rows
                if row.status is not FinalClaimStatus.SUPPORTED
            ),
            None,
        )
        detail = blocked.claim[:160] if blocked is not None else "no final claim rows"
        raise SourceAuditViolation(f"final claim admission blocked: {detail}")
    return summary


def _claim_id(candidate: FinalClaimCandidate, occurrence: int) -> str:
    payload = f"{candidate.chapter_no}\n{candidate.claim}\n{occurrence}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"final-claim-{digest}"


def _source_text(reference: EvidenceRef) -> str:
    provenance = reference.provenance or {}
    quote = str(reference.quote or "").strip()
    if quote:
        return quote
    return str(provenance.get("source_text") or "").strip()
