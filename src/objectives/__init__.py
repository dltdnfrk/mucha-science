"""Deterministic objective normalization, policy resolution, and D1 ranking.

This package is the authoritative scalar ranking path. Hard constraints are
resolved before utilities, and every candidate is returned in exactly one of
``ranked``, ``excluded``, or ``abstained``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from src.pipeline.scientific_contracts import ContractError, canonical_json, digest
from src.platform_contracts import (
    AbstentionReason,
    ApplicationType,
    CandidateDisposition,
    CandidateRankingDecision,
    Constraint,
    ConstraintOperator,
    ConstraintOutcome,
    ConstraintOwner,
    GateOutcome,
    ObjectiveEvaluation,
    ObjectiveEvaluationStatus,
    ObjectiveTerm,
    Prediction,
    PredictionEpistemicStatus,
    QualityGateResult,
    QueryChange,
    UserQueryRevision,
)

UTILITY_MAX_PPM = 1_000_000
WEIGHT_TOTAL_UNITS = 1_000_000


class ObjectiveValidationError(ContractError):
    """Raised when an objective, revision edit, or policy invariant is broken."""


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ObjectiveValidationError(f"{name} must be an integer or decimal string")
    try:
        result = Decimal(value)  # type: ignore[arg-type]
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ObjectiveValidationError(f"{name} must be an integer or decimal string") from exc
    if not result.is_finite():
        raise ObjectiveValidationError(f"{name} must be finite")
    return result


def _round_ratio_half_even(numerator: int, denominator: int) -> int:
    """Round a nonnegative exact rational using IEEE round-half-to-even."""
    if denominator <= 0 or numerator < 0:
        raise ObjectiveValidationError("score ratio must be nonnegative with a positive denominator")
    quotient, remainder = divmod(numerator, denominator)
    doubled = remainder * 2
    if doubled > denominator or (doubled == denominator and quotient % 2):
        quotient += 1
    return quotient


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ObjectiveDefinition:
    """A pinned linear normalizer whose output always means higher utility."""

    objective_id: str
    display_name: str
    version: str
    raw_direction: str
    raw_min: Decimal = Decimal("0")
    raw_max: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.raw_direction not in {"HIGHER_IS_BETTER", "LOWER_IS_BETTER"}:
            raise ObjectiveValidationError("unknown raw objective direction")
        if self.raw_min >= self.raw_max:
            raise ObjectiveValidationError("normalizer bounds must increase")

    @property
    def utility_direction(self) -> str:
        return "HIGHER_IS_BETTER"

    @property
    def objective_ref(self) -> Mapping[str, object]:
        normalizer_contract = {
            "id": self.objective_id,
            "version": self.version,
            "normalizer": {
                "algorithm": "clamped_linear_ppm_round_half_even",
                "raw_min": str(self.raw_min),
                "raw_max": str(self.raw_max),
                "raw_direction": self.raw_direction,
                "utility_direction": self.utility_direction,
                "utility_min_ppm": 0,
                "utility_max_ppm": UTILITY_MAX_PPM,
            },
        }
        return MappingProxyType(
            {
                "id": self.objective_id,
                "version": self.version,
                "sha256": digest(normalizer_contract),
            }
        )

    def normalize(self, raw_value: object) -> int:
        raw = _decimal(raw_value, "raw objective value")
        clamped = min(self.raw_max, max(self.raw_min, raw))
        numerator = (clamped - self.raw_min) * UTILITY_MAX_PPM
        denominator = self.raw_max - self.raw_min
        if self.raw_direction == "LOWER_IS_BETTER":
            numerator = denominator * UTILITY_MAX_PPM - numerator
        # Keep the complete Decimal ratio exact instead of using context precision.
        numerator_value, numerator_scale = numerator.as_integer_ratio()
        denominator_value, denominator_scale = denominator.as_integer_ratio()
        return _round_ratio_half_even(
            numerator_value * denominator_scale,
            numerator_scale * denominator_value,
        )


def _definition(objective_id: str, display_name: str) -> ObjectiveDefinition:
    return ObjectiveDefinition(objective_id, display_name, "1.0.0", "HIGHER_IS_BETTER")


OBJECTIVE_REGISTRY: Mapping[str, ObjectiveDefinition] = MappingProxyType(
    {
        definition.objective_id: definition
        for definition in (
            _definition("target_binding_activity", "Target binding/activity"),
            _definition("non_target_avoidance", "Non-target avoidance"),
            _definition("detectability", "Detectability"),
            _definition("inhibition_kill", "Inhibition/kill"),
            _definition("surface_adhesion_persistence", "Surface adhesion/persistence"),
            _definition("synthesizability", "Synthesizability"),
            _definition("stability", "Stability"),
        )
    }
)


def score_weighted_utilities(utilities_ppm: Sequence[int], weights: Sequence[int]) -> int:
    """Apply the one D1 weighted-mean path, including the N=1 case."""
    if not utilities_ppm:
        raise ObjectiveValidationError("at least one utility is required")
    if len(utilities_ppm) != len(weights):
        raise ObjectiveValidationError("utilities and weights must have equal lengths")
    if any(not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= UTILITY_MAX_PPM for value in utilities_ppm):
        raise ObjectiveValidationError("utilities must be integer ppm values from 0 through 1000000")
    if any(not isinstance(weight, int) or isinstance(weight, bool) or not 1 <= weight <= WEIGHT_TOTAL_UNITS for weight in weights):
        raise ObjectiveValidationError("zero weights are forbidden; weights must be 1 through 1000000")
    numerator = sum(weight * utility for weight, utility in zip(weights, utilities_ppm, strict=True))
    return _round_ratio_half_even(numerator, sum(weights))


def normalize_relative_weights(weights: Sequence[int]) -> tuple[int, ...]:
    """Canonicalize positive relative weights to an integer total of one million."""
    if not weights:
        raise ObjectiveValidationError("at least one weight is required")
    if any(not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0 for weight in weights):
        raise ObjectiveValidationError("zero weights are forbidden")
    total = sum(weights)
    floors = [(weight * WEIGHT_TOTAL_UNITS) // total for weight in weights]
    remainder_units = WEIGHT_TOTAL_UNITS - sum(floors)
    fractional_order = sorted(
        range(len(weights)),
        key=lambda index: (-(weights[index] * WEIGHT_TOTAL_UNITS % total), index),
    )
    for index in fractional_order[:remainder_units]:
        floors[index] += 1
    if any(weight == 0 for weight in floors):
        raise ObjectiveValidationError("relative weights cannot be represented without zero weights")
    return tuple(floors)


PLATFORM_CONSTRAINT_IDS: Mapping[str, str] = MappingProxyType(
    {
        "synthesizability": "platform.synthesizability",
        "crop_phytotoxicity": "platform.crop_phytotoxicity",
        "soil_beneficial_microbe": "platform.soil_beneficial_microbe",
        "handler_exposure": "platform.handler_exposure",
    }
)

_POLICY_VERSION = "d1-policy-v1"
_ENVIRONMENTAL_APPLICATIONS = frozenset(
    {
        ApplicationType.ENVIRONMENTAL_SPRAY,
        ApplicationType.ENVIRONMENTAL_COATING,
        ApplicationType.OTHER_ENVIRONMENTAL,
    }
)


def _platform_constraint(
    name: str,
    metric_ref: str,
    operator: ConstraintOperator,
    threshold: str,
    unit: str,
) -> Constraint:
    return Constraint.from_content(
        {
            "constraint_id": PLATFORM_CONSTRAINT_IDS[name],
            "owner": ConstraintOwner.PLATFORM_POLICY.value,
            "metric_ref": metric_ref,
            "operator": operator.value,
            "threshold": {"value": threshold, "unit": unit},
            "policy_ref": _POLICY_VERSION,
        }
    )


_PLATFORM_CONSTRAINTS = (
    _platform_constraint("synthesizability", "metric.synthesizability_probability", ConstraintOperator.GTE, "0.70", "probability"),
    _platform_constraint("crop_phytotoxicity", "metric.crop_phytotoxicity_risk", ConstraintOperator.LTE, "0.10", "probability"),
    _platform_constraint("soil_beneficial_microbe", "metric.soil_beneficial_microbe_risk", ConstraintOperator.LTE, "0.10", "probability"),
    _platform_constraint("handler_exposure", "metric.handler_exposure_risk", ConstraintOperator.LTE, "0.10", "probability"),
)
_PLATFORM_BY_ID = {constraint.constraint_id: constraint for constraint in _PLATFORM_CONSTRAINTS}

POLICY_BUNDLE_REF: Mapping[str, str] = MappingProxyType(
    {
        "version": _POLICY_VERSION,
        "sha256": digest(
            {
                "version": _POLICY_VERSION,
                "constraints": [constraint.to_content() for constraint in _PLATFORM_CONSTRAINTS],
            }
        ),
    }
)


def _active_platform_constraints(application_type: ApplicationType) -> tuple[Constraint, ...]:
    return _PLATFORM_CONSTRAINTS if application_type in _ENVIRONMENTAL_APPLICATIONS else _PLATFORM_CONSTRAINTS[:1]


def _validate_objectives(objectives: Sequence[ObjectiveTerm]) -> tuple[ObjectiveTerm, ...]:
    terms = tuple(objectives)
    if not terms:
        raise ObjectiveValidationError("objectives must be nonempty")
    seen: set[bytes] = set()
    term_ids: set[str] = set()
    for term in terms:
        if not isinstance(term, ObjectiveTerm):
            raise ObjectiveValidationError("objectives must contain ObjectiveTerm records")
        if term.term_id in term_ids:
            raise ObjectiveValidationError("objective term IDs must be unique")
        term_ids.add(term.term_id)
        objective_id = term.objective_ref.get("id")
        definition = OBJECTIVE_REGISTRY.get(objective_id) if isinstance(objective_id, str) else None
        if definition is None or dict(term.objective_ref) != dict(definition.objective_ref):
            raise ObjectiveValidationError("objective_ref is not a pinned registry objective")
        duplicate_key = canonical_json({"objective_ref": term.objective_ref, "parameters": term.parameters})
        if duplicate_key in seen:
            raise ObjectiveValidationError("duplicate objective terms are forbidden")
        seen.add(duplicate_key)
    return terms


def _validate_user_constraints(constraints: Sequence[Constraint]) -> tuple[Constraint, ...]:
    result = tuple(constraints)
    ids: set[str] = set()
    platform_by_metric = {constraint.metric_ref: constraint for constraint in _PLATFORM_CONSTRAINTS}
    for constraint in result:
        if not isinstance(constraint, Constraint):
            raise ObjectiveValidationError("user_constraints must contain Constraint records")
        if constraint.owner is not ConstraintOwner.USER:
            raise ObjectiveValidationError("user constraints must be user-owned")
        if constraint.constraint_id in ids or constraint.constraint_id in _PLATFORM_BY_ID:
            raise ObjectiveValidationError("constraint IDs must be unique and cannot shadow platform constraints")
        ids.add(constraint.constraint_id)
        platform = platform_by_metric.get(constraint.metric_ref)
        if platform is None:
            continue
        same_shape = constraint.operator is platform.operator and constraint.threshold["unit"] == platform.threshold["unit"]
        user_value = _decimal(constraint.threshold["value"], "user constraint threshold")
        platform_value = _decimal(platform.threshold["value"], "platform constraint threshold")
        stricter = (
            constraint.operator is ConstraintOperator.GTE and user_value >= platform_value
        ) or (
            constraint.operator is ConstraintOperator.LTE and user_value <= platform_value
        )
        if not same_shape or not stricter:
            raise ObjectiveValidationError("user constraints overlapping platform policy must be at least as strict")
    return result


def create_query_revision(
    *,
    query_id: str,
    application_type: ApplicationType,
    objectives: Sequence[ObjectiveTerm],
    user_constraints: Sequence[Constraint],
    actor: str,
    created_at: str,
) -> UserQueryRevision:
    terms = _validate_objectives(objectives)
    constraints = _validate_user_constraints(user_constraints)
    return UserQueryRevision.from_content(
        {
            "query_id": query_id,
            "parent_revision_id": None,
            "application_type": application_type.value,
            "objectives": [term.to_content() for term in terms],
            "user_constraints": [constraint.to_content() for constraint in constraints],
            "change_set": [QueryChange.ADD_OBJECTIVE.value],
            "actor": actor,
            "created_at": created_at,
        }
    )


def _revised_query(
    revision: UserQueryRevision,
    *,
    application_type: ApplicationType,
    objectives: Sequence[ObjectiveTerm],
    change: QueryChange,
    actor: str,
    created_at: str,
) -> UserQueryRevision:
    terms = _validate_objectives(objectives)
    constraints = _validate_user_constraints(revision.user_constraints)
    return UserQueryRevision.from_content(
        {
            "query_id": revision.query_id,
            "parent_revision_id": revision.revision_id,
            "application_type": application_type.value,
            "objectives": [term.to_content() for term in terms],
            "user_constraints": [constraint.to_content() for constraint in constraints],
            "change_set": [change.value],
            "actor": actor,
            "created_at": created_at,
        }
    )


def remove_objective(
    revision: UserQueryRevision,
    term_id: str,
    *,
    actor: str,
    created_at: str,
) -> UserQueryRevision:
    remaining = tuple(term for term in revision.objectives if term.term_id != term_id)
    if len(remaining) == len(revision.objectives):
        raise ObjectiveValidationError(f"unknown objective term: {term_id}")
    if not remaining:
        raise ObjectiveValidationError("a query revision must retain at least one objective")
    normalized = normalize_relative_weights([term.weight_units for term in remaining])
    rebuilt = tuple(
        ObjectiveTerm.from_content(
            {
                **term.to_content(),
                "weight_units": weight,
            }
        )
        for term, weight in zip(remaining, normalized, strict=True)
    )
    return _revised_query(
        revision,
        application_type=revision.application_type,
        objectives=rebuilt,
        change=QueryChange.REMOVE_OBJECTIVE,
        actor=actor,
        created_at=created_at,
    )


def set_application_type(
    revision: UserQueryRevision,
    application_type: ApplicationType,
    *,
    actor: str,
    created_at: str,
) -> UserQueryRevision:
    if not isinstance(application_type, ApplicationType):
        raise ObjectiveValidationError("application_type must be an ApplicationType")
    if application_type is revision.application_type:
        raise ObjectiveValidationError("application_type edit must change the value")
    return _revised_query(
        revision,
        application_type=application_type,
        objectives=revision.objectives,
        change=QueryChange.SET_APPLICATION_TYPE,
        actor=actor,
        created_at=created_at,
    )


def resolve_constraints(
    revision: UserQueryRevision,
    *,
    removed_constraint_ids: Iterable[str] = (),
) -> tuple[Constraint, ...]:
    protected = _active_platform_constraints(revision.application_type)
    removed = tuple(removed_constraint_ids)
    protected_ids = {constraint.constraint_id for constraint in protected}
    if protected_ids.intersection(removed):
        raise ObjectiveValidationError("platform constraints cannot be removed or disabled")
    user_ids = {constraint.constraint_id for constraint in revision.user_constraints}
    unknown = set(removed).difference(user_ids)
    if unknown:
        raise ObjectiveValidationError(f"unknown constraint IDs: {sorted(unknown)}")
    removed_set = set(removed)
    return protected + tuple(
        constraint for constraint in revision.user_constraints if constraint.constraint_id not in removed_set
    )


@dataclass(frozen=True)
class CandidateInput:
    candidate_id: str
    candidate_content: Mapping[str, object]
    objective_evaluations: Mapping[str, ObjectiveEvaluation | int]
    constraint_outcomes: Mapping[str, ConstraintOutcome]
    prediction_lineage: Mapping[str, Prediction] = MappingProxyType({})
    quality_gate_results: Mapping[str, QualityGateResult] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id:
            raise ObjectiveValidationError("candidate_id must be a nonempty string")
        canonical_json(self.candidate_content)
        evaluations: dict[str, ObjectiveEvaluation] = {}
        for term_id, evaluation in self.objective_evaluations.items():
            if isinstance(evaluation, int) and not isinstance(evaluation, bool):
                evaluation = ObjectiveEvaluation.from_content(
                    {
                        "objective_term_id": term_id,
                        "status": ObjectiveEvaluationStatus.SCORED.value,
                        "utility_ppm": evaluation,
                        "gate_result_ids": [],
                        "prediction_lineage_ref": None,
                    }
                )
            if not isinstance(term_id, str) or not isinstance(evaluation, ObjectiveEvaluation):
                raise ObjectiveValidationError("objective_evaluations must map term IDs to ObjectiveEvaluation records or legacy integer utilities")
            if term_id != evaluation.objective_term_id:
                raise ObjectiveValidationError("objective evaluation keys must match objective_term_id")
            evaluations[term_id] = evaluation
        predictions: dict[str, Prediction] = {}
        for prediction_id, prediction in self.prediction_lineage.items():
            if not isinstance(prediction, Prediction) or prediction_id != prediction.prediction_id:
                raise ObjectiveValidationError("prediction_lineage keys must match canonical Prediction IDs")
            predictions[prediction_id] = prediction
        gates: dict[str, QualityGateResult] = {}
        for gate_id, gate in self.quality_gate_results.items():
            if not isinstance(gate, QualityGateResult) or gate_id != gate.gate_id:
                raise ObjectiveValidationError("quality_gate_results keys must match gate IDs")
            gates[gate_id] = gate
        outcomes: dict[str, ConstraintOutcome] = {}
        for constraint_id, outcome in self.constraint_outcomes.items():
            try:
                outcomes[constraint_id] = ConstraintOutcome(outcome)
            except (ValueError, TypeError) as exc:
                raise ObjectiveValidationError(f"invalid constraint outcome for {constraint_id}") from exc
        object.__setattr__(self, "candidate_content", _freeze(self.candidate_content))
        object.__setattr__(self, "objective_evaluations", MappingProxyType(evaluations))
        object.__setattr__(self, "constraint_outcomes", MappingProxyType(outcomes))
        object.__setattr__(self, "prediction_lineage", MappingProxyType(predictions))
        object.__setattr__(self, "quality_gate_results", MappingProxyType(gates))


@dataclass(frozen=True)
class CandidateDecision:
    candidate_id: str
    query_revision_id: str
    candidate_content_hash: str
    disposition: CandidateDisposition
    rank: int | None
    composite_score_ppm: int | None
    objective_evaluations: tuple[ObjectiveEvaluation, ...]
    per_objective_utility_ppm: Mapping[str, int]
    abstention_reasons: tuple[AbstentionReason, ...]
    gate_result_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    required_next_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "per_objective_utility_ppm", MappingProxyType(dict(self.per_objective_utility_ppm)))
        CandidateRankingDecision.from_content(
            {
                "candidate_id": self.candidate_id,
                "query_revision_id": self.query_revision_id,
                "disposition": self.disposition.value,
                "objective_evaluations": [item.to_content() for item in self.objective_evaluations],
                "abstention_reasons": [item.value for item in self.abstention_reasons],
                "gate_result_ids": list(self.gate_result_ids),
                "required_next_evidence": list(self.required_next_evidence),
                "composite_score_ppm": self.composite_score_ppm,
            }
        )

    @property
    def canonical_ranking_decision(self) -> CandidateRankingDecision:
        return CandidateRankingDecision.from_content(
            {
                "candidate_id": self.candidate_id,
                "query_revision_id": self.query_revision_id,
                "disposition": self.disposition.value,
                "objective_evaluations": [item.to_content() for item in self.objective_evaluations],
                "abstention_reasons": [item.value for item in self.abstention_reasons],
                "gate_result_ids": list(self.gate_result_ids),
                "required_next_evidence": list(self.required_next_evidence),
                "composite_score_ppm": self.composite_score_ppm,
            }
        )


@dataclass(frozen=True)
class CombinationResult:
    ranked: tuple[CandidateDecision, ...]
    excluded: tuple[CandidateDecision, ...]
    abstained: tuple[CandidateDecision, ...]
    resolved_constraints: tuple[Constraint, ...]
    policy_bundle_ref: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_bundle_ref", MappingProxyType(dict(self.policy_bundle_ref)))

    @property
    def debug_blocked_as_ranked(self) -> bool:
        """A blocked candidate is structurally unable to appear in ``ranked``."""
        ranked_ids = {decision.candidate_id for decision in self.ranked}
        return any(
            decision.candidate_id in ranked_ids
            for decision in self.excluded + self.abstained
        )


def _decision(
    candidate: CandidateInput,
    query_revision_id: str,
    disposition: CandidateDisposition,
    *,
    evaluations: tuple[ObjectiveEvaluation, ...] = (),
    utilities: Mapping[str, int] | None = None,
    score: int | None = None,
    abstention_reasons: tuple[AbstentionReason, ...] = (),
    gate_result_ids: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    required: tuple[str, ...] = (),
    rank: int | None = None,
) -> CandidateDecision:
    return CandidateDecision(
        candidate.candidate_id,
        query_revision_id,
        digest(candidate.candidate_content),
        disposition,
        rank,
        score,
        evaluations,
        utilities or {},
        abstention_reasons,
        gate_result_ids,
        reasons,
        required,
    )


def _unique(items: Iterable[object]) -> tuple[object, ...]:
    return tuple(dict.fromkeys(items))


def _effective_evaluation(
    candidate: CandidateInput,
    evaluation: ObjectiveEvaluation,
) -> tuple[ObjectiveEvaluation, tuple[AbstentionReason, ...], tuple[str, ...]]:
    status = evaluation.status
    reasons: list[AbstentionReason] = []
    required: list[str] = []
    gate_results = tuple(candidate.quality_gate_results.get(gate_id) for gate_id in evaluation.gate_result_ids)

    if any(gate is None for gate in gate_results):
        status = ObjectiveEvaluationStatus.ABSTAINED
        reasons.append(AbstentionReason.REQUIRED_PROVENANCE_MISSING)
        required.extend(f"quality_gate_result:{gate_id}" for gate_id, gate in zip(evaluation.gate_result_ids, gate_results, strict=True) if gate is None)

    prediction = None
    if evaluation.gate_result_ids and evaluation.prediction_lineage_ref is None:
        status = ObjectiveEvaluationStatus.ABSTAINED
        reasons.append(AbstentionReason.REQUIRED_PROVENANCE_MISSING)
        required.append(f"prediction_lineage:{evaluation.objective_term_id}")
    if evaluation.prediction_lineage_ref is not None:
        prediction = candidate.prediction_lineage.get(evaluation.prediction_lineage_ref)
        if prediction is None:
            status = ObjectiveEvaluationStatus.ABSTAINED
            reasons.append(AbstentionReason.MISSING_REQUIRED_PREDICTION)
            required.append(f"prediction:{evaluation.prediction_lineage_ref}")
        elif prediction.estimand["candidate_id"] != candidate.candidate_id:
            raise ObjectiveValidationError("prediction lineage candidate does not match CandidateInput")
        elif any(gate is not None and gate.subject_prediction_id != prediction.prediction_id for gate in gate_results):
            raise ObjectiveValidationError("quality gate subject does not match objective prediction lineage")
        elif prediction.epistemic_status is PredictionEpistemicStatus.HYPOTHESIS_ONLY:
            status = ObjectiveEvaluationStatus.HYPOTHESIS_ONLY
            required.append(f"rankable_prediction:{prediction.prediction_id}")

    if any(gate is not None and gate.outcome in {GateOutcome.FAIL, GateOutcome.UNKNOWN} for gate in gate_results):
        status = ObjectiveEvaluationStatus.HYPOTHESIS_ONLY

    if status is not ObjectiveEvaluationStatus.SCORED:
        for gate in gate_results:
            if gate is not None:
                try:
                    reasons.append(AbstentionReason(gate.reason))
                except ValueError:
                    reasons.append(AbstentionReason.REQUIRED_PROVENANCE_MISSING)
        if not reasons:
            reasons.append(AbstentionReason.REQUIRED_PROVENANCE_MISSING)
        if not required:
            required.append(f"objective_evidence:{evaluation.objective_term_id}")
    elif evaluation.utility_ppm is None:
        status = ObjectiveEvaluationStatus.ABSTAINED
        reasons.append(AbstentionReason.MISSING_REQUIRED_PREDICTION)
        required.append(f"objective_utility:{evaluation.objective_term_id}")

    effective = ObjectiveEvaluation.from_content(
        {
            **evaluation.to_content(),
            "status": status.value,
            "utility_ppm": None if status is ObjectiveEvaluationStatus.ABSTAINED else evaluation.utility_ppm,
        }
    )
    return effective, tuple(_unique(reasons)), tuple(_unique(required))


def combine_candidates(
    revision: UserQueryRevision,
    candidates: Sequence[CandidateInput],
) -> CombinationResult:
    """Resolve hard constraints and return disjoint ranked/excluded/abstained lists."""
    terms = _validate_objectives(revision.objectives)
    constraints = resolve_constraints(revision)
    ranked_pending: list[tuple[CandidateInput, CandidateDecision]] = []
    excluded: list[CandidateDecision] = []
    abstained: list[CandidateDecision] = []
    candidate_ids: set[str] = set()

    for candidate in candidates:
        if not isinstance(candidate, CandidateInput):
            raise ObjectiveValidationError("candidates must contain CandidateInput records")
        if candidate.candidate_id in candidate_ids:
            raise ObjectiveValidationError("candidate IDs must be unique")
        candidate_ids.add(candidate.candidate_id)

        failed = tuple(
            constraint.constraint_id
            for constraint in constraints
            if candidate.constraint_outcomes.get(constraint.constraint_id, ConstraintOutcome.UNKNOWN) is ConstraintOutcome.FAIL
        )
        unknown = tuple(
            constraint.constraint_id
            for constraint in constraints
            if candidate.constraint_outcomes.get(constraint.constraint_id, ConstraintOutcome.UNKNOWN) is ConstraintOutcome.UNKNOWN
        )
        if failed:
            excluded.append(
                _decision(
                    candidate,
                    revision.revision_id,
                    CandidateDisposition.EXCLUDED,
                    reasons=tuple(f"HARD_CONSTRAINT_FAILED:{constraint_id}" for constraint_id in failed),
                )
            )
            continue
        if unknown:
            abstained.append(
                _decision(
                    candidate,
                    revision.revision_id,
                    CandidateDisposition.ABSTAINED,
                    abstention_reasons=(AbstentionReason.MANDATORY_CONSTRAINT_UNRESOLVED,),
                    reasons=tuple(f"MANDATORY_CONSTRAINT_UNRESOLVED:{constraint_id}" for constraint_id in unknown),
                    required=tuple(f"constraint_result:{constraint_id}" for constraint_id in unknown),
                )
            )
            continue

        active_term_ids = {term.term_id for term in terms}
        extra = set(candidate.objective_evaluations).difference(active_term_ids)
        if extra:
            raise ObjectiveValidationError(f"objective evaluations contain inactive terms: {sorted(extra)}")
        missing = tuple(term.term_id for term in terms if term.term_id not in candidate.objective_evaluations)
        if missing:
            present = tuple(
                candidate.objective_evaluations[term.term_id]
                for term in terms
                if term.term_id in candidate.objective_evaluations
            )
            abstained.append(
                _decision(
                    candidate,
                    revision.revision_id,
                    CandidateDisposition.ABSTAINED,
                    evaluations=present,
                    utilities={item.objective_term_id: item.utility_ppm for item in present if item.utility_ppm is not None},
                    abstention_reasons=(AbstentionReason.MISSING_REQUIRED_PREDICTION,),
                    reasons=tuple(f"MISSING_ACTIVE_OBJECTIVE_VALUE:{term_id}" for term_id in missing),
                    required=tuple(f"objective_utility:{term_id}" for term_id in missing),
                )
            )
            continue

        effective: list[ObjectiveEvaluation] = []
        epistemic_reasons: list[AbstentionReason] = []
        required_evidence: list[str] = []
        for term in terms:
            item, item_reasons, item_required = _effective_evaluation(
                candidate,
                candidate.objective_evaluations[term.term_id],
            )
            effective.append(item)
            epistemic_reasons.extend(item_reasons)
            required_evidence.extend(item_required)

        unresolved = tuple(item for item in effective if item.status is not ObjectiveEvaluationStatus.SCORED)
        utilities = {
            item.objective_term_id: item.utility_ppm
            for item in effective
            if item.utility_ppm is not None
        }
        if unresolved:
            gate_ids = tuple(_unique(gate_id for item in unresolved for gate_id in item.gate_result_ids))
            abstained.append(
                _decision(
                    candidate,
                    revision.revision_id,
                    CandidateDisposition.ABSTAINED,
                    evaluations=tuple(effective),
                    utilities=utilities,
                    abstention_reasons=tuple(_unique(epistemic_reasons)),
                    gate_result_ids=gate_ids,
                    reasons=tuple(f"ACTIVE_OBJECTIVE_{item.status.value}:{item.objective_term_id}" for item in unresolved),
                    required=tuple(_unique(required_evidence)),
                )
            )
            continue

        score = score_weighted_utilities(
            [utilities[term.term_id] for term in terms],
            [term.weight_units for term in terms],
        )
        ranked_pending.append(
            (candidate, _decision(candidate, revision.revision_id, CandidateDisposition.RANKED, evaluations=tuple(effective), utilities=utilities, score=score))
        )

    ranked_pending.sort(
        key=lambda item: (
            -(item[1].composite_score_ppm or 0),
            item[1].candidate_content_hash,
            item[0].candidate_id,
        )
    )
    ranked: list[CandidateDecision] = []
    prior_score: int | None = None
    dense_rank = 0
    for _, decision in ranked_pending:
        if decision.composite_score_ppm != prior_score:
            dense_rank += 1
            prior_score = decision.composite_score_ppm
        ranked.append(
            CandidateDecision(
                decision.candidate_id,
                decision.query_revision_id,
                decision.candidate_content_hash,
                decision.disposition,
                dense_rank,
                decision.composite_score_ppm,
                decision.objective_evaluations,
                decision.per_objective_utility_ppm,
                decision.abstention_reasons,
                decision.gate_result_ids,
                decision.reasons,
                decision.required_next_evidence,
            )
        )

    return CombinationResult(
        tuple(ranked),
        tuple(excluded),
        tuple(abstained),
        constraints,
        POLICY_BUNDLE_REF,
    )


__all__ = [
    "CandidateDecision",
    "CandidateDisposition",
    "CandidateInput",
    "CombinationResult",
    "OBJECTIVE_REGISTRY",
    "ObjectiveDefinition",
    "ObjectiveValidationError",
    "PLATFORM_CONSTRAINT_IDS",
    "POLICY_BUNDLE_REF",
    "combine_candidates",
    "create_query_revision",
    "normalize_relative_weights",
    "remove_objective",
    "resolve_constraints",
    "score_weighted_utilities",
    "set_application_type",
]
