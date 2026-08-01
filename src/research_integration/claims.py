"""Research-facing construction and admission rules for canonical claims."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum

from src.platform_contracts import (
    ApprovalStatus,
    Claim,
    ClaimEvidenceLink,
    ClaimOrigin,
    SourceSpan,
    derive_claim_status,
)


class ClaimDisplayClass(StrEnum):
    """UI-safe distinction between sourced literature and reasoning outputs."""

    LITERATURE_BACKED = "literature-backed"
    REASONING = "reasoning"


class PackReflectionError(ValueError):
    """Raised when a claim is not eligible for domain-pack reflection."""


_FORBIDDEN_COUNCIL_EVIDENCE_FIELDS = frozenset(
    {
        "evidence_tier",
        "empirical_evidence",
        "is_empirical_evidence",
        "source_link",
        "source_links",
        "source_span",
        "entailment",
    }
)
def claims_from_council_output(output: object) -> tuple[Claim, ...]:
    """Convert a ``RoundResult`` or ``CouncilSession``-shaped output to Claims.

    Council evidence reference IDs are retained only as provenance record
    references. They are never converted to source spans or evidence tiers.
    """

    _reject_empirical_council_fields(output)
    statements = _council_statements(output)
    if not statements:
        raise ValueError("Council output contains no claim or consensus")

    claims: list[Claim] = []
    for text, context in statements:
        claims.append(
            Claim.from_content(
                {
                    "proposition": {
                        "display_text": text,
                        "subject_refs": _subject_refs(context),
                        "predicate_ref": "council.reasoning",
                        "object": {"statement": text},
                        "qualifiers": _council_qualifiers(context),
                    },
                    "origin": ClaimOrigin.COUNCIL.value,
                    "source_links": [],
                    "supporting_record_refs": _strings(
                        _value(context, "evidence_ref_ids", [])
                    ),
                    "status": "UNKNOWN",
                    "approval": {
                        "status": ApprovalStatus.PENDING.value,
                        "actor": None,
                        "decided_at": None,
                    },
                    "supersedes_claim_id": None,
                }
            )
        )
    return tuple(claims)


def approve_claim(claim: Claim, *, actor: str, decided_at: str) -> Claim:
    """Return an approved canonical claim without changing its evidence class."""

    if claim.approval["status"] != ApprovalStatus.PENDING.value:
        raise ValueError("only a PENDING claim can be approved")
    content = claim.to_content()
    content["approval"] = {
        "status": ApprovalStatus.APPROVED.value,
        "actor": actor,
        "decided_at": decided_at,
    }
    return Claim.from_content(content)


def literature_claim(
    proposition: Mapping[str, object],
    source_links: Sequence[ClaimEvidenceLink],
    *,
    supporting_record_refs: Sequence[str] = (),
    approval_status: ApprovalStatus = ApprovalStatus.PENDING,
    approval_actor: str | None = None,
    decided_at: str | None = None,
    supersedes_claim_id: str | None = None,
) -> Claim:
    """Build a literature claim and derive status without evidence voting."""

    links = tuple(source_links)
    for link in links:
        if not isinstance(link, ClaimEvidenceLink) or not isinstance(link.source_span, SourceSpan):
            raise TypeError("source_links must contain ClaimEvidenceLink records with SourceSpan records")

    status = derive_claim_status(links).value
    return Claim.from_content(
        {
            "proposition": dict(proposition),
            "origin": ClaimOrigin.LITERATURE_EXTRACTION.value,
            "source_links": [link.to_content() for link in links],
            "supporting_record_refs": list(supporting_record_refs),
            "status": status,
            "approval": {
                "status": approval_status.value,
                "actor": approval_actor,
                "decided_at": decided_at,
            },
            "supersedes_claim_id": supersedes_claim_id,
        }
    )


def claim_display_class(claim: Claim) -> ClaimDisplayClass:
    """Return the presentation class without changing the Claim contract."""

    if claim.origin is ClaimOrigin.LITERATURE_EXTRACTION:
        return ClaimDisplayClass.LITERATURE_BACKED
    return ClaimDisplayClass.REASONING


def reflect_claim_into_pack(
    claim: Claim, domain_pack_payload: Mapping[str, object]
) -> dict[str, object]:
    """Append an approved claim to a domain-pack knowledge payload.

    The input mapping and its knowledge list are not mutated.
    """

    if claim.approval["status"] != ApprovalStatus.APPROVED.value:
        raise PackReflectionError("domain-pack reflection requires an APPROVED claim")
    existing = domain_pack_payload.get("knowledge", [])
    if not isinstance(existing, (list, tuple)):
        raise TypeError("domain-pack knowledge must be an array")
    knowledge = list(existing)
    knowledge.append(
        {
            "claim": claim.to_payload(),
            "display_class": claim_display_class(claim).value,
        }
    )
    return {**domain_pack_payload, "knowledge": knowledge}


def _reject_empirical_council_fields(value: object) -> None:
    if isinstance(value, Mapping):
        forbidden = _FORBIDDEN_COUNCIL_EVIDENCE_FIELDS.intersection(value)
        if forbidden:
            fields = ", ".join(sorted(forbidden))
            raise ValueError(f"Council claims cannot be empirical evidence ({fields})")
        for nested_key in ("rounds", "results"):
            nested = value.get(nested_key)
            if isinstance(nested, (list, tuple)):
                for item in nested:
                    _reject_empirical_council_fields(item)
        return

    attributes = vars(value) if hasattr(value, "__dict__") else {}
    forbidden = _FORBIDDEN_COUNCIL_EVIDENCE_FIELDS.intersection(attributes)
    if forbidden:
        fields = ", ".join(sorted(forbidden))
        raise ValueError(f"Council claims cannot be empirical evidence ({fields})")
    for nested_key in ("rounds", "results"):
        nested = attributes.get(nested_key)
        if isinstance(nested, (list, tuple)):
            for item in nested:
                _reject_empirical_council_fields(item)


def _council_statements(output: object) -> list[tuple[str, object]]:
    consensus = _text(_value(output, "consensus", None))
    if consensus:
        return [(consensus, output)]

    direct = _direct_statements(output)
    if direct:
        return [(statement, output) for statement in direct]

    statements: list[tuple[str, object]] = []
    rounds = _value(output, "rounds", [])
    if isinstance(rounds, (list, tuple)):
        for round_output in rounds:
            nested = _council_statements(round_output)
            statements.extend(nested)
    return statements


def _direct_statements(output: object) -> list[str]:
    statements: list[str] = []
    for key in ("key_claim", "lead_claim", "analysis"):
        text = _text(_value(output, key, None))
        if text:
            statements.append(text)
            break
    for key in ("body_claims", "key_points"):
        statements.extend(_strings(_value(output, key, [])))
    return _dedupe(statements)


def _council_qualifiers(context: object) -> dict[str, object]:
    qualifiers: dict[str, object] = {}
    scalar_fields = (
        "council_id",
        "report_id",
        "layer_id",
        "chapter_title",
        "confidence_score",
    )
    for field in scalar_fields:
        value = _value(context, field, None)
        if isinstance(value, float):
            # Canonical Claim JSON intentionally excludes binary floats.
            qualifiers[field] = str(value)
        elif isinstance(value, (str, int)) and not isinstance(value, bool) and value != "":
            qualifiers[field] = value
    for field in ("disagreements", "next_actions"):
        values = _strings(_value(context, field, []))
        if values:
            qualifiers[field] = values
    return qualifiers


def _subject_refs(context: object) -> list[str]:
    for field in ("council_id", "report_id", "layer_id"):
        value = _text(_value(context, field, None))
        if value:
            return [value]
    return []


def _value(value: object, name: str, default: object) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple)):
        return []
    return _dedupe([text for item in value if (text := _text(item))])


def _text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
