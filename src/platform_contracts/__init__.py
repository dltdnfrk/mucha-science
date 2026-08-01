"""Immutable domain record contracts for the Mucha Science platform.

Record identities and wire bytes are derived with the frozen canonicalization
utilities owned by :mod:`src.pipeline.scientific_contracts`.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import re
from types import MappingProxyType
from typing import ClassVar, Mapping, Self

from src.pipeline.scientific_contracts import (
    ContractError,
    canonical_json,
    decode_json_object,
    deterministic_id,
    digest,
)

_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ApplicationType(StrEnum):
    EX_VIVO_DIAGNOSTIC = "EX_VIVO_DIAGNOSTIC"
    CONTAINED_LAB = "CONTAINED_LAB"
    ENVIRONMENTAL_SPRAY = "ENVIRONMENTAL_SPRAY"
    ENVIRONMENTAL_COATING = "ENVIRONMENTAL_COATING"
    OTHER_ENVIRONMENTAL = "OTHER_ENVIRONMENTAL"


class ConstraintOwner(StrEnum):
    USER = "USER"
    PLATFORM_POLICY = "PLATFORM_POLICY"


class ConstraintOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ConstraintOperator(StrEnum):
    GTE = "GTE"
    LTE = "LTE"
    BETWEEN = "BETWEEN"
    EQ = "EQ"
    IN = "IN"


class QueryChange(StrEnum):
    ADD_OBJECTIVE = "ADD_OBJECTIVE"
    REMOVE_OBJECTIVE = "REMOVE_OBJECTIVE"
    SET_WEIGHT = "SET_WEIGHT"
    ADD_CONSTRAINT = "ADD_CONSTRAINT"
    REMOVE_CONSTRAINT = "REMOVE_CONSTRAINT"
    SET_APPLICATION_TYPE = "SET_APPLICATION_TYPE"


class EvidenceTier(StrEnum):
    PURIFIED_ENZYME = "PURIFIED_ENZYME"
    LYSATE = "LYSATE"
    WHOLE_ISOLATE = "WHOLE_ISOLATE"
    SPIKED_MATRIX = "SPIKED_MATRIX"
    RETROSPECTIVE_FIELD = "RETROSPECTIVE_FIELD"
    PROSPECTIVE_FIELD = "PROSPECTIVE_FIELD"


class ObservationOrigin(StrEnum):
    PLATFORM_ASSAY = "PLATFORM_ASSAY"
    EXPLORATORY_ASSAY = "EXPLORATORY_ASSAY"
    IMPORTED_EXTERNAL = "IMPORTED_EXTERNAL"


class PredictionOrigin(StrEnum):
    PLATFORM_COMPUTATION = "PLATFORM_COMPUTATION"
    EXTERNAL_COMPUTATION = "EXTERNAL_COMPUTATION"


class PairingDesign(StrEnum):
    PROSPECTIVE_LOCKED = "PROSPECTIVE_LOCKED"
    RETROSPECTIVE_BLINDED = "RETROSPECTIVE_BLINDED"
    EXTERNAL_PREEXISTING = "EXTERNAL_PREEXISTING"


class PairRelation(StrEnum):
    DIRECT_ESTIMAND = "DIRECT_ESTIMAND"
    DOWNSTREAM_CONTEXT = "DOWNSTREAM_CONTEXT"


class ResultKind(StrEnum):
    POINT = "POINT"
    INTERVAL = "INTERVAL"
    LEFT_CENSORED = "LEFT_CENSORED"
    RIGHT_CENSORED = "RIGHT_CENSORED"
    CATEGORICAL = "CATEGORICAL"
    FAILED = "FAILED"


class QCStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


class PredictionEpistemicStatus(StrEnum):
    RANKABLE_PREDICTION = "RANKABLE_PREDICTION"
    HYPOTHESIS_ONLY = "HYPOTHESIS_ONLY"


class GateOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class CandidateDisposition(StrEnum):
    RANKED = "RANKED"
    EXCLUDED = "EXCLUDED"
    ABSTAINED = "ABSTAINED"


class AbstentionReason(StrEnum):
    MISSING_REQUIRED_PREDICTION = "MISSING_REQUIRED_PREDICTION"
    LOW_STRUCTURE_CONFIDENCE = "LOW_STRUCTURE_CONFIDENCE"
    STRUCTURE_ENSEMBLE_DISAGREEMENT = "STRUCTURE_ENSEMBLE_DISAGREEMENT"
    OLIGOMER_STATE_AMBIGUOUS = "OLIGOMER_STATE_AMBIGUOUS"
    COFACTOR_STATE_AMBIGUOUS = "COFACTOR_STATE_AMBIGUOUS"
    OUT_OF_DISTRIBUTION = "OUT_OF_DISTRIBUTION"
    UNCERTAINTY_TOO_HIGH = "UNCERTAINTY_TOO_HIGH"
    UNCALIBRATED_PREDICTOR_VERSION = "UNCALIBRATED_PREDICTOR_VERSION"
    REQUIRED_PROVENANCE_MISSING = "REQUIRED_PROVENANCE_MISSING"
    ADAPTER_LIMITATION_TRIGGERED = "ADAPTER_LIMITATION_TRIGGERED"
    CONFLICTING_SUPPORT = "CONFLICTING_SUPPORT"
    MANDATORY_CONSTRAINT_UNRESOLVED = "MANDATORY_CONSTRAINT_UNRESOLVED"


class ObjectiveEvaluationStatus(StrEnum):
    SCORED = "SCORED"
    HYPOTHESIS_ONLY = "HYPOTHESIS_ONLY"
    ABSTAINED = "ABSTAINED"


class BenchmarkSplitRole(StrEnum):
    NONE = "NONE"
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class SourceKind(StrEnum):
    PUBLICATION = "PUBLICATION"
    DATABASE_RECORD = "DATABASE_RECORD"
    DATASET_RELEASE = "DATASET_RELEASE"
    WEB_RESOURCE = "WEB_RESOURCE"
    USER_FILE = "USER_FILE"
    EXPERIMENTAL_IMPORT = "EXPERIMENTAL_IMPORT"


class LicenseDecision(StrEnum):
    ALLOWED = "ALLOWED"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"
    DENIED = "DENIED"


class VersionStatus(StrEnum):
    PINNED = "PINNED"
    UNVERSIONED = "UNVERSIONED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ControlType(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    BLANK = "BLANK"
    VEHICLE = "VEHICLE"
    MATRIX = "MATRIX"
    PROCESS = "PROCESS"


class ReportingStatus(StrEnum):
    REPORTED = "REPORTED"
    NOT_REPORTED = "NOT_REPORTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ModifierRole(StrEnum):
    PERMEABILIZER = "PERMEABILIZER"
    INHIBITOR = "INHIBITOR"
    COFACTOR = "COFACTOR"
    BUFFER = "BUFFER"
    OTHER = "OTHER"


class ClaimOrigin(StrEnum):
    LITERATURE_EXTRACTION = "LITERATURE_EXTRACTION"
    MEASUREMENT_ANALYSIS = "MEASUREMENT_ANALYSIS"
    COUNCIL = "COUNCIL"
    COMPUTATION = "COMPUTATION"
    HUMAN = "HUMAN"


class EntailmentDecision(StrEnum):
    ENTAILED = "ENTAILED"
    CONTRADICTED = "CONTRADICTED"
    NOT_ENOUGH_INFORMATION = "NOT_ENOUGH_INFORMATION"


class Applicability(StrEnum):
    DIRECT = "DIRECT"
    PARTIAL = "PARTIAL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNKNOWN = "UNKNOWN"


class ClaimStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SelectorType(StrEnum):
    UTF8_BYTE_RANGE = "UTF8_BYTE_RANGE"
    PDF_PAGE_BOX = "PDF_PAGE_BOX"
    JSON_POINTER = "JSON_POINTER"
    TABLE_CELL = "TABLE_CELL"


class VerifierMethod(StrEnum):
    HUMAN = "HUMAN"
    MODEL = "MODEL"
    RULE = "RULE"


ALL_ENUM_TYPES: tuple[type[StrEnum], ...] = (
    ApplicationType, ConstraintOwner, ConstraintOutcome, ConstraintOperator, QueryChange,
    EvidenceTier, ObservationOrigin, PredictionOrigin, PairingDesign, PairRelation,
    ResultKind, QCStatus, PredictionEpistemicStatus, GateOutcome,
    CandidateDisposition, AbstentionReason, ObjectiveEvaluationStatus,
    BenchmarkSplitRole, SourceKind,
    LicenseDecision, VersionStatus, ControlType, ReportingStatus, ModifierRole,
    ClaimOrigin, EntailmentDecision, Applicability, ClaimStatus, ApprovalStatus,
    SelectorType, VerifierMethod,
)


def _plain(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and isinstance(value, _Contract):
        return value.to_content()
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _freeze(value: object) -> object:
    """Recursively freeze canonical container values held by frozen records."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: object, name: str, required: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != required or any(not isinstance(key, str) for key in value):
        raise ContractError(f"{name} fields are frozen")
    return value


