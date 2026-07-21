"""Deterministic, evidence-aware hypothesis lifecycle for council output.

This module intentionally makes no claim validated: candidates are proposals for
an H-stage record, not scientific findings.  It accepts model output as data and
uses only explicit fields for parsing, critique, ranking, and evolution.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping


class HypothesisError(ValueError):
    """Structured hypothesis material is incomplete or malformed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _identifier(kind: str, value: Mapping[str, Any]) -> str:
    return f"{kind}_{sha256(_canonical(value)).hexdigest()[:32]}"


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HypothesisError(f"hypothesis requires non-empty {field}")
    return value.strip()


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise HypothesisError(f"hypothesis requires non-empty {field}")
    return tuple(_text(item, field) for item in value)


@dataclass(frozen=True)
class Hypothesis:
    """A candidate claim and its durable, non-validating lifecycle metadata."""

    id: str
    claim: str
    rationale: str
    evidence: tuple[str, ...]
    counterevidence: tuple[str, ...]
    falsification_criteria: str
    parent_ids: tuple[str, ...] = ()
    critiques: tuple[str, ...] = ()
    rank: int | None = None
    status: str = "candidate"

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "artifact_type": "claim",
            "statement": self.claim,
            "rationale": self.rationale,
            "evidence": list(self.evidence),
            "counterevidence": list(self.counterevidence),
            "falsification_criteria": self.falsification_criteria,
            "parent_claim_ids": list(self.parent_ids),
            "critiques": list(self.critiques),
            "rank": self.rank,
            "status": self.status,
            "validation_status": "unvalidated",
        }


