"""Append-only responsibility sign-off core for scientific cycles.

This module deliberately has no CLI dependency.  It records human assertions;
it neither authenticates actors nor grants institutional approval.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import re
from types import MappingProxyType
from typing import Mapping

from src.pipeline.scientific_contracts import (
    ActorAssertion,
    AuthorityKind,
    Responsibility,
    actor_assertion_from_mapping,
    canonical_id_array,
    deterministic_id,
    digest,
    stage_boundary_from_mapping,
)
from datetime import datetime



def _mapping(value: object) -> object:
    """Convert public dataclass inputs to the frozen mapping protocol."""
    if is_dataclass(value):
        return _mapping(asdict(value))
    if isinstance(value, Mapping):
        return {key: _mapping(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_mapping(item) for item in value]
    return value
def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return value



def _canonical_scope(scope_kind: object, scope_ids: object) -> tuple[str, tuple[str, ...], str]:
    if not isinstance(scope_kind, str) or not scope_kind:
        raise SignoffError("requirement scope kind must be a nonempty string")
    if scope_kind == "report_body":
        if (not isinstance(scope_ids, (list, tuple)) or len(scope_ids) != 2
                or not isinstance(scope_ids[0], str) or not isinstance(scope_ids[1], str)):
            raise SignoffError("report-body scope must contain its ID and hash")
        try:
            report_body_id = canonical_id_array((scope_ids[0],), nonempty=True)[0]
        except ValueError as exc:
            raise SignoffError("report-body scope ID must be canonical") from exc
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", scope_ids[1]):
            raise SignoffError("report-body scope hash must be a SHA-256 digest")
        ids = (report_body_id, scope_ids[1])
    else:
        try:
            ids = canonical_id_array(scope_ids)  # type: ignore[arg-type]
        except ValueError as exc:
            raise SignoffError("requirement scope IDs must be canonical") from exc
    return scope_kind, ids, digest({"scope_kind": scope_kind, "scope_ids": list(ids)})


class SignoffError(ValueError):
    """Raised when a responsibility record would violate currentness or binding."""


@dataclass(frozen=True)
class ResponsibilityRequirementRecord:
    requirement_id: str
    cycle_id: str
    responsibility: Responsibility
    ordinal: int
    scope_kind: str
    scope_ids: tuple[str, ...]
    scope_hash: str
    supersedes_requirement_id: str | None = None
    def __post_init__(self) -> None:
        scope_kind, scope_ids, scope_hash = _canonical_scope(self.scope_kind, self.scope_ids)
        if (scope_kind != self.scope_kind or scope_ids != self.scope_ids
                or scope_hash != self.scope_hash):
            raise SignoffError("requirement scope hash must match its canonical scope")
        expected_id = deterministic_id("responsibility_requirement", {
            "cycle_id": self.cycle_id,
            "responsibility": self.responsibility.value,
            "requirement_ordinal": self.ordinal,
            "scope_kind": scope_kind,
            "scope_ids": list(scope_ids),
            "scope_hash": scope_hash,
            "supersedes_requirement_id": self.supersedes_requirement_id,
        })
        if self.requirement_id != expected_id:
            raise SignoffError("requirement ID must bind its immutable scope and supersession")


@dataclass(frozen=True)
class ResponsibilityDispositionRecord:
    disposition_id: str
    cycle_id: str
    requirement_id: str
    responsibility: Responsibility
    ordinal: int
    actor: ActorAssertion
    asserted_at: str
    status: str
    rationale: str
    scope_hash: str
    details: Mapping[str, object] = field(default_factory=dict)
    superseded_by_requirement_id: str | None = None

    @property
    def actor_assurance_label(self) -> str:
        return "operator asserted — unverified" if self.actor.authority_scope.kind is AuthorityKind.NONE else "external reference — unverified"


@dataclass(frozen=True)
class FinalAccountabilityBinding:
    report_body_id: str
    report_body_hash: str
    reviewed_exact_bytes: bool
    limitations_acknowledged: bool

    def __post_init__(self) -> None:
        if not self.report_body_id or not self.report_body_hash:
            raise SignoffError("final accountability requires an immutable report body binding")
        if not (self.reviewed_exact_bytes and self.limitations_acknowledged):
            raise SignoffError("final accountability requires exact-byte review and limitation acknowledgement")


class SignoffCore:
    """In-memory pure projection of immutable requirement and disposition records."""

    def __init__(self, cycle_id: str) -> None:
        self.cycle_id = cycle_id
        self._requirements: list[ResponsibilityRequirementRecord] = []
        self._dispositions: list[ResponsibilityDispositionRecord] = []
        for responsibility in Responsibility:
            self._append_requirement(responsibility, "cycle", (), None, None)
    @property
    def requirements(self) -> tuple[ResponsibilityRequirementRecord, ...]:
        """Immutable append-only view of requirement history."""
        return tuple(self._requirements)

    @property
    def dispositions(self) -> tuple[ResponsibilityDispositionRecord, ...]:
        """Immutable append-only view of disposition history."""
        return tuple(self._dispositions)


    def _append_requirement(self, responsibility: Responsibility, scope_kind: str,
                            scope_ids: tuple[str, ...], supplied_scope_hash: str | None,
                            supersedes: str | None) -> ResponsibilityRequirementRecord:
        scope_kind, scope_ids, scope_hash = _canonical_scope(scope_kind, scope_ids)
        if supplied_scope_hash is not None and supplied_scope_hash != scope_hash:
            raise SignoffError("requirement scope hash must match its canonical scope")
        ordinal = len(self._requirements)
        requirement_id = deterministic_id("responsibility_requirement", {
            "cycle_id": self.cycle_id,
            "responsibility": responsibility.value,
            "requirement_ordinal": ordinal,
            "scope_kind": scope_kind,
            "scope_ids": list(scope_ids),
            "scope_hash": scope_hash,
            "supersedes_requirement_id": supersedes,
        })
        record = ResponsibilityRequirementRecord(requirement_id, self.cycle_id, responsibility,
                                                  ordinal, scope_kind, scope_ids, scope_hash, supersedes)
        self._requirements.append(record)
        return record

    def current_requirement(self, responsibility: Responsibility) -> ResponsibilityRequirementRecord:
        for record in reversed(self._requirements):
            if record.responsibility is responsibility:
                return record
        raise SignoffError("missing responsibility requirement")

    def rescope(self, responsibility: Responsibility, scope_kind: str,
                scope_ids: tuple[str, ...], scope_hash: str | None = None) -> ResponsibilityRequirementRecord:
        """Append a replacement requirement; previous records remain historical."""
        old = self.current_requirement(responsibility)
        return self._append_requirement(responsibility, scope_kind, scope_ids, scope_hash, old.requirement_id)
    @staticmethod
    def validate_disposition_input(*, requirement: Mapping[str, object],
                                   existing_disposition: Mapping[str, object] | None,
                                   responsibility: str, payload: Mapping[str, object]) -> dict[str, object]:
        """Validate reducer-facing immutable sign-off content against the current requirement."""
        if requirement.get("responsibility") != responsibility:
            raise SignoffError("disposition responsibility does not match requirement")
        if existing_disposition is not None:
            raise SignoffError("current requirement already has an immutable disposition; supersede it first")
        if payload.get("requirement_id") != requirement.get("id"):
            raise SignoffError("disposition must target the current requirement")
        _, _, expected_scope_hash = _canonical_scope(
            requirement.get("scope_kind"), requirement.get("scope_ids"),
        )
        if requirement.get("scope_hash") != expected_scope_hash:
            raise SignoffError("requirement scope hash must match its canonical scope")
        if payload.get("scope_hash") != expected_scope_hash:
            raise SignoffError("disposition scope hash must exactly match the current requirement")
        actor = payload.get("actor")
        try:
            actor = actor_assertion_from_mapping(actor) if isinstance(actor, Mapping) else None
        except ValueError as exc:
            raise SignoffError("disposition requires a valid asserted actor") from exc
        if actor is None:
            raise SignoffError("disposition requires an asserted actor")
        asserted_at = payload.get("asserted_at")
        if not isinstance(asserted_at, str):
            raise SignoffError("disposition requires an assertion timestamp")
        try:
            datetime.strptime(asserted_at, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError as exc:
            raise SignoffError("disposition timestamp must be UTC RFC3339 microseconds") from exc
        allowed = {"satisfied", "declined"}
        if responsibility == Responsibility.EXCEPTION_INTERPRETATION.value:
            allowed.add("not_applicable")
        if payload.get("status") not in allowed or not isinstance(payload.get("rationale"), str) or not payload["rationale"]:
            raise SignoffError("invalid responsibility disposition")
        details = payload.get("details", {})
        if not isinstance(details, Mapping):
            raise SignoffError("disposition details must be an object")
        if responsibility == Responsibility.FINAL_ACCOUNTABILITY.value:
            binding = FinalAccountabilityBinding(
                str(details.get("report_body_id", "")), str(details.get("report_body_hash", "")),
                details.get("reviewed_exact_bytes") is True, details.get("limitations_acknowledged") is True,
            )
            scope_kind, scope_ids, scope_hash = _canonical_scope(
                requirement.get("scope_kind"), requirement.get("scope_ids"),
            )
            if (scope_kind != "report_body"
                    or scope_ids != (binding.report_body_id, binding.report_body_hash)
                    or scope_hash != expected_scope_hash):
                raise SignoffError("final accountability must bind the current report body ID and hash")
        if responsibility == Responsibility.EXECUTION_ACCOUNTABILITY.value:
            try:
                details = dict(details)
                details["handoff_owner"] = actor_assertion_from_mapping(details["handoff_owner"])
                details["execution_boundary"] = stage_boundary_from_mapping(details["execution_boundary"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SignoffError("execution accountability requires valid asserted handoff details") from exc
        return {"requirement_id": str(payload["requirement_id"]), "actor": actor,
                "asserted_at": asserted_at, "status": str(payload["status"]),
                "rationale": str(payload["rationale"]), "scope_hash": str(payload["scope_hash"]),
                "details": dict(details)}

    def record_disposition(self, *, requirement_id: str, responsibility: Responsibility,
                           actor: ActorAssertion, asserted_at: str, status: str,
                           rationale: str, details: Mapping[str, object] | None = None) -> ResponsibilityDispositionRecord:
        requirement = self.current_requirement(responsibility)
        payload = {
            "requirement_id": requirement_id,
            "scope_hash": requirement.scope_hash,
            "actor": _mapping(actor),
            "asserted_at": asserted_at,
            "status": status,
            "rationale": rationale,
            "details": _mapping(details or {}),
        }
        normalized = self.validate_disposition_input(
            requirement={
                "id": requirement.requirement_id,
                "responsibility": requirement.responsibility.value,
                "scope_kind": requirement.scope_kind,
                "scope_ids": list(requirement.scope_ids),
                "scope_hash": requirement.scope_hash,
            },
            existing_disposition=(
                {"id": self.current_disposition(responsibility).disposition_id}
                if self.current_disposition(responsibility) is not None else None
            ),
            responsibility=responsibility.value,
            payload=payload,
        )
        ordinal = len(self._dispositions)
        content = {
            "requirement_id": normalized["requirement_id"],
            "responsibility": responsibility.value,
            "ordinal": ordinal,
            "actor": normalized["actor"],
            "asserted_at": normalized["asserted_at"],
            "status": normalized["status"],
            "rationale": normalized["rationale"],
            "scope_hash": normalized["scope_hash"],
            "details": normalized["details"],
        }
        disposition_id = deterministic_id("responsibility_disposition", {
            "cycle_id": self.cycle_id,
            "requirement_id": requirement_id,
            "disposition_ordinal": ordinal,
            "content_hash": digest(content),
        })
        record = ResponsibilityDispositionRecord(
            disposition_id, self.cycle_id, requirement_id, responsibility, ordinal, actor,
            str(normalized["asserted_at"]), str(normalized["status"]),
            str(normalized["rationale"]), str(normalized["scope_hash"]),
            _freeze_value(normalized["details"]),
        )
        self._dispositions.append(record)
        return record

    def supersede(self, responsibility: Responsibility, scope_kind: str, scope_ids: tuple[str, ...],
                  scope_hash: str | None = None) -> ResponsibilityRequirementRecord:
        return self.rescope(responsibility, scope_kind, scope_ids, scope_hash)

    def current_disposition(self, responsibility: Responsibility) -> ResponsibilityDispositionRecord | None:
        requirement = self.current_requirement(responsibility)
        for record in reversed(self._dispositions):
            if record.requirement_id == requirement.requirement_id:
                return record
        return None

    def is_satisfied(self, responsibility: Responsibility) -> bool:
        record = self.current_disposition(responsibility)
        return record is not None and record.status in {"satisfied", "not_applicable"}

    def final_accountability(self, report_body_id: str, report_body_hash: str) -> ResponsibilityDispositionRecord | None:
        record = self.current_disposition(Responsibility.FINAL_ACCOUNTABILITY)
        if record is None or record.status != "satisfied":
            return None
        if record.details.get("report_body_id") != report_body_id or record.details.get("report_body_hash") != report_body_hash:
            return None
        return record