def _record_content(value: object, name: str, required: set[str]) -> Mapping[str, object]:
    result = _mapping(value, name, required)
    canonical_json(result)
    return result


def _string(value: object, name: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ContractError(f"{name} must be a nonempty string" + (" or null" if nullable else ""))
    return value


def _timestamp(value: object, name: str, *, nullable: bool = False) -> str | None:
    text = _string(value, name, nullable=nullable)
    if text is not None and not _TIMESTAMP.fullmatch(text):
        raise ContractError(f"{name} must be a canonical UTC timestamp")
    return text


def _hash(value: object, name: str, *, nullable: bool = False) -> str | None:
    text = _string(value, name, nullable=nullable)
    if text is not None and not _DIGEST.fullmatch(text):
        raise ContractError(f"{name} must be a sha256 digest")
    return text


def _integer(value: object, name: str, *, minimum: int = 0, maximum: int = 9_007_199_254_740_991) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ContractError(f"{name} must be an integer from {minimum} through {maximum}")
    return value


def _optional_integer(value: object, name: str, *, minimum: int = 0, maximum: int = 9_007_199_254_740_991) -> int | None:
    if value is None:
        return None
    return _integer(value, name, minimum=minimum, maximum=maximum)


def _sequence(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{name} must be an array")
    return tuple(value)


def _strings(value: object, name: str) -> tuple[str, ...]:
    items = _sequence(value, name)
    if any(not isinstance(item, str) or not item for item in items):
        raise ContractError(f"{name} must contain nonempty strings")
    return tuple(item for item in items if isinstance(item, str))


def _enum(enum_type: type[StrEnum], value: object, name: str) -> StrEnum:
    if not isinstance(value, str):
        raise ContractError(f"{name} must be a {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ContractError(f"unknown {enum_type.__name__}: {value}") from exc


def _object(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractError(f"{name} must be an object")
    canonical_json(value)
    return dict(value)


class _Contract:
    ID_FIELD: ClassVar[str | None] = None
    ID_KIND: ClassVar[str | None] = None

    def __post_init__(self) -> None:
        for field in fields(self):
            if field.name != self.ID_FIELD:
                object.__setattr__(self, field.name, _freeze(getattr(self, field.name)))
        self._assign_id()

    def to_content(self) -> dict[str, object]:
        return {
            field.name: _plain(getattr(self, field.name))
            for field in fields(self)
            if field.name != self.ID_FIELD
        }

    @property
    def content_hash(self) -> str:
        return digest(self.to_content())

    @property
    def record_id(self) -> str | None:
        return getattr(self, self.ID_FIELD) if self.ID_FIELD is not None else None

    def _assign_id(self) -> None:
        if self.ID_FIELD is not None and self.ID_KIND is not None:
            identifier = deterministic_id(self.ID_KIND, {"content_hash": self.content_hash})
            object.__setattr__(self, self.ID_FIELD, identifier)

    def to_payload(self) -> dict[str, object]:
        payload = self.to_content()
        if self.ID_FIELD is not None:
            return {self.ID_FIELD: self.record_id, **payload}
        return payload

    def to_json(self) -> bytes:
        return canonical_json(self.to_payload())

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Self:
        if not isinstance(payload, Mapping):
            raise ContractError(f"{cls.__name__} payload must be an object")
        material = dict(payload)
        supplied_id: object | None = None
        if cls.ID_FIELD is not None:
            expected = {field.name for field in fields(cls)}
            material = dict(_mapping(payload, cls.__name__, expected))
            supplied_id = material.pop(cls.ID_FIELD)
        record = cls.from_content(material)
        if cls.ID_FIELD is not None and supplied_id != record.record_id:
            raise ContractError(f"{cls.ID_FIELD} does not match canonical content")
        return record

    @classmethod
    def from_json(cls, raw: str | bytes) -> Self:
        value = decode_json_object(raw)
        if not isinstance(value, Mapping):
            raise ContractError(f"{cls.__name__} JSON must be an object")
        return cls.from_payload(value)

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        raise NotImplementedError


@dataclass(frozen=True)
class ObjectiveTerm(_Contract):
    term_id: str
    objective_ref: Mapping[str, object]
    weight_units: int
    parameters: Mapping[str, object]

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _record_content(content, cls.__name__, {"term_id", "objective_ref", "weight_units", "parameters"})
        reference = _mapping(value["objective_ref"], "objective_ref", {"id", "version", "sha256"})
        _string(reference["id"], "objective_ref.id"); _string(reference["version"], "objective_ref.version"); _hash(reference["sha256"], "objective_ref.sha256")
        return cls(_string(value["term_id"], "term_id") or "", dict(reference), _integer(value["weight_units"], "weight_units", minimum=1, maximum=1_000_000), _object(value["parameters"], "parameters"))


@dataclass(frozen=True)
class Constraint(_Contract):
    constraint_id: str
    owner: ConstraintOwner
    metric_ref: str
    operator: ConstraintOperator
    threshold: Mapping[str, object]
    policy_ref: str | None

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _record_content(content, cls.__name__, {"constraint_id", "owner", "metric_ref", "operator", "threshold", "policy_ref"})
        threshold = _mapping(value["threshold"], "threshold", {"value", "unit"})
        _string(threshold["value"], "threshold.value"); _string(threshold["unit"], "threshold.unit")
        return cls(_string(value["constraint_id"], "constraint_id") or "", ConstraintOwner(_enum(ConstraintOwner, value["owner"], "owner")), _string(value["metric_ref"], "metric_ref") or "", ConstraintOperator(_enum(ConstraintOperator, value["operator"], "operator")), dict(threshold), _string(value["policy_ref"], "policy_ref", nullable=True))


@dataclass(frozen=True)
class ObjectiveEvaluation(_Contract):
    objective_term_id: str
    status: ObjectiveEvaluationStatus
    utility_ppm: int | None
    gate_result_ids: tuple[str, ...]
    prediction_lineage_ref: str | None

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"objective_term_id", "status", "utility_ppm", "gate_result_ids", "prediction_lineage_ref"}
        value = _record_content(content, cls.__name__, names)
        status = ObjectiveEvaluationStatus(_enum(ObjectiveEvaluationStatus, value["status"], "status"))
        utility = _optional_integer(value["utility_ppm"], "utility_ppm", maximum=1_000_000)
        if status is ObjectiveEvaluationStatus.SCORED and utility is None:
            raise ContractError("scored objective evaluations require utility_ppm")
        if status is ObjectiveEvaluationStatus.ABSTAINED and utility is not None:
            raise ContractError("abstained objective evaluations cannot carry utility_ppm")
        gate_ids = _strings(value["gate_result_ids"], "gate_result_ids")
        if len(set(gate_ids)) != len(gate_ids):
            raise ContractError("gate_result_ids must be unique")
        return cls(
            _string(value["objective_term_id"], "objective_term_id") or "",
            status,
            utility,
            gate_ids,
            _string(value["prediction_lineage_ref"], "prediction_lineage_ref", nullable=True),
        )


@dataclass(frozen=True)
class QualityGateResult(_Contract):
    gate_id: str
    policy_ref: Mapping[str, object]
    subject_prediction_id: str
    metric: str
    observed_value: object
    threshold_or_predicate: Mapping[str, object]
    outcome: GateOutcome
    reason: str

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"gate_id", "policy_ref", "subject_prediction_id", "metric", "observed_value", "threshold_or_predicate", "outcome", "reason"}
        value = _record_content(content, cls.__name__, names)
        policy_ref = _mapping(value["policy_ref"], "policy_ref", {"version", "sha256"})
        _string(policy_ref["version"], "policy_ref.version"); _hash(policy_ref["sha256"], "policy_ref.sha256")
        canonical_json(value["observed_value"])
        return cls(
            _string(value["gate_id"], "gate_id") or "",
            dict(policy_ref),
            _string(value["subject_prediction_id"], "subject_prediction_id") or "",
            _string(value["metric"], "metric") or "",
            value["observed_value"],
            _object(value["threshold_or_predicate"], "threshold_or_predicate"),
            GateOutcome(_enum(GateOutcome, value["outcome"], "outcome")),
            _string(value["reason"], "reason") or "",
        )


@dataclass(frozen=True)
class CandidateRankingDecision(_Contract):
    candidate_id: str
    query_revision_id: str
    disposition: CandidateDisposition
    objective_evaluations: tuple[ObjectiveEvaluation, ...]
    abstention_reasons: tuple[AbstentionReason, ...]
    gate_result_ids: tuple[str, ...]
    required_next_evidence: tuple[str, ...]
    composite_score_ppm: int | None

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"candidate_id", "query_revision_id", "disposition", "objective_evaluations", "abstention_reasons", "gate_result_ids", "required_next_evidence", "composite_score_ppm"}
        value = _record_content(content, cls.__name__, names)
        disposition = CandidateDisposition(_enum(CandidateDisposition, value["disposition"], "disposition"))
        evaluations = tuple(ObjectiveEvaluation.from_content(_object(item, "objective evaluation")) for item in _sequence(value["objective_evaluations"], "objective_evaluations"))
        if len({item.objective_term_id for item in evaluations}) != len(evaluations):
            raise ContractError("objective evaluations must have unique objective_term_id values")
        reasons = tuple(AbstentionReason(_enum(AbstentionReason, item, "abstention_reasons")) for item in _sequence(value["abstention_reasons"], "abstention_reasons"))
        score = _optional_integer(value["composite_score_ppm"], "composite_score_ppm", maximum=1_000_000)
        if disposition is CandidateDisposition.RANKED and (score is None or any(item.status is not ObjectiveEvaluationStatus.SCORED for item in evaluations)):
            raise ContractError("ranked decisions require a score and only scored objective evaluations")
        if disposition is not CandidateDisposition.RANKED and score is not None:
            raise ContractError("excluded and abstained decisions cannot have a composite score")
        if disposition is CandidateDisposition.ABSTAINED and (not reasons or not _sequence(value["required_next_evidence"], "required_next_evidence")):
            raise ContractError("abstained decisions require machine-readable reasons and next evidence")
        return cls(
            _string(value["candidate_id"], "candidate_id") or "",
            _string(value["query_revision_id"], "query_revision_id") or "",
            disposition,
            evaluations,
            reasons,
            _strings(value["gate_result_ids"], "gate_result_ids"),
            _strings(value["required_next_evidence"], "required_next_evidence"),
            score,
        )


@dataclass(frozen=True)
class UserQueryRevision(_Contract):
    ID_FIELD: ClassVar[str] = "revision_id"
    ID_KIND: ClassVar[str] = "query_revision"
    revision_id: str
    query_id: str
    parent_revision_id: str | None
    application_type: ApplicationType
    objectives: tuple[ObjectiveTerm, ...]
    user_constraints: tuple[Constraint, ...]
    change_set: tuple[QueryChange, ...]
    actor: str
    created_at: str

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"query_id", "parent_revision_id", "application_type", "objectives", "user_constraints", "change_set", "actor", "created_at"}
        value = _record_content(content, cls.__name__, names)
        objectives = tuple(ObjectiveTerm.from_content(_object(item, "objective")) for item in _sequence(value["objectives"], "objectives"))
        if not objectives:
            raise ContractError("objectives must be nonempty")
        constraints = tuple(Constraint.from_content(_object(item, "constraint")) for item in _sequence(value["user_constraints"], "user_constraints"))
        changes = tuple(QueryChange(_enum(QueryChange, item, "change_set")) for item in _sequence(value["change_set"], "change_set"))
        record = cls("", _string(value["query_id"], "query_id") or "", _string(value["parent_revision_id"], "parent_revision_id", nullable=True), ApplicationType(_enum(ApplicationType, value["application_type"], "application_type")), objectives, constraints, changes, _string(value["actor"], "actor") or "", _timestamp(value["created_at"], "created_at") or "")
        record._assign_id(); return record


