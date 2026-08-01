from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.objectives import (
    OBJECTIVE_REGISTRY,
    CandidateInput,
    CandidateDisposition,
    ObjectiveValidationError,
    PLATFORM_CONSTRAINT_IDS,
    combine_candidates,
    create_query_revision,
    normalize_relative_weights,
    remove_objective,
    resolve_constraints,
    score_weighted_utilities,
    set_application_type,
)
from src.platform_contracts import (
    AbstentionReason,
    ApplicationType,
    Constraint,
    ConstraintOutcome,
    ObjectiveEvaluation,
    ObjectiveEvaluationStatus,
    ObjectiveTerm,
    Prediction,
)

TS = "2026-08-01T00:00:00.000000Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def term(objective_id: str, weight: int, *, term_id: str | None = None, parameters: dict[str, object] | None = None) -> ObjectiveTerm:
    definition = OBJECTIVE_REGISTRY[objective_id]
    return ObjectiveTerm.from_content(
        {
            "term_id": term_id or objective_id,
            "objective_ref": definition.objective_ref,
            "weight_units": weight,
            "parameters": parameters or {},
        }
    )


def evaluation(term_id: str, utility_ppm: int) -> ObjectiveEvaluation:
    return ObjectiveEvaluation.from_content(
        {
            "objective_term_id": term_id,
            "status": "SCORED",
            "utility_ppm": utility_ppm,
            "gate_result_ids": [],
            "prediction_lineage_ref": None,
        }
    )


def prediction(epistemic_status: str = "RANKABLE_PREDICTION") -> Prediction:
    return Prediction.from_content(
        {
            "prediction_series_id": f"series-{epistemic_status.lower()}",
            "origin": "PLATFORM_COMPUTATION",
            "estimand": {"candidate_id": "candidate-1", "target_id": "target-1", "endpoint_ref": "endpoint.binding", "unit": "ppm", "condition_scope_hash": HASH_A},
            "result": {"utility_ppm": 1_000_000},
            "issued_at": TS,
            "locked_at": TS,
            "invocation_lineage_hash": HASH_A,
            "revision": 1,
            "recomputes_prediction_id": None,
            "predictor_signature": HASH_A,
            "input_hashes": [HASH_A],
            "uncertainty": {},
            "objective_normalizer_hash": HASH_B,
            "calibration_model_hash": None,
            "epistemic_status": epistemic_status,
        }
    )


def query(*objectives: ObjectiveTerm, application_type: ApplicationType = ApplicationType.CONTAINED_LAB):
    return create_query_revision(
        query_id="query-1",
        application_type=application_type,
        objectives=objectives,
        user_constraints=(),
        actor="scientist-1",
        created_at=TS,
    )


def test_registry_has_seven_versioned_higher_is_better_normalizers() -> None:
    assert set(OBJECTIVE_REGISTRY) == {
        "target_binding_activity",
        "non_target_avoidance",
        "detectability",
        "inhibition_kill",
        "surface_adhesion_persistence",
        "synthesizability",
        "stability",
    }
    for objective_id, definition in OBJECTIVE_REGISTRY.items():
        assert definition.objective_ref["id"] == objective_id
        assert definition.objective_ref["version"]
        assert definition.objective_ref["sha256"].startswith("sha256:")
        assert 0 <= definition.normalize("0.5") <= 1_000_000
        assert definition.utility_direction == "HIGHER_IS_BETTER"


def test_weighted_fixture_scores_650000() -> None:
    assert score_weighted_utilities([800_000, 200_000], [3, 1]) == 650_000


def test_single_objective_flows_through_same_scoring_function() -> None:
    assert score_weighted_utilities([800_000], [7]) == 800_000


def test_half_even_and_weight_scale_invariance() -> None:
    assert score_weighted_utilities([0, 1], [1, 1]) == 0
    assert score_weighted_utilities([800_000, 200_000], [3, 1]) == score_weighted_utilities(
        [800_000, 200_000], [6, 2]
    )


