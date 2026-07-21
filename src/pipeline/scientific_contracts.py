"""Frozen, dependency-free contracts for the ``ai-scientist.v1`` protocol.

This module owns canonical Python representations only.  It deliberately has no
physical-execution API: external results are descriptions of completed work.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import math
import re
import unicodedata2
from typing import Any, ClassVar, Mapping, Sequence

PROTOCOL = "muchanipo"
PROTOCOL_VERSION = "ai-scientist.v1"
NORMALIZATION_PROFILE = "unicode-nfc-whitespace"
NORMALIZATION_PROFILE_VERSION = "1"
NORMALIZATION_UNICODE_VERSION = "15.1.0"
IDENTITY_SCHEMA = "ai-scientist.identity.v1"
GENESIS_HASH = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_SAFE_INTEGER = 9_007_199_254_740_991
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_CONFIDENCE = re.compile(r"(?:0|1|0\.\d{1,4})\Z")
_EXTERNAL_POLICY = re.compile(r"external:[a-z0-9][a-z0-9._-]{0,127}\Z")
_WS = frozenset("\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000")

if unicodedata2.unidata_version != NORMALIZATION_UNICODE_VERSION:
    raise ImportError(
        "scientific question normalization requires unicodedata2 pinned to Unicode "
        f"{NORMALIZATION_UNICODE_VERSION}; found {unicodedata2.unidata_version}"
    )


class ContractError(ValueError):
    """Raised when a frozen scientific or wire invariant is violated."""


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ContractError("objects require string keys")
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _validate_jcs_subset(value: Any) -> None:
    """Validate the explicit stdlib-supported RFC 8785 subset.

    Python's encoder does not implement ECMAScript number serialization, so
    binary floats are rejected rather than silently producing non-JCS bytes.
    Scientific decimals must be represented by their contract string fields.
    """
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ContractError("strings containing surrogate code points are unsupported")
        return
    if isinstance(value, int) and not isinstance(value, bool):
        if not -_SAFE_INTEGER <= value <= _SAFE_INTEGER:
            raise ContractError("integer is outside the RFC 8785 safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError("NaN and infinity are forbidden")
        raise ContractError("binary floats are unsupported; use a canonical decimal string")
    if isinstance(value, Mapping):
        keys = list(value)
        if any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys):
            raise ContractError("objects require unique string keys")
        for key, item in value.items():
            _validate_jcs_subset(key)
            _validate_jcs_subset(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_jcs_subset(item)
        return
    raise ContractError(f"unsupported canonical value: {type(value).__name__}")


def _utf16_key(value: str) -> bytes:
    """RFC 8785 orders object member names by UTF-16 code units."""
    return value.encode("utf-16-be")


def _utf16_ordered(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _utf16_ordered(value[key]) for key in sorted(value, key=_utf16_key)}
    if isinstance(value, (list, tuple)):
        return [_utf16_ordered(item) for item in value]
    return value


def canonical_json(value: Any) -> bytes:
    """Return deterministic UTF-8 for the documented RFC 8785 subset."""
    value = _plain(value)
    _validate_jcs_subset(value)
    return json.dumps(_utf16_ordered(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_json_object(raw: str | bytes) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates, parse_constant=lambda x: (_ for _ in ()).throw(ContractError(f"invalid JSON number: {x}")))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContractError("invalid JSON") from exc
    _validate_jcs_subset(value)
    return value


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def byte_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def deterministic_id(kind: str, seed: Mapping[str, Any]) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", kind):
        raise ContractError("identifier kind must be lowercase ASCII")
    if {"kind", "seed_schema"}.intersection(seed):
        raise ContractError("identity seed cannot override its frozen kind or schema")
    material = {"seed_schema": IDENTITY_SCHEMA, "kind": kind, **dict(seed)}
    return f"{kind}_{hashlib.sha256(canonical_json(material)).hexdigest()[:32]}"


def content_record(record_type: str, content: Mapping[str, Any], seed: Mapping[str, Any]) -> dict[str, Any]:
    forbidden = {"id", "content_hash", "repository_metadata", "transport_metadata", "projection"}
    if forbidden.intersection(content):
        raise ContractError("record content crosses the ID-free content boundary")
    content_hash = digest(content)
    return {"record_type": record_type, "schema_version": PROTOCOL_VERSION,
            "id": deterministic_id(record_type, {**dict(seed), "content_hash": content_hash}),
            "content_hash": content_hash, "content": dict(content)}


def command_digest(name: str, cycle_id: str | None, idempotency_key: str, payload: Mapping[str, Any]) -> str:
    return digest({"digest_schema": "ai-scientist.command.v1", "protocol_version": PROTOCOL_VERSION,
                   "name": name, "cycle_id": cycle_id, "idempotency_key": idempotency_key,
                   "payload": dict(payload)})


def event_frame_hash(frame: Mapping[str, Any]) -> str:
    """Hash the complete event frame with only its top-level frame_hash omitted."""
    if "frame_hash" not in frame:
        raise ContractError("event frame must carry frame_hash")
    return digest({key: value for key, value in frame.items() if key != "frame_hash"})


def normalize_question(raw: str) -> str:
    if not isinstance(raw, str):
        raise ContractError("raw_question must be a string")
    normalized = unicodedata2.normalize("NFC", raw.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = re.sub("[" + re.escape("".join(_WS)) + "]+", " ", normalized).strip(" ")
    if not normalized:
        raise ContractError("normalized question must not be empty")
    return normalized


def canonical_id_array(values: Sequence[str], *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ContractError("ID array must be a list or tuple")
    result = tuple(values)
    if nonempty and not result:
        raise ContractError("ID array must be nonempty")
    if any(not isinstance(value, str) or not _ID.fullmatch(value) for value in result):
        raise ContractError("IDs must be protocol IDs")
    if tuple(sorted(set(result))) != result:
        raise ContractError("set-like ID arrays must be deduplicated and ASCII sorted")
    return result


class ActorKind(StrEnum): HUMAN = "human"; ORGANIZATION = "organization"
class AssertionSource(StrEnum): OPERATOR_ENTRY = "operator_entry"; IMPORTED_DOCUMENT = "imported_document"; EXTERNAL_REFERENCE = "external_reference"
class VerificationStatus(StrEnum): OPERATOR_ASSERTED_UNVERIFIED = "operator_asserted_unverified"; EXTERNAL_REFERENCE_UNVERIFIED = "external_reference_unverified"
class AuthorityKind(StrEnum): NONE = "none"; EXTERNALLY_ASSERTED = "externally_asserted"
class Stage(StrEnum): L = "L"; H = "H"; P = "P"; X = "X"; A = "A"; W = "W"
class Outcome(StrEnum): SUPPORTS = "supports"; REFUTES = "refutes"; INCONCLUSIVE = "inconclusive"; NOT_APPLICABLE = "not_applicable"
class Support(StrEnum): UNSUPPORTED = "unsupported"; PENDING = "pending"; DISPUTED = "disputed"; ACCEPTED = "accepted"
class AssessmentState(StrEnum): PENDING = "pending"; DISPUTED = "disputed"; ACCEPTED = "accepted"; REJECTED = "rejected"
class EvidenceQuality(StrEnum): LOW = "low"; MODERATE = "moderate"; HIGH = "high"; UNKNOWN = "unknown"
class ValidationLevel(StrEnum): V0 = "V0"; V1 = "V1"; V2 = "V2"; V3 = "V3"
class Responsibility(StrEnum):
    QUESTION_SELECTION = "question_selection"; SAFETY_ETHICS_REVIEW = "safety_ethics_review"; EXECUTION_ACCOUNTABILITY = "execution_accountability"; EXCEPTION_INTERPRETATION = "exception_interpretation"; NOVELTY_VALUE_JUDGMENT = "novelty_value_judgment"; FINAL_ACCOUNTABILITY = "final_accountability"

@dataclass(frozen=True)
class AuthorityScope:
    kind: AuthorityKind
    scope: str | None
    def __post_init__(self) -> None:
        if (not isinstance(self.kind, AuthorityKind)
                or self.scope is not None and (not isinstance(self.scope, str) or not self.scope)
                or (self.kind is AuthorityKind.NONE) != (self.scope is None)):
            raise ContractError("authority scope must be null exactly for none")

@dataclass(frozen=True)
class ExternalReference:
    reference_type: str; issuer: str; title: str; uri_or_identifier: str; content_hash: str
    assertion_source: AssertionSource; verification_status: VerificationStatus; authority_scope: AuthorityScope
    def __post_init__(self) -> None:
        if (not all(isinstance(field, str) and field for field in
                    (self.reference_type, self.issuer, self.title, self.uri_or_identifier, self.content_hash))
                or not isinstance(self.assertion_source, AssertionSource)
                or not isinstance(self.verification_status, VerificationStatus)
                or not isinstance(self.authority_scope, AuthorityScope)
                or not _DIGEST.fullmatch(self.content_hash)):
            raise ContractError("invalid external reference")
        if self.assertion_source is AssertionSource.OPERATOR_ENTRY or self.verification_status is not VerificationStatus.EXTERNAL_REFERENCE_UNVERIFIED:
            raise ContractError("external references are externally unverified assertions")

@dataclass(frozen=True)
class ActorAssertion:
    actor_kind: ActorKind; display_name: str; organization: str | None; role: str | None
    assertion_source: AssertionSource; verification_status: VerificationStatus
    authority_scope: AuthorityScope; external_reference: ExternalReference | None
    def __post_init__(self) -> None:
        if (not isinstance(self.actor_kind, ActorKind)
                or not isinstance(self.display_name, str) or not self.display_name
                or any(value is not None and (not isinstance(value, str) or not value)
                       for value in (self.organization, self.role))
                or not isinstance(self.assertion_source, AssertionSource)
                or not isinstance(self.verification_status, VerificationStatus)
                or not isinstance(self.authority_scope, AuthorityScope)
                or self.external_reference is not None and not isinstance(self.external_reference, ExternalReference)):
            raise ContractError("invalid actor assertion")
        operator = self.assertion_source is AssertionSource.OPERATOR_ENTRY
        if operator and (self.verification_status is not VerificationStatus.OPERATOR_ASSERTED_UNVERIFIED or self.authority_scope.kind is not AuthorityKind.NONE or self.external_reference is not None):
            raise ContractError("operator entries require unverified/none/null assurance")
        if not operator and (self.verification_status is not VerificationStatus.EXTERNAL_REFERENCE_UNVERIFIED or self.external_reference is None):
            raise ContractError("imported actors require an unverified external reference")
def _authority_scope_from_mapping(value: Mapping[str, Any]) -> AuthorityScope:
    if (not isinstance(value, Mapping) or set(value) != {"kind", "scope"}
            or not isinstance(value["kind"], str) or not value["kind"]
            or value["scope"] is not None and (not isinstance(value["scope"], str) or not value["scope"])):
        raise ContractError("authority scope fields are frozen")
    try:
        return AuthorityScope(AuthorityKind(value["kind"]), value["scope"])
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid authority scope") from exc


def external_reference_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Construct the frozen reference contract and return canonical persisted data."""
    fields = {"reference_type", "issuer", "title", "uri_or_identifier", "content_hash",
              "assertion_source", "verification_status", "authority_scope"}
    if (not isinstance(value, Mapping) or set(value) != fields
            or not all(isinstance(value[field], str) and value[field] for field in
                       fields - {"authority_scope"})):
        raise ContractError("external reference fields are frozen")
    try:
        reference = ExternalReference(
            value["reference_type"], value["issuer"], value["title"],
            value["uri_or_identifier"], value["content_hash"],
            AssertionSource(value["assertion_source"]), VerificationStatus(value["verification_status"]),
            _authority_scope_from_mapping(value["authority_scope"]),
        )
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid external reference") from exc
    return _plain(reference)