@dataclass(frozen=True)
class AssayObservation(_Contract):
    ID_FIELD: ClassVar[str] = "observation_id"
    ID_KIND: ClassVar[str] = "observation"
    observation_id: str
    evidence_tier: EvidenceTier
    origin: ObservationOrigin
    candidate_id: str | None
    target_id: str | None
    endpoint_ref: str
    assay_condition_id: str
    result: Mapping[str, object]
    raw_artifact_refs: tuple[str, ...]
    replicate_group_ref: str | None
    source_record_id: str | None
    assay_started_at: str | None
    observed_at: str
    qc_status: QCStatus

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"evidence_tier", "origin", "candidate_id", "target_id", "endpoint_ref", "assay_condition_id", "result", "raw_artifact_refs", "replicate_group_ref", "source_record_id", "assay_started_at", "observed_at", "qc_status"}
        value = _record_content(content, cls.__name__, names)
        result = _mapping(value["result"], "result", {"kind", "value", "unit"})
        _enum(ResultKind, result["kind"], "result.kind"); _string(result["unit"], "result.unit", nullable=True)
        record = cls("", EvidenceTier(_enum(EvidenceTier, value["evidence_tier"], "evidence_tier")), ObservationOrigin(_enum(ObservationOrigin, value["origin"], "origin")), _string(value["candidate_id"], "candidate_id", nullable=True), _string(value["target_id"], "target_id", nullable=True), _string(value["endpoint_ref"], "endpoint_ref") or "", _string(value["assay_condition_id"], "assay_condition_id") or "", dict(result), _strings(value["raw_artifact_refs"], "raw_artifact_refs"), _string(value["replicate_group_ref"], "replicate_group_ref", nullable=True), _string(value["source_record_id"], "source_record_id", nullable=True), _timestamp(value["assay_started_at"], "assay_started_at", nullable=True), _timestamp(value["observed_at"], "observed_at") or "", QCStatus(_enum(QCStatus, value["qc_status"], "qc_status")))
        record._assign_id(); return record