def test_missing_second_utility_abstains_without_a_composite_score() -> None:
    revision = query(term("target_binding_activity", 3), term("stability", 1))
    outcomes = {
        constraint.constraint_id: ConstraintOutcome.PASS
        for constraint in resolve_constraints(revision)
    }
    result = combine_candidates(
        revision,
        [CandidateInput("candidate-1", {"smiles": "C"}, {"target_binding_activity": evaluation("target_binding_activity", 800_000)}, outcomes)],
    )

    assert result.ranked == ()
    assert result.excluded == ()
    assert result.abstained[0].disposition is CandidateDisposition.ABSTAINED
    assert result.abstained[0].composite_score_ppm is None
    assert result.abstained[0].reasons == ("MISSING_ACTIVE_OBJECTIVE_VALUE:stability",)
    assert result.abstained[0].required_next_evidence == ("objective_utility:stability",)


def test_hypothesis_only_prediction_lineage_abstains_even_with_maximum_utility() -> None:
    revision = query(term("target_binding_activity", 1))
    constraint_id = resolve_constraints(revision)[0].constraint_id
    weak_prediction = prediction("HYPOTHESIS_ONLY")
    evaluation = ObjectiveEvaluation.from_content(
        {
            "objective_term_id": "target_binding_activity",
            "status": ObjectiveEvaluationStatus.SCORED.value,
            "utility_ppm": 1_000_000,
            "gate_result_ids": [],
            "prediction_lineage_ref": weak_prediction.prediction_id,
        }
    )

    result = combine_candidates(
        revision,
        [CandidateInput(
            "candidate-1",
            {"smiles": "C"},
            {evaluation.objective_term_id: evaluation},
            {constraint_id: ConstraintOutcome.PASS},
            {weak_prediction.prediction_id: weak_prediction},
        )],
    )

    assert result.ranked == ()
    decision = result.abstained[0]
    assert decision.disposition is CandidateDisposition.ABSTAINED
    assert decision.composite_score_ppm is None
    assert decision.objective_evaluations[0].status is ObjectiveEvaluationStatus.HYPOTHESIS_ONLY
    assert decision.objective_evaluations[0].utility_ppm == 1_000_000
    assert decision.abstention_reasons == (AbstentionReason.REQUIRED_PROVENANCE_MISSING,)
    assert decision.required_next_evidence == (f"rankable_prediction:{weak_prediction.prediction_id}",)


def test_failed_quality_gate_abstains_with_machine_readable_gate_reason() -> None:
    from src.platform_contracts import QualityGateResult

    revision = query(term("target_binding_activity", 1))
    constraint_id = resolve_constraints(revision)[0].constraint_id
    rankable_prediction = prediction()
    gate = QualityGateResult.from_content(
        {
            "gate_id": "structure-confidence-gate",
            "policy_ref": {"version": "structure-v1", "sha256": HASH_A},
            "subject_prediction_id": rankable_prediction.prediction_id,
            "metric": "structure_confidence",
            "observed_value": "0.42",
            "threshold_or_predicate": {"operator": "GTE", "value": "0.80"},
            "outcome": "FAIL",
            "reason": "LOW_STRUCTURE_CONFIDENCE",
        }
    )
    objective_evaluation = ObjectiveEvaluation.from_content(
        {
            "objective_term_id": "target_binding_activity",
            "status": "SCORED",
            "utility_ppm": 1_000_000,
            "gate_result_ids": [gate.gate_id],
            "prediction_lineage_ref": rankable_prediction.prediction_id,
        }
    )

    result = combine_candidates(
        revision,
        [CandidateInput(
            "candidate-1",
            {"smiles": "C"},
            {"target_binding_activity": objective_evaluation},
            {constraint_id: ConstraintOutcome.PASS},
            {rankable_prediction.prediction_id: rankable_prediction},
            {gate.gate_id: gate},
        )],
    )

    decision = result.abstained[0]
    assert decision.abstention_reasons == (AbstentionReason.LOW_STRUCTURE_CONFIDENCE,)
    assert decision.gate_result_ids == (gate.gate_id,)
    assert decision.canonical_ranking_decision.to_json()