def actor_assertion_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Reject asserted authority outside v1 and persist only frozen actor fields."""
    fields = {"actor_kind", "display_name", "organization", "role", "assertion_source",
              "verification_status", "authority_scope", "external_reference"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ContractError("actor assertion fields are frozen")
    scope = _authority_scope_from_mapping(value["authority_scope"])
    reference_value = value["external_reference"]
    reference = None
    if isinstance(reference_value, Mapping):
        canonical = external_reference_from_mapping(reference_value)
        reference_scope = canonical["authority_scope"]
        reference = ExternalReference(canonical["reference_type"], canonical["issuer"], canonical["title"],
                                      canonical["uri_or_identifier"], canonical["content_hash"],
                                      AssertionSource(canonical["assertion_source"]),
                                      VerificationStatus(canonical["verification_status"]),
                                      AuthorityScope(AuthorityKind(reference_scope["kind"]), reference_scope["scope"]))
    if reference_value is not None and reference is None:
        raise ContractError("actor external reference must be an object or null")
    try:
        if (not isinstance(value["actor_kind"], str) or not value["actor_kind"]
                or not isinstance(value["display_name"], str) or not value["display_name"]
                or any(item is not None and (not isinstance(item, str) or not item)
                       for item in (value["organization"], value["role"]))
                or not isinstance(value["assertion_source"], str) or not value["assertion_source"]
                or not isinstance(value["verification_status"], str) or not value["verification_status"]):
            raise ContractError("invalid actor assertion")
        actor = ActorAssertion(
            ActorKind(value["actor_kind"]), value["display_name"], value["organization"], value["role"],
            AssertionSource(value["assertion_source"]), VerificationStatus(value["verification_status"]),
            scope, reference,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid actor assertion") from exc
    return _plain(actor)


def performer_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {"kind", "name", "version", "external_reference"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ContractError("performer fields are frozen")
    reference = value["external_reference"]
    if reference is not None and not isinstance(reference, Mapping):
        raise ContractError("performer external reference must be an object or null")
    if (not isinstance(value["kind"], str) or not value["kind"]
            or not isinstance(value["name"], str) or not value["name"]
            or value["version"] is not None and (not isinstance(value["version"], str) or not value["version"])):
        raise ContractError("invalid performer")
    canonical = external_reference_from_mapping(reference) if reference is not None else None
    external = None
    if canonical is not None:
        scope = canonical["authority_scope"]
        external = ExternalReference(canonical["reference_type"], canonical["issuer"], canonical["title"],
                                     canonical["uri_or_identifier"], canonical["content_hash"],
                                     AssertionSource(canonical["assertion_source"]),
                                     VerificationStatus(canonical["verification_status"]),
                                     AuthorityScope(AuthorityKind(scope["kind"]), scope["scope"]))
    performer = Performer(value["kind"], value["name"], value["version"], external)
    return _plain(performer)


def stage_boundary_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    if (not isinstance(value, Mapping) or set(value) != {"kind", "description"}
            or not isinstance(value["kind"], str) or not value["kind"]
            or not isinstance(value["description"], str) or not value["description"]):
        raise ContractError("stage boundary fields are frozen")
    return _plain(StageBoundary(value["kind"], value["description"]))

@dataclass(frozen=True)
class Performer:
    kind: str; name: str; version: str | None; external_reference: ExternalReference | None
    def __post_init__(self) -> None:
        if (not isinstance(self.kind, str) or self.kind not in {"human", "organization", "ai_model", "service", "software"}
                or not isinstance(self.name, str) or not self.name
                or self.version is not None and (not isinstance(self.version, str) or not self.version)
                or self.external_reference is not None and not isinstance(self.external_reference, ExternalReference)):
            raise ContractError("invalid performer")

@dataclass(frozen=True)
class StageBoundary:
    kind: str; description: str
    def __post_init__(self) -> None:
        if (not isinstance(self.kind, str)
                or self.kind not in {"cognitive_only", "computational_only", "export_only", "external_completed_import"}
                or not isinstance(self.description, str) or not self.description):
            raise ContractError("invalid non-physical stage boundary")

@dataclass(frozen=True)
class StageRecord:
    cycle_id: str; stage: Stage; stage_ordinal: int; origin: str; status: str; execution_kind: str
    accountable_party: ActorAssertion | None; performers: tuple[Performer, ...]; automation_mode: str
    boundary: StageBoundary; started_at: str | None; completed_at: str | None; artifact_ids: tuple[str, ...]
    proposal_id: str | None; proposal_hash: str | None; result_ids: tuple[str, ...]; report_body_id: str | None; supersedes_stage_id: str | None
    def __post_init__(self) -> None:
        if self.stage_ordinal < 0 or self.origin not in {"muchanipo", "external"} or self.status not in {"completed", "not_run"}:
            raise ContractError("invalid stage identity")
        if self.status == "not_run":
            required_null = (self.stage is Stage.X and self.execution_kind == "not_run" and self.accountable_party is None and not self.performers and self.automation_mode == "not_run" and self.started_at is None and self.completed_at is None)
            if not required_null: raise ContractError("only local X may be not_run")
        elif self.accountable_party is None or not self.performers or self.execution_kind not in {"cognitive", "computational"} or self.automation_mode not in {"manual", "ai_assisted", "automated"} or self.started_at is None or self.completed_at is None:
            raise ContractError("completed stages require accountable completed-stage fields")
        canonical_id_array(self.artifact_ids); canonical_id_array(self.result_ids)

@dataclass(frozen=True)
class ResponsibilityRequirement:
    cycle_id: str; responsibility: Responsibility; requirement_ordinal: int; scope_kind: str; scope_ids: tuple[str, ...]; scope_hash: str; status_at_creation: str = "pending"; supersedes_requirement_id: str | None = None
    def __post_init__(self) -> None:
        if self.requirement_ordinal < 0 or self.status_at_creation != "pending" or not _DIGEST.fullmatch(self.scope_hash): raise ContractError("invalid responsibility requirement")
        canonical_id_array(self.scope_ids)

@dataclass(frozen=True)
class ResponsibilityDisposition:
    expected_revision: int; requirement_id: str; actor: ActorAssertion; asserted_at: str; status: str; rationale: str
    responsibility: ClassVar[Responsibility]
    allowed_statuses: ClassVar[frozenset[str]] = frozenset({"satisfied", "declined"})
    def __post_init__(self) -> None:
        if self.expected_revision < 0 or self.status not in self.allowed_statuses or not self.rationale: raise ContractError("invalid responsibility disposition")

@dataclass(frozen=True)
class QuestionSelectionDisposition(ResponsibilityDisposition):
    responsibility: ClassVar[Responsibility] = Responsibility.QUESTION_SELECTION
    selected_normalized_question: str = ""; rejected_alternatives: tuple[Mapping[str, str], ...] = ()
@dataclass(frozen=True)
class SafetyEthicsReviewDisposition(ResponsibilityDisposition):
    responsibility: ClassVar[Responsibility] = Responsibility.SAFETY_ETHICS_REVIEW
    proposal_id: str = ""; proposal_hash: str = ""; risk_findings: tuple[str, ...] = (); export_only_boundary_confirmed: bool = False
@dataclass(frozen=True)
class ExecutionAccountabilityDisposition(ResponsibilityDisposition):
    responsibility: ClassVar[Responsibility] = Responsibility.EXECUTION_ACCOUNTABILITY
    proposal_id: str = ""; proposal_hash: str = ""; handoff_owner: ActorAssertion | None = None; execution_boundary: StageBoundary | None = None
@dataclass(frozen=True)
class ExceptionInterpretationDisposition(ResponsibilityDisposition):
    responsibility: ClassVar[Responsibility] = Responsibility.EXCEPTION_INTERPRETATION
    allowed_statuses: ClassVar[frozenset[str]] = frozenset({"satisfied", "declined", "not_applicable"})
    result_ids: tuple[str, ...] = (); result_hashes: tuple[str, ...] = (); deviations: tuple[Mapping[str, str], ...] = (); no_exception_assertion: bool = False
    def __post_init__(self) -> None:
        super().__post_init__()
        if self.status == "not_applicable" and (self.deviations or not self.no_exception_assertion): raise ContractError("not_applicable requires no deviations and an assertion")
@dataclass(frozen=True)
class NoveltyValueJudgmentDisposition(ResponsibilityDisposition):
    responsibility: ClassVar[Responsibility] = Responsibility.NOVELTY_VALUE_JUDGMENT
    claim_ids: tuple[str, ...] = (); judgment: str = ""; limitations: tuple[str, ...] = ()
@dataclass(frozen=True)
class FinalAccountabilityDisposition(ResponsibilityDisposition):
    responsibility: ClassVar[Responsibility] = Responsibility.FINAL_ACCOUNTABILITY
    report_body_id: str = ""; report_body_hash: str = ""; reviewed_exact_bytes: bool = False; limitations_acknowledged: bool = False

@dataclass(frozen=True)
class ValidationDimensions:
    model_confidence: str | None; evidence_quality: EvidenceQuality; validation_level: ValidationLevel
    result_outcome: Outcome; assessment_state: AssessmentState; support: Support
    def __post_init__(self) -> None:
        if self.model_confidence is not None and not _CONFIDENCE.fullmatch(self.model_confidence): raise ContractError("invalid confidence")

@dataclass(frozen=True)
class ProtocolEnvelope:
    protocol: str; protocol_version: str; kind: str; name: str; message_id: str; cycle_id: str | None
    correlation_id: str | None; causation_id: str | None; sequence: int; revision: int; idempotency_key: str | None
    timestamp: str; payload: Mapping[str, Any]; extensions: Mapping[str, Any]
    def __post_init__(self) -> None:
        if (self.protocol != PROTOCOL or self.protocol_version != PROTOCOL_VERSION
                or self.kind not in {"action", "event", "response", "error", "snapshot", "diagnostic"}
                or not isinstance(self.name, str) or not _ID.fullmatch(self.message_id)
                or any(value is not None and (not isinstance(value, str) or not _ID.fullmatch(value))
                       for value in (self.cycle_id, self.correlation_id, self.causation_id))
                or not _is_integer(self.sequence) or not _is_integer(self.revision)
                or (self.idempotency_key is not None and (not isinstance(self.idempotency_key, str) or not self.idempotency_key))
                or not _TIMESTAMP.fullmatch(self.timestamp)
                or not isinstance(self.payload, Mapping) or not isinstance(self.extensions, Mapping)):
            raise ContractError("invalid protocol envelope")

CONTINUE_OPERATIONS = frozenset({"landscape.complete", "hypothesis.complete", "proposal.complete", "execution.not_run", "analysis.complete", "write.interim", "write.final", "cycle.complete"})
ADJUDICATION_MODES = frozenset({"create", "transition"})
ACTIONS = frozenset({"protocol.hello", "cycle.start", "cycle.replay", "cycle.resume", "cycle.continue", "proposal.reject", "result.submit", "validation.adjudicate", "export.create", "export.get", "report.render", "cycle.abort", "cycle.ack", "responsibility.disposition.supersede", *(f"responsibility.{r.value}.disposition" for r in Responsibility)})
EVENTS = frozenset({"cycle.started", "cycle.continued", "cycle.completed", "responsibility.disposition.recorded", "responsibility.disposition.superseded", "proposal.rejected", "result.recorded", "validation.assessment.recorded", "validation.assessment.transitioned", "export.created", "cycle.aborted"})
ERRORS = frozenset({"protocol_invalid", "protocol_unsupported", "unknown_action", "validation_failed", "unsupported_transition", "supersession_conflict", "import_forbidden", "export_too_large", "feature_disabled", "capability_required", "read_only", "policy_required", "gate_unsatisfied", "idempotency_conflict", "revision_conflict", "cursor_ahead", "cursor_mismatch", "ack_mismatch", "not_found", "artifact_not_found", "repository_corrupt", "commit_outcome_unknown"})

_ENVELOPE_FIELDS = frozenset({
    "protocol", "protocol_version", "kind", "name", "message_id", "cycle_id",
    "correlation_id", "causation_id", "sequence", "revision", "idempotency_key",
    "timestamp", "payload", "extensions",
})
_ID = re.compile(r"[a-z][a-z0-9_]*_[0-9a-f]{32}\Z")


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _SAFE_INTEGER


def _validate_named_shapes(value: Any, *, field: str | None = None) -> None:
    """Reject lossy wire values and enforce frozen identifier/hash field shapes."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key.endswith("_id") and item is not None and (not isinstance(item, str) or not _ID.fullmatch(item)):
                raise ContractError(f"{key} must be a protocol ID or null")
            if key.endswith("_hash") and (not isinstance(item, str) or not _DIGEST.fullmatch(item)):
                raise ContractError(f"{key} must be a sha256 hash")
            if key.endswith("_at") and item is not None and (not isinstance(item, str) or not _TIMESTAMP.fullmatch(item)):
                raise ContractError(f"{key} must be a timestamp or null")
            _validate_named_shapes(item, field=key)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_named_shapes(item, field=field)