@dataclass(frozen=True)
class Prediction(_Contract):
    ID_FIELD: ClassVar[str] = "prediction_id"
    ID_KIND: ClassVar[str] = "pred"
    prediction_id: str
    prediction_series_id: str
    origin: PredictionOrigin
    estimand: Mapping[str, object]
    result: Mapping[str, object]
    issued_at: str
    locked_at: str
    invocation_lineage_hash: str
    revision: int
    recomputes_prediction_id: str | None
    predictor_signature: str
    input_hashes: tuple[str, ...]
    uncertainty: Mapping[str, object]
    objective_normalizer_hash: str
    calibration_model_hash: str | None
    epistemic_status: PredictionEpistemicStatus

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"prediction_series_id", "origin", "estimand", "result", "issued_at", "locked_at", "invocation_lineage_hash", "revision", "recomputes_prediction_id", "predictor_signature", "input_hashes", "uncertainty", "objective_normalizer_hash", "calibration_model_hash", "epistemic_status"}
        value = _record_content(content, cls.__name__, names)
        estimand = _mapping(value["estimand"], "estimand", {"candidate_id", "target_id", "endpoint_ref", "unit", "condition_scope_hash"})
        _string(estimand["candidate_id"], "estimand.candidate_id"); _string(estimand["target_id"], "estimand.target_id", nullable=True); _string(estimand["endpoint_ref"], "estimand.endpoint_ref"); _string(estimand["unit"], "estimand.unit"); _hash(estimand["condition_scope_hash"], "estimand.condition_scope_hash")
        input_hashes = _strings(value["input_hashes"], "input_hashes")
        for item in input_hashes: _hash(item, "input_hashes item")
        record = cls("", _string(value["prediction_series_id"], "prediction_series_id") or "", PredictionOrigin(_enum(PredictionOrigin, value["origin"], "origin")), dict(estimand), _object(value["result"], "result"), _timestamp(value["issued_at"], "issued_at") or "", _timestamp(value["locked_at"], "locked_at") or "", _hash(value["invocation_lineage_hash"], "invocation_lineage_hash") or "", _integer(value["revision"], "revision", maximum=4_294_967_295), _string(value["recomputes_prediction_id"], "recomputes_prediction_id", nullable=True), _hash(value["predictor_signature"], "predictor_signature") or "", input_hashes, _object(value["uncertainty"], "uncertainty"), _hash(value["objective_normalizer_hash"], "objective_normalizer_hash") or "", _hash(value["calibration_model_hash"], "calibration_model_hash", nullable=True), PredictionEpistemicStatus(_enum(PredictionEpistemicStatus, value["epistemic_status"], "epistemic_status")))
        record._assign_id(); return record