def test_hypothesis_only_lineage_does_not_affect_independent_candidate_evaluations() -> None:
    revision = query(term("target_binding_activity", 1))
    constraint_id = resolve_constraints(revision)[0].constraint_id
    independent = ObjectiveEvaluation.from_content(
        {
            "objective_term_id": "target_binding_activity",
            "status": "SCORED",
            "utility_ppm": 700_000,
            "gate_result_ids": [],
            "prediction_lineage_ref": None,
        }
    )

    result = combine_candidates(
        revision,
        [CandidateInput("candidate-independent", {"smiles": "N"}, {"target_binding_activity": independent}, {constraint_id: ConstraintOutcome.PASS})],
    )

    assert result.ranked[0].composite_score_ppm == 700_000


def test_hard_constraint_fail_excludes_candidate() -> None:
    revision = query(term("target_binding_activity", 1))
    constraints = resolve_constraints(revision)
    outcomes = {constraint.constraint_id: ConstraintOutcome.PASS for constraint in constraints}
    outcomes[constraints[0].constraint_id] = ConstraintOutcome.FAIL

    result = combine_candidates(
        revision,
        [CandidateInput("candidate-1", {"smiles": "C"}, {"target_binding_activity": evaluation("target_binding_activity", 900_000)}, outcomes)],
    )

    assert result.ranked == ()
    assert result.excluded[0].disposition is CandidateDisposition.EXCLUDED
    assert result.excluded[0].reasons == (f"HARD_CONSTRAINT_FAILED:{constraints[0].constraint_id}",)
    assert result.excluded[0].composite_score_ppm is None


def test_hard_constraint_unknown_abstains_candidate() -> None:
    revision = query(term("target_binding_activity", 1))
    constraint = resolve_constraints(revision)[0]

    result = combine_candidates(
        revision,
        [CandidateInput("candidate-1", {"smiles": "C"}, {"target_binding_activity": evaluation("target_binding_activity", 900_000)}, {constraint.constraint_id: ConstraintOutcome.UNKNOWN})],
    )

    assert result.abstained[0].reasons == (f"MANDATORY_CONSTRAINT_UNRESOLVED:{constraint.constraint_id}",)
    assert result.abstained[0].required_next_evidence == (f"constraint_result:{constraint.constraint_id}",)


def test_spray_query_auto_contains_all_three_environmental_safety_constraints() -> None:
    revision = query(term("target_binding_activity", 1), application_type=ApplicationType.ENVIRONMENTAL_SPRAY)
    ids = {constraint.constraint_id for constraint in resolve_constraints(revision)}

    assert PLATFORM_CONSTRAINT_IDS["synthesizability"] in ids
    assert {
        PLATFORM_CONSTRAINT_IDS["crop_phytotoxicity"],
        PLATFORM_CONSTRAINT_IDS["soil_beneficial_microbe"],
        PLATFORM_CONSTRAINT_IDS["handler_exposure"],
    } <= ids


def test_deleting_or_shadowing_platform_constraint_is_validation_error() -> None:
    revision = query(term("target_binding_activity", 1), application_type=ApplicationType.ENVIRONMENTAL_SPRAY)
    protected_id = PLATFORM_CONSTRAINT_IDS["crop_phytotoxicity"]
    with pytest.raises(ObjectiveValidationError, match="platform constraints cannot be removed"):
        resolve_constraints(revision, removed_constraint_ids=(protected_id,))

    platform_copy = resolve_constraints(revision)[0]
    with pytest.raises(ObjectiveValidationError, match="must be user-owned"):
        create_query_revision(
            query_id="query-2",
            application_type=ApplicationType.CONTAINED_LAB,
            objectives=(term("target_binding_activity", 1),),
            user_constraints=(platform_copy,),
            actor="scientist-1",
            created_at=TS,
        )