def _exact_payload(payload: Mapping[str, Any], fields: frozenset[str], action: str) -> None:
    if set(payload) != fields:
        raise ContractError(f"{action} payload fields are frozen")

def _validate_cursor(cursor: Any) -> None:
    if (not isinstance(cursor, Mapping) or set(cursor) != {"cycle_id", "sequence", "event_hash"}
            or not isinstance(cursor["cycle_id"], str) or not _ID.fullmatch(cursor["cycle_id"])
            or not _is_integer(cursor["sequence"])
            or not isinstance(cursor["event_hash"], str) or not _DIGEST.fullmatch(cursor["event_hash"])):
        raise ContractError("invalid cursor")


def _validate_connection_request(payload: Mapping[str, Any]) -> None:
    if (not isinstance(payload["client_instance_id"], str)
            or not _ID.fullmatch(payload["client_instance_id"])
            or not _is_integer(payload["request_ordinal"])
            or payload["request_ordinal"] < 1):
        raise ContractError("invalid connection request ordinal")



def validate_protocol_action(obj: Mapping[str, Any]) -> None:
    """Validate a complete, closed v1 action frame before lifecycle dispatch."""
    if set(obj) != _ENVELOPE_FIELDS:
        raise ContractError("protocol envelope fields are frozen")
    if obj.get("protocol") != PROTOCOL or obj.get("protocol_version") != PROTOCOL_VERSION:
        raise ContractError("unsupported protocol envelope")
    if obj.get("kind") != "action" or obj.get("name") not in ACTIONS:
        raise ContractError("unknown protocol action")
    for field in ("message_id",):
        if not isinstance(obj.get(field), str) or not _ID.fullmatch(obj[field]):
            raise ContractError(f"{field} must be a protocol ID")
    for field in ("cycle_id", "correlation_id", "causation_id"):
        if obj[field] is not None and (not isinstance(obj[field], str) or not _ID.fullmatch(obj[field])):
            raise ContractError(f"{field} must be a protocol ID or null")
    if (
        obj.get("sequence") != 0
        or isinstance(obj.get("sequence"), bool)
        or obj.get("revision") != 0
        or isinstance(obj.get("revision"), bool)
        or obj.get("correlation_id") != obj["message_id"]
        or obj.get("causation_id") is not None
    ):
        raise ContractError("root actions require zero coordinates and message correlation")
    if obj["idempotency_key"] is not None and (not isinstance(obj["idempotency_key"], str) or not obj["idempotency_key"]):
        raise ContractError("idempotency_key must be a nonempty string or null")
    if not isinstance(obj.get("timestamp"), str) or not _TIMESTAMP.fullmatch(obj["timestamp"]):
        raise ContractError("timestamp must be a UTC microsecond timestamp")
    if not isinstance(obj.get("payload"), Mapping) or not isinstance(obj.get("extensions"), Mapping) or obj["extensions"]:
        raise ContractError("payload must be an object and extensions must be empty")
    read_actions = {"cycle.replay", "cycle.resume", "export.get", "report.render", "cycle.ack"}
    if obj["name"] in read_actions:
        if obj["idempotency_key"] is not None:
            raise ContractError("read actions require a null idempotency key")
    elif obj["idempotency_key"] is None:
        raise ContractError("mutation and handshake actions require an idempotency key")
    _validate_jcs_subset(obj)
    payload = obj["payload"]
    name = obj["name"]
    if name == "protocol.hello":
        _exact_payload(payload, frozenset({
            "handshake_idempotency_key", "client_instance_id", "supported_versions",
            "capabilities", "projection", "cursors",
        }), name)
        if (payload["handshake_idempotency_key"] != obj["idempotency_key"]
                or not isinstance(payload["handshake_idempotency_key"], str)
                or not payload["handshake_idempotency_key"]
                or not isinstance(payload["client_instance_id"], str)
                or not _ID.fullmatch(payload["client_instance_id"])
                or not isinstance(payload["supported_versions"], list)
                or not payload["supported_versions"]
                or not all(isinstance(version, str) for version in payload["supported_versions"])
                or not isinstance(payload["capabilities"], list)
                or not all(isinstance(capability, str) for capability in payload["capabilities"])
                or not isinstance(payload["projection"], str)
                or not isinstance(payload["cursors"], list)):
            raise ContractError("invalid protocol.hello payload")
        for cursor in payload["cursors"]:
            _validate_cursor(cursor)
    elif name == "cycle.start":
        _exact_payload(payload, frozenset({"creation_idempotency_key", "expected_revision", "raw_question", "contract_version", "boundary", "creator"}), name)
        if (payload["creation_idempotency_key"] != obj["idempotency_key"]
                or not _is_integer(payload["expected_revision"]) or payload["expected_revision"] != 0
                or not isinstance(payload["contract_version"], str)
                or payload["contract_version"] != PROTOCOL_VERSION):
            raise ContractError("cycle.start requires matching creation identity and the frozen contract version")
        actor_assertion_from_mapping(payload["creator"])
        stage_boundary_from_mapping(payload["boundary"])
    elif name == "cycle.replay":
        _exact_payload(payload, frozenset({"client_instance_id", "request_ordinal", "cursor", "max_events"}), name)
        _validate_connection_request(payload)
        _validate_cursor(payload["cursor"])
        if not _is_integer(payload["max_events"]) or not 1 <= payload["max_events"] <= 128:
            raise ContractError("cycle.replay max_events must be between 1 and 128")
    elif name == "cycle.resume":
        _exact_payload(payload, frozenset({"client_instance_id", "request_ordinal", "cycle_id", "cursor", "projection"}), name)
        _validate_connection_request(payload)
        _validate_cursor(payload["cursor"])
        if payload["cycle_id"] != payload["cursor"]["cycle_id"] or not isinstance(payload["projection"], str):
            raise ContractError("invalid cycle.resume payload")
    elif name == "cycle.ack":
        _exact_payload(payload, frozenset({"client_instance_id", "ack_ordinal", "checkpoint", "state_hash"}), name)
        if (not isinstance(payload["client_instance_id"], str) or not _ID.fullmatch(payload["client_instance_id"])
                or not _is_integer(payload["ack_ordinal"]) or payload["ack_ordinal"] < 1
                or not isinstance(payload["state_hash"], str) or not _DIGEST.fullmatch(payload["state_hash"])):
            raise ContractError("invalid cycle.ack payload")
        _validate_cursor(payload["checkpoint"])
    elif name == "export.create":
        validate_export_payload(payload)
    elif name == "export.get":
        _exact_payload(payload, frozenset({
            "client_instance_id", "request_ordinal", "export_id", "include_archive_bytes",
        }), name)
        _validate_connection_request(payload)
        if (not isinstance(payload["export_id"], str) or not _ID.fullmatch(payload["export_id"])
                or not isinstance(payload["include_archive_bytes"], bool)):
            raise ContractError("invalid export.get payload")
    elif name == "report.render":
        _exact_payload(payload, frozenset({
            "client_instance_id", "request_ordinal", "cycle_id", "at_revision", "format",
            "include_status_overlay",
        }), name)
        _validate_connection_request(payload)
        if (not isinstance(payload["cycle_id"], str) or not _ID.fullmatch(payload["cycle_id"])
                or not _is_integer(payload["at_revision"])
                or payload["format"] not in {"canonical_json", "markdown", "html"}
                or not isinstance(payload["include_status_overlay"], bool)):
            raise ContractError("invalid report.render payload")
    elif name == "cycle.abort":
        _exact_payload(payload, frozenset({"expected_revision", "actor", "reason", "final_observation"}), name)
        actor_assertion_from_mapping(payload["actor"])
        if (not _is_integer(payload["expected_revision"]) or not isinstance(payload["reason"], str)
                or not payload["reason"] or not isinstance(payload["final_observation"], str)):
            raise ContractError("invalid cycle.abort payload")
    elif name == "responsibility.disposition.supersede":
        validate_supersede_payload(payload)
    elif name == "proposal.reject":
        _exact_payload(
            payload,
            frozenset({"expected_revision", "proposal_id", "proposal_hash", "actor", "reason", "recoverable"}),
            name,
        )
        actor_assertion_from_mapping(payload["actor"])
        if (
            not _is_integer(payload["expected_revision"])
            or not isinstance(payload["reason"], str)
            or not payload["reason"]
            or not isinstance(payload["recoverable"], bool)
        ):
            raise ContractError("invalid proposal.reject payload")
    elif name == "result.submit":
        validate_result_submit_payload(payload)
    elif name.startswith("responsibility.") and name.endswith(".disposition"):
        validate_disposition_payload(name.split(".")[1], payload)
    elif name == "cycle.continue":
        validate_continue_payload(payload)
    elif name == "validation.adjudicate":
        validate_adjudication_payload(payload)
    _validate_named_shapes(payload)