@dataclass(frozen=True)
class Measurement(_Contract):
    ID_FIELD: ClassVar[str] = "measurement_id"
    ID_KIND: ClassVar[str] = "measurement"
    measurement_id: str
    observation_id: str
    originating_prediction_id: str
    pairing_design: PairingDesign
    pair_relation: PairRelation
    benchmark_split_role: BenchmarkSplitRole
    pair_created_at: str
    compatibility_check_ref: str

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"observation_id", "originating_prediction_id", "pairing_design", "pair_relation", "benchmark_split_role", "pair_created_at", "compatibility_check_ref"}
        value = _record_content(content, cls.__name__, names)
        record = cls("", _string(value["observation_id"], "observation_id") or "", _string(value["originating_prediction_id"], "originating_prediction_id") or "", PairingDesign(_enum(PairingDesign, value["pairing_design"], "pairing_design")), PairRelation(_enum(PairRelation, value["pair_relation"], "pair_relation")), BenchmarkSplitRole(_enum(BenchmarkSplitRole, value["benchmark_split_role"], "benchmark_split_role")), _timestamp(value["pair_created_at"], "pair_created_at") or "", _string(value["compatibility_check_ref"], "compatibility_check_ref") or "")
        record._assign_id(); return record


@dataclass(frozen=True)
class SourceRecord(_Contract):
    ID_FIELD: ClassVar[str] = "source_id"
    ID_KIND: ClassVar[str] = "source"
    source_id: str
    source_kind: SourceKind
    namespace: str
    accession: str
    source_release: str
    version_status: VersionStatus
    schema_version: str
    api_version: str
    canonical_uri: str
    retrieved_at: str
    artifact: Mapping[str, object]
    license: Mapping[str, object]
    citation: Mapping[str, object]
    provenance: Mapping[str, object]

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"source_kind", "namespace", "accession", "source_release", "version_status", "schema_version", "api_version", "canonical_uri", "retrieved_at", "artifact", "license", "citation", "provenance"}
        value = _record_content(content, cls.__name__, names)
        artifact = _mapping(value["artifact"], "artifact", {"sha256", "media_type", "byte_size"}); _hash(artifact["sha256"], "artifact.sha256"); _string(artifact["media_type"], "artifact.media_type"); _integer(artifact["byte_size"], "artifact.byte_size")
        license_data = _mapping(value["license"], "license", {"expression", "terms_uri", "terms_snapshot_sha256", "decision", "restrictions", "decided_by", "decided_at"})
        _string(license_data["expression"], "license.expression"); _string(license_data["terms_uri"], "license.terms_uri", nullable=True); _hash(license_data["terms_snapshot_sha256"], "license.terms_snapshot_sha256", nullable=True); _enum(LicenseDecision, license_data["decision"], "license.decision"); _strings(license_data["restrictions"], "license.restrictions"); _string(license_data["decided_by"], "license.decided_by", nullable=True); _timestamp(license_data["decided_at"], "license.decided_at", nullable=True)
        provenance = _mapping(value["provenance"], "provenance", {"parent_source_ids", "adapter_invocation_id"}); _strings(provenance["parent_source_ids"], "provenance.parent_source_ids"); _string(provenance["adapter_invocation_id"], "provenance.adapter_invocation_id", nullable=True)
        record = cls("", SourceKind(_enum(SourceKind, value["source_kind"], "source_kind")), *(_string(value[name], name) or "" for name in ("namespace", "accession", "source_release")), VersionStatus(_enum(VersionStatus, value["version_status"], "version_status")), *(_string(value[name], name) or "" for name in ("schema_version", "api_version", "canonical_uri")), _timestamp(value["retrieved_at"], "retrieved_at") or "", dict(artifact), dict(license_data), _object(value["citation"], "citation"), dict(provenance))
        record._assign_id(); return record