class HypothesisLifecycle:
    """Pure deterministic operations over structured hypothesis candidates."""

    def parse(self, candidates: str | Mapping[str, Any] | Iterable[Mapping[str, Any]]) -> list[Hypothesis]:
        if isinstance(candidates, str):
            try:
                candidates = json.loads(candidates)
            except json.JSONDecodeError as exc:
                raise HypothesisError("hypothesis candidates must be structured JSON") from exc
        if isinstance(candidates, Mapping):
            if set(candidates) != {"hypotheses"}:
                raise HypothesisError("hypothesis candidate container must contain only hypotheses")
            candidates = candidates["hypotheses"]
        if not isinstance(candidates, (list, tuple)):
            raise HypothesisError("hypothesis candidates must be an array")
        parsed = [self._parse_one(item) for item in candidates]
        if not parsed:
            raise HypothesisError("hypothesis candidates must not be empty")
        if len({item.id for item in parsed}) != len(parsed):
            raise HypothesisError("duplicate hypothesis candidates")
        return parsed

    def _parse_one(self, candidate: Any) -> Hypothesis:
        if not isinstance(candidate, Mapping):
            raise HypothesisError("hypothesis candidate must be an object")
        allowed_fields = {
            "claim", "rationale", "evidence", "counterevidence",
            "falsification_criteria", "parent_ids",
        }
        if set(candidate) - allowed_fields:
            raise HypothesisError("hypothesis candidate contains unsupported fields")
        claim = _text(candidate.get("claim"), "claim")
        rationale = _text(candidate.get("rationale"), "rationale")
        evidence = _strings(candidate.get("evidence"), "evidence")
        counterevidence = _strings(candidate.get("counterevidence"), "counterevidence")
        falsification = _text(candidate.get("falsification_criteria"), "falsification_criteria")
        raw_parents = candidate.get("parent_ids")
        if raw_parents is not None and not isinstance(raw_parents, (list, tuple)):
            raise HypothesisError("hypothesis parent_ids must be a string array")
        parents = _strings(raw_parents, "parent_ids") if raw_parents else ()
        if len(set(parents)) != len(parents):
            raise HypothesisError("hypothesis parent_ids must not contain duplicates")
        parents = tuple(sorted(parents))
        identity = {"claim": claim, "rationale": rationale, "evidence": evidence, "counterevidence": counterevidence,
                    "falsification_criteria": falsification, "parent_ids": parents}
        hypothesis_id = _identifier("hypothesis", identity)
        if hypothesis_id in parents:
            raise HypothesisError("hypothesis must not link to itself")
        return Hypothesis(hypothesis_id, claim, rationale, evidence, counterevidence, falsification, parents)

    def critique(self, hypotheses: Iterable[Hypothesis]) -> list[Hypothesis]:
        """Attach explicit pressure tests; critiques never change validation status."""
        result = []
        for item in hypotheses:
            notes = tuple(sorted(set(item.critiques) | {
                f"Counterevidence to resolve: {entry}" for entry in item.counterevidence
            } | {f"Falsification test required: {item.falsification_criteria}"}))
            result.append(replace(item, critiques=notes, status="critiqued"))
        return result

    def rank(self, hypotheses: Iterable[Hypothesis]) -> list[Hypothesis]:
        """Rank by explicit evidence/counterevidence coverage, not confidence or consensus."""
        items = list(hypotheses)
        ordered = sorted(items, key=lambda item: (-len(item.evidence), -len(item.counterevidence), item.id))
        ranks = {item.id: index for index, item in enumerate(ordered, start=1)}
        return [replace(item, rank=ranks[item.id], status="ranked") for item in items]

    def evolve(self, hypothesis: Hypothesis, candidate: Mapping[str, Any]) -> Hypothesis:
        """Create a new candidate with an immutable parent link to the source claim."""
        if not isinstance(candidate, Mapping):
            raise HypothesisError("evolved hypothesis candidate must be an object")
        parent_ids = candidate.get("parent_ids", ())
        if not isinstance(parent_ids, (list, tuple)) or not all(
                isinstance(parent_id, str) and parent_id.strip() for parent_id in parent_ids):
            raise HypothesisError("hypothesis parent_ids must be a string array")
        if len(set(parent_ids)) != len(parent_ids):
            raise HypothesisError("hypothesis parent_ids must not contain duplicates")
        if hypothesis.id in parent_ids:
            raise HypothesisError("evolved hypothesis must not repeat its source parent")
        evolved = self._parse_one(
            dict(candidate) | {"parent_ids": [*parent_ids, hypothesis.id]}
        )
        if evolved.id in evolved.parent_ids:
            raise HypothesisError("hypothesis must not link to itself")
        return replace(evolved, status="evolved")

    def counter_hypotheses(self, hypotheses: Iterable[Hypothesis]) -> list[Hypothesis]:
        """Produce testable alternatives from each candidate's stated counterevidence."""
        alternatives = []
        for item in hypotheses:
            alternative = {
                "claim": f"Alternative to: {item.claim}",
                "rationale": "The original candidate has stated counterevidence that must be tested.",
                "evidence": list(item.counterevidence),
                "counterevidence": list(item.evidence),
                "falsification_criteria": f"Show that the alternative fails while: {item.falsification_criteria}",
                "parent_ids": [item.id],
            }
            alternatives.append(replace(self._parse_one(alternative), status="counter_hypothesis"))
        return alternatives

    def h_stage_input(self, hypotheses: Iterable[Hypothesis], *,
                      evidence_artifact_ids: Mapping[str, Iterable[str]] | None = None) -> dict[str, Any]:
        """Return frozen H-stage claim inputs with caller-supplied artifact references only."""
        items = list(hypotheses)
        ranks = [item.rank for item in items]
        if any(rank is None for rank in ranks):
            raise HypothesisError("H-stage claim requires an explicit rank")
        if (not items
                or any(not isinstance(rank, int) or isinstance(rank, bool) for rank in ranks)
                or set(ranks) != set(range(1, len(items) + 1))):
            raise HypothesisError("ranked hypothesis batch must use unique contiguous ranks 1..N")
        artifact_ids_by_hypothesis = dict(evidence_artifact_ids or {})
        claims = []
        for item in items:
            if item.rank is None:
                raise HypothesisError("H-stage claim requires an explicit rank")
            if item.id in item.parent_ids:
                raise HypothesisError("hypothesis must not link to itself")
            if len(set(item.parent_ids)) != len(item.parent_ids):
                raise HypothesisError("hypothesis parent_ids must not contain duplicates")
            artifact_ids = artifact_ids_by_hypothesis.get(item.id, ())
            if not isinstance(artifact_ids, (list, tuple)) or not all(
                    isinstance(artifact_id, str) and artifact_id for artifact_id in artifact_ids):
                raise HypothesisError("evidence artifact IDs must be a string array")
            claims.append({
                "artifact_type": "claim",
                "statement": item.claim,
                "falsification_criteria": item.falsification_criteria,
                "evidence_artifact_ids": list(artifact_ids),
                "parent_claim_ids": list(item.parent_ids),
                "rank": item.rank,
                "limitations": [
                    "Unvalidated candidate; rank is prioritization, not support.",
                    *(() if artifact_ids else ("Evidence text is explicitly unlinked to committed artifacts.",)),
                    *(f"Counterevidence: {entry}" for entry in item.counterevidence),
                    *(f"Critique: {entry}" for entry in item.critiques),
                ],
            })
        return {"kind": "hypothesis.complete", "claims": claims}

    def validate_h_stage_claims(self, claims: Iterable[Mapping[str, Any]],
                                committed_artifact_ids: Iterable[str] | Mapping[str, Mapping[str, Any]]) -> None:
        """Verify an H-stage projection preserves its unvalidated provenance and links."""
        committed_records = (
            committed_artifact_ids if isinstance(committed_artifact_ids, Mapping) else None
        )
        current_claim_ids: set[str] | None = None
        if committed_records is not None:
            claim_scopes = [
                record["content"] for record in committed_records.values()
                if (isinstance(record, Mapping)
                    and record.get("record_type") == "responsibility_requirement"
                    and isinstance(record.get("content"), Mapping)
                    and record["content"].get("responsibility") == "novelty_value_judgment"
                    and record["content"].get("scope_kind") == "claims")
            ]
            if claim_scopes:
                if not all(
                        isinstance(scope.get("requirement_ordinal"), int)
                        and not isinstance(scope["requirement_ordinal"], bool)
                        and scope["requirement_ordinal"] >= 0
                        for scope in claim_scopes):
                    raise HypothesisError("current claim scope is invalid")
                current_scope = max(claim_scopes, key=lambda scope: scope["requirement_ordinal"])
                scope_ids = current_scope.get("scope_ids")
                if (not isinstance(scope_ids, list)
                        or not all(isinstance(scope_id, str) and scope_id for scope_id in scope_ids)):
                    raise HypothesisError("current claim scope is invalid")
                current_claim_ids = set(scope_ids)
        available_ids = set(committed_artifact_ids)
        required_fields = {
            "artifact_type", "statement", "falsification_criteria", "evidence_artifact_ids",
            "parent_claim_ids", "rank", "limitations",
        }
        unvalidated_limitation = "Unvalidated candidate; rank is prioritization, not support."
        unlinked_evidence_limitation = "Evidence text is explicitly unlinked to committed artifacts."

        def validate_parent(parent_id: str, ancestry: frozenset[str], *, must_be_current: bool) -> None:
            if parent_id in ancestry:
                raise HypothesisError("H-stage claim lineage contains a cycle")
            if committed_records is None:
                raise HypothesisError("H-stage claim parent identity cannot be verified")
            record = committed_records.get(parent_id)
            if must_be_current and current_claim_ids is not None and parent_id not in current_claim_ids:
                raise HypothesisError("H-stage claim parent is not current")
            if (not isinstance(record, Mapping)
                    or record.get("id") != parent_id
                    or record.get("record_type") != "claim"
                    or not isinstance(record.get("content"), Mapping)
                    or record["content"].get("artifact_type") != "claim"):
                raise HypothesisError("H-stage claim references an uncommitted or non-claim parent")
            ancestors = record["content"].get("parent_claim_ids")
            if not isinstance(ancestors, list) or not all(
                    isinstance(ancestor, str) and ancestor for ancestor in ancestors):
                raise HypothesisError("committed parent claim has invalid lineage")
            if len(set(ancestors)) != len(ancestors):
                raise HypothesisError("committed parent claim has duplicate parents")
            if parent_id in ancestors:
                raise HypothesisError("committed parent claim links to itself")
            for ancestor in ancestors:
                validate_parent(ancestor, ancestry | {parent_id}, must_be_current=False)

        claim_batch = list(claims)
        ranks: list[int] = []
        for claim in claim_batch:
            if not isinstance(claim, Mapping) or set(claim) != required_fields:
                raise HypothesisError("H-stage claim has an invalid shape")
            artifact_ids = claim["evidence_artifact_ids"]
            parent_ids = claim["parent_claim_ids"]
            limitations = claim["limitations"]
            if (claim["artifact_type"] != "claim"
                    or not isinstance(claim["statement"], str) or not claim["statement"].strip()
                    or not isinstance(claim["falsification_criteria"], str) or not claim["falsification_criteria"].strip()
                    or not isinstance(claim["rank"], int) or isinstance(claim["rank"], bool) or claim["rank"] < 1
                    or not isinstance(artifact_ids, list)
                    or not isinstance(parent_ids, list)
                    or not isinstance(limitations, list)
                    or not all(isinstance(item, str) and item for item in artifact_ids)
                    or not all(isinstance(item, str) and item for item in parent_ids)
                    or not all(isinstance(item, str) and item for item in limitations)):
                raise HypothesisError("H-stage claim has invalid evidence, lineage, or limitations")
            if len(set(parent_ids)) != len(parent_ids):
                raise HypothesisError("H-stage claim has duplicate parents")
            for parent_id in parent_ids:
                validate_parent(parent_id, frozenset(), must_be_current=True)
            if unvalidated_limitation not in limitations:
                raise HypothesisError("H-stage claim must explicitly remain unvalidated")
            if not artifact_ids and unlinked_evidence_limitation not in limitations:
                raise HypothesisError("H-stage claim without committed evidence must state that limitation")
            if not set(artifact_ids) <= available_ids:
                raise HypothesisError("H-stage claim references uncommitted evidence artifacts")
            ranks.append(claim["rank"])
        if (not claim_batch
                or set(ranks) != set(range(1, len(claim_batch) + 1))):
            raise HypothesisError("H-stage claim batch must use unique contiguous ranks 1..N")