def validate_result_submit_payload(payload: Mapping[str, Any]) -> None:
    fields = frozenset({
        "expected_revision", "proposal_id", "proposal_hash", "supersedes_result_id",
        "execution_kind", "accountable_party", "performers", "started_at",
        "completed_at", "external_references", "staged_blob_ids",
        "result_manifest", "deviations",
    })
    _exact_payload(payload, fields, "result.submit")
    if (
        not _is_integer(payload["expected_revision"])
        or not isinstance(payload["proposal_id"], str)
        or not _ID.fullmatch(payload["proposal_id"])
        or not isinstance(payload["proposal_hash"], str)
        or not _DIGEST.fullmatch(payload["proposal_hash"])
        or payload["execution_kind"] not in {"computational", "physical"}
        or not isinstance(payload["performers"], list)
        or not payload["performers"]
        or not isinstance(payload["external_references"], list)
        or not payload["external_references"]
        or not isinstance(payload["staged_blob_ids"], list)
        or not payload["staged_blob_ids"]
        or not isinstance(payload["result_manifest"], Mapping)
        or not isinstance(payload["deviations"], list)
        or (
            payload["supersedes_result_id"] is not None
            and (
                not isinstance(payload["supersedes_result_id"], str)
                or not _ID.fullmatch(payload["supersedes_result_id"])
            )
        )
    ):
        raise ContractError("invalid result.submit payload")
    try:
        started = datetime.strptime(payload["started_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        completed = datetime.strptime(payload["completed_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
    except (TypeError, ValueError) as exc:
        raise ContractError("result timestamps must be canonical UTC timestamps") from exc
    if not _TIMESTAMP.fullmatch(payload["started_at"]) or not _TIMESTAMP.fullmatch(payload["completed_at"]) or started > completed:
        raise ContractError("invalid result timestamps")
    actor = actor_assertion_from_mapping(payload["accountable_party"])
    if actor["actor_kind"] != ActorKind.HUMAN.value:
        raise ContractError("external result accountability requires a human actor")
    for performer in payload["performers"]:
        performer_from_mapping(performer)
    for reference in payload["external_references"]:
        external_reference_from_mapping(reference)
    if not all(isinstance(blob_id, str) and _ID.fullmatch(blob_id) for blob_id in payload["staged_blob_ids"]) or len(set(payload["staged_blob_ids"])) != len(payload["staged_blob_ids"]):
        raise ContractError("staged blob IDs must be canonical and unique")
    _validate_jcs_subset(payload["result_manifest"])
    _validate_jcs_subset(payload["deviations"])
def validate_export_payload(payload: Mapping[str, Any]) -> None:
    fields = frozenset({
        "expected_revision", "format", "artifact_ids", "report_body_id",
        "redaction_profile_id", "external_reference_ids",
    })
    _exact_payload(payload, fields, "export.create")
    if (not _is_integer(payload["expected_revision"])
            or payload["format"] != "scientific-export.v1"
            or not isinstance(payload["artifact_ids"], list)
            or not isinstance(payload["external_reference_ids"], list)
            or not all(isinstance(value, str) and _ID.fullmatch(value)
                       for value in payload["artifact_ids"] + payload["external_reference_ids"])
            or (payload["report_body_id"] is not None
                and (not isinstance(payload["report_body_id"], str)
                     or not _ID.fullmatch(payload["report_body_id"])))
            or (payload["redaction_profile_id"] is not None
                and (not isinstance(payload["redaction_profile_id"], str)
                     or not _ID.fullmatch(payload["redaction_profile_id"])))):
        raise ContractError("invalid export.create payload")
    canonical_id_array(payload["artifact_ids"])
    canonical_id_array(payload["external_reference_ids"])
def validate_continue_payload(payload: Mapping[str, Any]) -> None:
    if (set(payload) != {"expected_revision", "operation", "stage_input"}
            or not _is_integer(payload.get("expected_revision"))
            or payload.get("operation") not in CONTINUE_OPERATIONS
            or not isinstance(payload.get("stage_input"), Mapping)
            or payload["stage_input"].get("kind") != payload["operation"]):
        raise ContractError("cycle.continue requires a matching frozen discriminator")
    common = {"kind", "accountable_party", "performers", "execution_kind", "automation_mode", "boundary", "started_at", "completed_at"}
    fields = {
        "landscape.complete": common | {"invalidate_current_proposal", "landscape_artifacts"},
        "hypothesis.complete": common | {"invalidate_current_proposal", "claims"},
        "proposal.complete": common | {"proposal"},
        "execution.not_run": {"kind", "proposal_id", "proposal_hash", "status", "execution_kind", "accountable_party", "performers", "automation_mode", "boundary", "started_at", "completed_at", "artifact_ids", "result_ids"},
        "analysis.complete": common | {"result_ids", "analysis_artifacts"},
        "write.interim": common | {"source_revision", "source_artifact_ids", "claim_ids", "result_ids", "analysis_artifact_ids", "limitations"},
        "write.final": common | {"source_revision", "source_artifact_ids", "claim_ids", "result_ids", "analysis_artifact_ids", "limitations"},
        "cycle.complete": {"kind", "report_stage_id", "report_body_id", "report_body_hash", "final_accountability_requirement_id", "final_accountability_disposition_id"},
    }
    if set(payload["stage_input"]) != fields[payload["operation"]]:
        raise ContractError("cycle.continue stage input fields are frozen")
    if payload["operation"] in {"landscape.complete", "hypothesis.complete"} and not isinstance(
            payload["stage_input"]["invalidate_current_proposal"], bool):
        raise ContractError("invalidate_current_proposal must be a boolean")
    data = payload["stage_input"]
    if payload["operation"] == "execution.not_run":
        if (data["status"], data["execution_kind"], data["accountable_party"], data["performers"],
                data["automation_mode"], data["started_at"], data["completed_at"]) != (
                    "not_run", "not_run", None, [], "not_run", None, None):
            raise ContractError("local X fields are frozen")
        stage_boundary_from_mapping(data["boundary"])
        return
    if payload["operation"] != "cycle.complete":
        actor_assertion_from_mapping(data["accountable_party"])
        if not isinstance(data["performers"], list) or not data["performers"]:
            raise ContractError("completed stages require performers")
        for performer in data["performers"]:
            performer_from_mapping(performer)
        stage_boundary_from_mapping(data["boundary"])
        if data["execution_kind"] not in {"cognitive", "computational"}:
            raise ContractError("completed stages must be non-physical")
        if data["automation_mode"] not in {"manual", "ai_assisted", "automated"}:
            raise ContractError("invalid automation mode")
        if not all(isinstance(data[field], str) and _TIMESTAMP.fullmatch(data[field])
                   for field in ("started_at", "completed_at")):
            raise ContractError("completed stages require timestamps")
    for field in ("source_artifact_ids", "claim_ids", "result_ids", "analysis_artifact_ids",
                  "artifact_ids"):
        if field in data:
            canonical_id_array(data[field])

def validate_supersede_payload(payload: Mapping[str, Any]) -> None:
    fields = frozenset({
        "expected_revision", "responsibility", "requirement_id",
        "superseded_disposition_id", "rationale", "replacement_disposition",
    })
    if set(payload) != fields or not _is_integer(payload.get("expected_revision")):
        raise ContractError("responsibility disposition supersede fields are frozen")
    responsibility = payload.get("responsibility")
    if not isinstance(responsibility, str):
        raise ContractError("invalid responsibility disposition supersede")
    try:
        Responsibility(responsibility)
    except ValueError as exc:
        raise ContractError("invalid responsibility disposition supersede") from exc
    if (
        not isinstance(payload.get("requirement_id"), str)
        or not _ID.fullmatch(payload["requirement_id"])
        or not isinstance(payload.get("superseded_disposition_id"), str)
        or not _ID.fullmatch(payload["superseded_disposition_id"])
        or not isinstance(payload.get("rationale"), str)
        or not payload["rationale"]
    ):
        raise ContractError("invalid responsibility disposition supersede")
    replacement = payload["replacement_disposition"]
    if replacement is not None:
        if not isinstance(replacement, Mapping):
            raise ContractError("invalid replacement disposition")
        validate_disposition_payload(responsibility, replacement)
def validate_disposition_payload(responsibility: str, payload: Mapping[str, Any]) -> None:
    fields = frozenset({"expected_revision", "requirement_id", "actor", "asserted_at", "status", "rationale", "scope_hash", "details"})
    if set(payload) != fields or not _is_integer(payload.get("expected_revision")):
        raise ContractError("responsibility disposition fields are frozen")
    if (not isinstance(payload.get("requirement_id"), str) or not _ID.fullmatch(payload["requirement_id"])
            or not isinstance(payload.get("scope_hash"), str) or not _DIGEST.fullmatch(payload["scope_hash"])
            or not isinstance(payload.get("actor"), Mapping)
            or not isinstance(payload.get("asserted_at"), str) or not _TIMESTAMP.fullmatch(payload["asserted_at"])
            or not isinstance(payload.get("status"), str)
            or not isinstance(payload.get("rationale"), str) or not payload["rationale"]):
        raise ContractError("invalid responsibility disposition fields")
    actor_assertion_from_mapping(payload["actor"])
    detail_fields = {
        "question_selection": {"selected_normalized_question", "rejected_alternatives"},
        "safety_ethics_review": {"proposal_id", "proposal_hash", "risk_findings", "export_only_boundary_confirmed"},
        "execution_accountability": {"proposal_id", "proposal_hash", "handoff_owner", "execution_boundary"},
        "exception_interpretation": {"result_ids", "result_hashes", "deviations", "no_exception_assertion"},
        "novelty_value_judgment": {"claim_ids", "judgment", "limitations"},
        "final_accountability": {"report_body_id", "report_body_hash", "reviewed_exact_bytes", "limitations_acknowledged"},
    }
    details = payload.get("details")
    if responsibility not in detail_fields or not isinstance(details, Mapping) or set(details) != detail_fields[responsibility]:
        raise ContractError("responsibility disposition details are frozen")
    for field in ("claim_ids", "result_ids"):
        if field in details:
            canonical_id_array(details[field])
    for field in ("risk_findings", "limitations", "result_hashes"):
        if field in details and (not isinstance(details[field], list) or not all(isinstance(item, str) for item in details[field])):
            raise ContractError(f"{field} must be a string array")
    if responsibility == "question_selection":
        if not isinstance(details["selected_normalized_question"], str) or not isinstance(details["rejected_alternatives"], list):
            raise ContractError("invalid question-selection details")
    elif responsibility == "safety_ethics_review":
        if (not isinstance(details["proposal_id"], str) or not _ID.fullmatch(details["proposal_id"])
                or not isinstance(details["proposal_hash"], str) or not _DIGEST.fullmatch(details["proposal_hash"])
                or not isinstance(details["risk_findings"], list) or not all(isinstance(item, str) for item in details["risk_findings"])
                or not isinstance(details["export_only_boundary_confirmed"], bool)):
            raise ContractError("invalid safety-review details")
    elif responsibility == "execution_accountability":
        if (not isinstance(details["proposal_id"], str) or not _ID.fullmatch(details["proposal_id"])
                or not isinstance(details["proposal_hash"], str) or not _DIGEST.fullmatch(details["proposal_hash"])
                or not isinstance(details["handoff_owner"], Mapping) or not isinstance(details["execution_boundary"], Mapping)):
            raise ContractError("invalid execution-accountability details")
        actor_assertion_from_mapping(details["handoff_owner"])
        boundary = stage_boundary_from_mapping(details["execution_boundary"])
        if boundary["kind"] != "export_only":
            raise ContractError("execution accountability requires an export-only boundary")
    elif responsibility == "exception_interpretation":
        if (not isinstance(details["deviations"], list) or not all(isinstance(item, Mapping) for item in details["deviations"])
                or not isinstance(details["no_exception_assertion"], bool)):
            raise ContractError("invalid exception-interpretation details")
    elif responsibility == "novelty_value_judgment":
        if not isinstance(details["judgment"], str):
            raise ContractError("invalid novelty-value details")
    elif responsibility == "final_accountability":
        if (not isinstance(details["report_body_id"], str) or not _ID.fullmatch(details["report_body_id"])
                or not isinstance(details["report_body_hash"], str) or not _DIGEST.fullmatch(details["report_body_hash"])
                or not isinstance(details["reviewed_exact_bytes"], bool)
                or not isinstance(details["limitations_acknowledged"], bool)):
            raise ContractError("invalid final-accountability details")


def validate_policy_tuple(policy_id: str, version: str, reference: ExternalReference | None) -> None:
    if not isinstance(policy_id, str) or not isinstance(version, str):
        raise ContractError("validation policy ID and version must be strings")
    general = policy_id == "muchanipo.validation.general" and version == "1.0.0"
    external = bool(_EXTERNAL_POLICY.fullmatch(policy_id)) and bool(version) and reference is not None
    if not ((general and reference is None) or external):
        raise ContractError("invalid validation policy tuple")
def validate_adjudication_payload(payload: Mapping[str, Any]) -> None:
    create_assessment_fields = frozenset({
        "claim_ids", "result_ids", "analysis_stage_id", "analysis_artifact_ids",
        "model_confidence", "evidence_quality", "validation_level", "result_outcome",
        "assessment_state", "applicability", "covered_scope", "method", "checks",
        "assessor", "qualifications", "validation_policy_id",
        "validation_policy_version", "validation_policy_reference", "rationale",
    })
    transition_fields = frozenset({
        "expected_revision", "mode", "assessment_id", "from_state", "to_state",
        "claim_ids", "result_ids", "analysis_stage_id", "analysis_artifact_ids",
        "actor", "qualification_evidence", "validation_policy_id",
        "validation_policy_version", "validation_policy_reference", "rationale",
    })
    if not isinstance(payload, Mapping) or payload.get("mode") not in ADJUDICATION_MODES:
        raise ContractError("unknown adjudication mode")
    mode = payload["mode"]
    if mode == "create":
        if set(payload) != {"expected_revision", "mode", "assessment"} or not _is_integer(payload.get("expected_revision")):
            raise ContractError("create adjudication fields are frozen")
        source = payload["assessment"]
        if not isinstance(source, Mapping) or set(source) != create_assessment_fields:
            raise ContractError("create assessment fields are frozen")
        if source["assessment_state"] != AssessmentState.PENDING.value:
            raise ContractError("new assessments must be pending")
    else:
        if set(payload) != transition_fields or not _is_integer(payload.get("expected_revision")):
            raise ContractError("transition adjudication fields are frozen")
        source = payload
        if source["from_state"] == source["to_state"]:
            raise ContractError("assessment transition must change state")
        try:
            AssessmentState(source["from_state"])
            AssessmentState(source["to_state"])
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid assessment transition state") from exc
        actor_assertion_from_mapping(source["actor"])
        _validate_qualification_evidence(source["qualification_evidence"])
        if not isinstance(source["rationale"], str) or not source["rationale"]:
            raise ContractError("invalid assessment transition evidence")

    try:
        ValidationDimensions(
            source["model_confidence"] if mode == "create" else None,
            EvidenceQuality(source["evidence_quality"]) if mode == "create" else EvidenceQuality.UNKNOWN,
            ValidationLevel(source["validation_level"]) if mode == "create" else ValidationLevel.V0,
            Outcome(source["result_outcome"]) if mode == "create" else Outcome.NOT_APPLICABLE,
            AssessmentState(source["assessment_state"]) if mode == "create" else AssessmentState(source["to_state"]),
            Support(source["support"]) if mode == "create" and "support" in source else Support.PENDING,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid validation dimensions") from exc
    if mode == "create":
        if (not all(isinstance(source[field], str) and source[field] for field in
                    ("applicability", "covered_scope", "method", "rationale"))
                or not isinstance(source["checks"], list)
                or not all(isinstance(check, str) and check for check in source["checks"])
                or not isinstance(source["qualifications"], list)
                or not all(isinstance(item, Mapping) and set(item) == {"kind", "asserted_unverified"}
                           and isinstance(item["kind"], str) and item["kind"]
                           and item["asserted_unverified"] is True
                           for item in source["qualifications"])
                or not isinstance(source["assessor"], Mapping)):
            raise ContractError("invalid assessment fields")
        actor_assertion_from_mapping(source["assessor"])
    elif not isinstance(source["assessment_id"], str) or not _ID.fullmatch(source["assessment_id"]):
        raise ContractError("assessment_id must be a protocol ID")
    reference = source["validation_policy_reference"]
    canonical_reference = None if reference is None else external_reference_from_mapping(reference)
    validate_policy_tuple(source["validation_policy_id"], source["validation_policy_version"], canonical_reference)
    if not isinstance(source["analysis_stage_id"], str) or not _ID.fullmatch(source["analysis_stage_id"]):
        raise ContractError("analysis_stage_id must be a protocol ID")
    for field in ("claim_ids", "result_ids", "analysis_artifact_ids"):
        canonical_id_array(source[field], nonempty=True)


def _validate_qualification_evidence(value: Any) -> None:
    if not isinstance(value, list):
        raise ContractError("qualification evidence must be a list")
    for evidence in value:
        if not isinstance(evidence, Mapping) or set(evidence) != {"qualification", "actor"}:
            raise ContractError("qualification evidence fields are frozen")
        qualification = evidence["qualification"]
        if (not isinstance(qualification, Mapping)
                or set(qualification) != {"kind", "asserted_unverified"}
                or not isinstance(qualification["kind"], str)
                or not qualification["kind"]
                or qualification["asserted_unverified"] is not True):
            raise ContractError("qualification evidence must be asserted and unverified")
        actor_assertion_from_mapping(evidence["actor"])