@dataclass(frozen=True)
class AssayCondition(_Contract):
    ID_FIELD: ClassVar[str] = "condition_id"
    ID_KIND: ClassVar[str] = "condition"
    condition_id: str
    protocol_source_id: str | None
    assay_type_ref: str
    matrix: Mapping[str, object]
    test_system: Mapping[str, object]
    environment: Mapping[str, object]
    modifiers: tuple[Mapping[str, object], ...]
    controls: Mapping[str, object]
    replication: Mapping[str, object]
    instrument_or_method_ref: str | None

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"protocol_source_id", "assay_type_ref", "matrix", "test_system", "environment", "modifiers", "controls", "replication", "instrument_or_method_ref"}
        value = _record_content(content, cls.__name__, names)
        matrix = _mapping(value["matrix"], "matrix", {"vocabulary_term", "source_or_species", "lot_or_batch", "preparation"}); _string(matrix["vocabulary_term"], "matrix.vocabulary_term"); _string(matrix["source_or_species"], "matrix.source_or_species", nullable=True); _string(matrix["lot_or_batch"], "matrix.lot_or_batch", nullable=True); _string(matrix["preparation"], "matrix.preparation")
        system = _mapping(value["test_system"], "test_system", {"organism_or_isolate_refs", "inoculum", "candidate_concentration"}); _strings(system["organism_or_isolate_refs"], "test_system.organism_or_isolate_refs"); _string(system["inoculum"], "test_system.inoculum", nullable=True); _string(system["candidate_concentration"], "test_system.candidate_concentration", nullable=True)
        environment = _mapping(value["environment"], "environment", {"temperature", "duration", "pH", "sampling_schedule"}); _string(environment["temperature"], "environment.temperature", nullable=True); _string(environment["duration"], "environment.duration"); _string(environment["pH"], "environment.pH", nullable=True)
        if environment["sampling_schedule"] is not None: canonical_json(environment["sampling_schedule"])
        modifiers = []
        for item in _sequence(value["modifiers"], "modifiers"):
            modifier = _mapping(item, "modifier", {"role", "substance_ref_or_name", "concentration"}); _enum(ModifierRole, modifier["role"], "modifier.role"); _string(modifier["substance_ref_or_name"], "modifier.substance_ref_or_name"); _string(modifier["concentration"], "modifier.concentration", nullable=True); modifiers.append(dict(modifier))
        controls = _mapping(value["controls"], "controls", {"reporting_status", "definitions"}); _enum(ReportingStatus, controls["reporting_status"], "controls.reporting_status")
        for item in _sequence(controls["definitions"], "controls.definitions"):
            definition = _mapping(item, "control definition", {"type", "material_ref_or_description", "expected_outcome"}); _enum(ControlType, definition["type"], "control.type"); _string(definition["material_ref_or_description"], "control.material"); _string(definition["expected_outcome"], "control.expected_outcome")
        replication = _mapping(value["replication"], "replication", {"reporting_status", "biological_n", "technical_n", "unit_of_replication", "randomization", "blinding"}); _enum(ReportingStatus, replication["reporting_status"], "replication.reporting_status")
        for name in ("biological_n", "technical_n"):
            if replication[name] is not None: _integer(replication[name], f"replication.{name}")
        for name in ("unit_of_replication", "randomization", "blinding"): _string(replication[name], f"replication.{name}", nullable=True)
        record = cls("", _string(value["protocol_source_id"], "protocol_source_id", nullable=True), _string(value["assay_type_ref"], "assay_type_ref") or "", dict(matrix), dict(system), dict(environment), tuple(modifiers), dict(controls), dict(replication), _string(value["instrument_or_method_ref"], "instrument_or_method_ref", nullable=True))
        record._assign_id(); return record