def test_users_can_only_add_constraints_at_least_as_strict_as_platform_policy() -> None:
    weaker = Constraint.from_content(
        {
            "constraint_id": "user-weak-synthesis",
            "owner": "USER",
            "metric_ref": "metric.synthesizability_probability",
            "operator": "GTE",
            "threshold": {"value": "0.40", "unit": "probability"},
            "policy_ref": None,
        }
    )
    with pytest.raises(ObjectiveValidationError, match="at least as strict"):
        create_query_revision(
            query_id="query-weak",
            application_type=ApplicationType.CONTAINED_LAB,
            objectives=(term("target_binding_activity", 1),),
            user_constraints=(weaker,),
            actor="scientist-1",
            created_at=TS,
        )


def test_removing_objective_creates_revision_and_renormalizes_remaining_weights() -> None:
    original = query(
        term("target_binding_activity", 3),
        term("detectability", 1),
        term("stability", 2),
    )
    revised = remove_objective(original, "detectability", actor="scientist-1", created_at=TS)

    assert revised is not original
    assert revised.parent_revision_id == original.revision_id
    assert revised.revision_id != original.revision_id
    assert [item.term_id for item in revised.objectives] == ["target_binding_activity", "stability"]
    assert [item.weight_units for item in revised.objectives] == [600_000, 400_000]
    assert sum(item.weight_units for item in revised.objectives) == 1_000_000
    assert revised.change_set == ("REMOVE_OBJECTIVE",)


def test_application_type_change_is_audited_new_revision() -> None:
    original = query(term("target_binding_activity", 1))
    revised = set_application_type(
        original,
        ApplicationType.ENVIRONMENTAL_COATING,
        actor="scientist-2",
        created_at=TS,
    )
    assert revised.parent_revision_id == original.revision_id
    assert revised.application_type is ApplicationType.ENVIRONMENTAL_COATING
    assert revised.change_set == ("SET_APPLICATION_TYPE",)
    assert revised.actor == "scientist-2"


def test_zero_weights_and_complete_duplicate_terms_are_rejected() -> None:
    with pytest.raises(ValueError):
        term("stability", 0)
    duplicate = term("stability", 1, term_id="stability-copy")
    with pytest.raises(ObjectiveValidationError, match="duplicate objective terms"):
        query(term("stability", 1), duplicate)


def test_normalized_relative_weights_are_deterministic_and_nonzero() -> None:
    assert normalize_relative_weights([3, 1]) == (750_000, 250_000)
    assert normalize_relative_weights([6, 2]) == (750_000, 250_000)
    with pytest.raises(ObjectiveValidationError, match="zero weights"):
        normalize_relative_weights([1, 0])


def test_equal_scores_keep_equal_rank_and_content_hash_breaks_serialization_tie() -> None:
    revision = query(term("target_binding_activity", 1))
    constraint_id = resolve_constraints(revision)[0].constraint_id
    candidates = [
        CandidateInput("candidate-z", {"smiles": "N"}, {"target_binding_activity": evaluation("target_binding_activity", 800_000)}, {constraint_id: ConstraintOutcome.PASS}),
        CandidateInput("candidate-a", {"smiles": "C"}, {"target_binding_activity": evaluation("target_binding_activity", 800_000)}, {constraint_id: ConstraintOutcome.PASS}),
        CandidateInput("candidate-low", {"smiles": "O"}, {"target_binding_activity": evaluation("target_binding_activity", 700_000)}, {constraint_id: ConstraintOutcome.PASS}),
    ]

    result = combine_candidates(revision, candidates)

    assert [item.rank for item in result.ranked] == [1, 1, 2]
    assert result.ranked[0].composite_score_ppm == result.ranked[1].composite_score_ppm
    assert [item.candidate_content_hash for item in result.ranked[:2]] == sorted(
        item.candidate_content_hash for item in result.ranked[:2]
    )
    assert not result.debug_blocked_as_ranked


def test_records_and_result_lists_are_immutable() -> None:
    revision = query(term("target_binding_activity", 1))
    with pytest.raises(FrozenInstanceError):
        revision.actor = "tampered"  # type: ignore[misc]