@dataclass(frozen=True)
class SourceSpan(_Contract):
    source_id: str
    artifact_sha256: str
    selector: Mapping[str, object]
    quoted_text_sha256: str
    quoted_text: str | None

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _record_content(content, cls.__name__, {"source_id", "artifact_sha256", "selector", "quoted_text_sha256", "quoted_text"})
        selector = _mapping(value["selector"], "selector", {"type", "value"}); _enum(SelectorType, selector["type"], "selector.type"); canonical_json(selector["value"])
        return cls(_string(value["source_id"], "source_id") or "", _hash(value["artifact_sha256"], "artifact_sha256") or "", dict(selector), _hash(value["quoted_text_sha256"], "quoted_text_sha256") or "", _string(value["quoted_text"], "quoted_text", nullable=True))


@dataclass(frozen=True)
class ClaimEvidenceLink(_Contract):
    source_span: SourceSpan
    entailment: EntailmentDecision
    applicability: Applicability
    verifier: Mapping[str, object]

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _record_content(content, cls.__name__, {"source_span", "entailment", "applicability", "verifier"})
        verifier = _mapping(value["verifier"], "verifier", {"method", "version", "verified_by", "verified_at"}); _enum(VerifierMethod, verifier["method"], "verifier.method"); _string(verifier["version"], "verifier.version"); _string(verifier["verified_by"], "verifier.verified_by"); _timestamp(verifier["verified_at"], "verifier.verified_at")
        return cls(SourceSpan.from_content(_object(value["source_span"], "source_span")), EntailmentDecision(_enum(EntailmentDecision, value["entailment"], "entailment")), Applicability(_enum(Applicability, value["applicability"], "applicability")), dict(verifier))


def derive_claim_status(source_links: tuple[ClaimEvidenceLink, ...] | list[ClaimEvidenceLink]) -> ClaimStatus:
    """Derive the non-voting status represented by canonical source links."""
    links = tuple(source_links)
    if any(not isinstance(link, ClaimEvidenceLink) for link in links):
        raise ContractError("source_links must contain ClaimEvidenceLink records")
    if any(link.entailment is EntailmentDecision.NOT_ENOUGH_INFORMATION for link in links):
        return ClaimStatus.UNKNOWN
    applicable = {
        link.entailment
        for link in links
        if link.applicability in {Applicability.DIRECT, Applicability.PARTIAL}
    }
    entails = EntailmentDecision.ENTAILED in applicable
    contradicts = EntailmentDecision.CONTRADICTED in applicable
    if entails and contradicts:
        return ClaimStatus.MIXED
    if entails:
        return ClaimStatus.SUPPORTED
    if contradicts:
        return ClaimStatus.CONTRADICTED
    return ClaimStatus.UNKNOWN


@dataclass(frozen=True)
class Claim(_Contract):
    ID_FIELD: ClassVar[str] = "claim_id"
    ID_KIND: ClassVar[str] = "claim"
    claim_id: str
    proposition: Mapping[str, object]
    origin: ClaimOrigin
    source_links: tuple[ClaimEvidenceLink, ...]
    supporting_record_refs: tuple[str, ...]
    status: ClaimStatus
    approval: Mapping[str, object]
    supersedes_claim_id: str | None

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"proposition", "origin", "source_links", "supporting_record_refs", "status", "approval", "supersedes_claim_id"}
        value = _record_content(content, cls.__name__, names)
        proposition = _mapping(value["proposition"], "proposition", {"display_text", "subject_refs", "predicate_ref", "object", "qualifiers"}); _string(proposition["display_text"], "proposition.display_text"); _strings(proposition["subject_refs"], "proposition.subject_refs"); _string(proposition["predicate_ref"], "proposition.predicate_ref"); canonical_json(proposition["object"]); canonical_json(proposition["qualifiers"])
        links = tuple(ClaimEvidenceLink.from_content(_object(item, "source link")) for item in _sequence(value["source_links"], "source_links"))
        origin = ClaimOrigin(_enum(ClaimOrigin, value["origin"], "origin")); status = ClaimStatus(_enum(ClaimStatus, value["status"], "status"))
        approval = _mapping(value["approval"], "approval", {"status", "actor", "decided_at"}); approval_status = ApprovalStatus(_enum(ApprovalStatus, approval["status"], "approval.status")); _string(approval["actor"], "approval.actor", nullable=True); _timestamp(approval["decided_at"], "approval.decided_at", nullable=True)
        if approval_status is ApprovalStatus.PENDING and (approval["actor"] is not None or approval["decided_at"] is not None): raise ContractError("pending approval cannot have a decision")
        if approval_status is not ApprovalStatus.PENDING and (approval["actor"] is None or approval["decided_at"] is None): raise ContractError("decided approval requires actor and timestamp")
        if origin is ClaimOrigin.LITERATURE_EXTRACTION or links:
            derived_status = derive_claim_status(links)
            if status is not derived_status:
                raise ContractError(f"claim status must match derived source-link status {derived_status.value}")
        record = cls("", dict(proposition), origin, links, _strings(value["supporting_record_refs"], "supporting_record_refs"), status, dict(approval), _string(value["supersedes_claim_id"], "supersedes_claim_id", nullable=True))
        record._assign_id(); return record


__all__ = [
    "ALL_ENUM_TYPES", "ApplicationType", "ConstraintOwner", "ConstraintOutcome",
    "ConstraintOperator", "QueryChange", "EvidenceTier", "ObservationOrigin",
    "PredictionOrigin", "PairingDesign", "PairRelation", "ResultKind", "QCStatus",
    "PredictionEpistemicStatus", "GateOutcome", "CandidateDisposition", "AbstentionReason",
    "ObjectiveEvaluationStatus", "BenchmarkSplitRole", "SourceKind", "LicenseDecision",
    "VersionStatus", "ControlType", "ReportingStatus", "ModifierRole", "ClaimOrigin",
    "EntailmentDecision", "Applicability", "ClaimStatus", "ApprovalStatus", "SelectorType",
    "VerifierMethod", "ObjectiveTerm", "Constraint", "ObjectiveEvaluation",
    "QualityGateResult", "CandidateRankingDecision", "UserQueryRevision",
    "AssayObservation", "Prediction", "Measurement", "SourceRecord", "AssayCondition",
    "SourceSpan", "ClaimEvidenceLink", "derive_claim_status", "Claim",
]
