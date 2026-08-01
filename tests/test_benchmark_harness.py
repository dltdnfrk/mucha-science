from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from src.benchmark import (
    ArmPrediction,
    BenchmarkConfigurationError,
    BenchmarkEvaluationRefused,
    BenchmarkRunner,
    CalibrationStratum,
    FrontierLLMArm,
    RankedArm,
    SplitManifest,
    SyntheticItem,
    build_leak_proof_split,
    calibration_quality,
    calibration_training_input,
    run_synthetic_benchmark,
    sequence_similarity,
)
from src.evidence_ladder import CalibrationInputRejected
from src.platform_contracts import (
    BenchmarkSplitRole,
    EvidenceTier,
    PairingDesign,
    PairRelation,
    PredictionOrigin,
    QCStatus,
)


LOCKED_AT = datetime(2026, 8, 1, tzinfo=timezone.utc)
OUTCOME_ACCESS_AT = LOCKED_AT + timedelta(hours=1)


def item(item_id: str, sequence: str, succeeded: bool, **changes: object) -> SyntheticItem:
    values = {
        "item_id": item_id,
        "sequence": sequence,
        "succeeded": succeeded,
        "endpoint_definition_hash": "sha256:endpoint-v1",
        "evidence_tier": "PURIFIED_ENZYME",
        "assay_condition_family_hash": "sha256:condition-v1",
        "pairing_design": "RETROSPECTIVE_BLINDED",
    }
    values.update(changes)
    return SyntheticItem(**values)


def predictions_for(items: tuple[SyntheticItem, ...], *, signature: str = "pipeline-v1") -> tuple[ArmPrediction, ...]:
    return tuple(
        ArmPrediction(
            item_id=value.item_id,
            score=0.9 if value.succeeded else 0.1,
            confidence=1.0 if value.succeeded else 0.0,
            excluded=not value.succeeded,
            locked_at=LOCKED_AT,
            predictor_signature=signature,
            endpoint_definition_hash=value.endpoint_definition_hash,
            evidence_tier=value.evidence_tier,
            assay_condition_family_hash=value.assay_condition_family_hash,
            pairing_design=value.pairing_design,
        )
        for value in items
    )


def three_arms() -> dict[str, RankedArm]:
    def scorer(multiplier: float):
        def rank(candidates, locked_at):
            return tuple(
                ArmPrediction.from_candidate(
                    candidate,
                    score=multiplier * (candidate.sequence.count("G") / len(candidate.sequence)),
                    confidence=0.75,
                    excluded=False,
                    locked_at=locked_at,
                )
                for candidate in candidates
            )
        return rank

    return {
        "platform": RankedArm("platform", "pipeline-v1", scorer(1.0)),
        "frontier_llm": FrontierLLMArm("llm-stub-v1", scorer(0.8)),
        "baseline": RankedArm("baseline", "similarity-v1", scorer(0.5)),
    }


def test_similarity_split_never_straddles_an_above_threshold_pair(tmp_path: Path) -> None:
    values = (
        item("a1", "AAAACCCC", True),
        item("a2", "AAAACCCA", True),
        item("b1", "GGGGTTTT", False),
        item("b2", "GGGGTTTA", False),
        item("c1", "ACGTACGT", True),
        item("d1", "TGCATGCA", False),
    )
    manifest = build_leak_proof_split(values, threshold=0.80)
    artifact = manifest.write_artifact(tmp_path / "split-manifest.json")

    assert artifact.exists()
    assert manifest.split_method == "connected_components:normalized_levenshtein:v1"
    assert manifest.verify_digest()
    for left_index, left in enumerate(values):
        for right in values[left_index + 1 :]:
            if sequence_similarity(left.sequence, right.sequence) >= manifest.threshold:
                assert manifest.assignments[left.item_id] == manifest.assignments[right.item_id]


def test_split_manifest_defensively_freezes_assignment_snapshot() -> None:
    values = (item("a", "AAAA", True), item("b", "GGGG", False))
    built = build_leak_proof_split(values, threshold=0.9)
    mutable = dict(built.assignments)
    manifest = SplitManifest(
        built.split_method,
        built.threshold,
        mutable,
        built.dataset_digest,
        built.digest,
    )

    mutable["a"] = "TEST"
    assert isinstance(manifest.assignments, MappingProxyType)
    assert manifest.assignments["a"] == built.assignments["a"]
    assert manifest.verify_digest()
    with pytest.raises(TypeError):
        manifest.assignments["a"] = "TEST"  # type: ignore[index]


def test_split_manifest_artifact_uses_canonical_decimal_strings(tmp_path: Path) -> None:
    manifest = build_leak_proof_split(
        (item("a", "AAAA", True), item("b", "GGGG", False)), threshold=0.80
    )
    payload = manifest.to_payload()

    assert payload["threshold"] == "0.8"
    artifact = manifest.write_artifact(tmp_path / "manifest.json")
    assert b'"threshold":"0.8"' in artifact.read_bytes()


def test_split_construction_is_outcome_blind() -> None:
    values = (item("a", "AAAA", True), item("b", "GGGG", False))
    reversed_outcomes = (item("a", "AAAA", False), item("b", "GGGG", True))

    original = build_leak_proof_split(values, threshold=0.9)
    reversed_labels = build_leak_proof_split(reversed_outcomes, threshold=0.9)
    assert original.assignments == reversed_labels.assignments
    assert original.dataset_digest == reversed_labels.dataset_digest


def test_evaluation_without_a_split_manifest_is_refused() -> None:
    values = (item("a", "AAAA", True), item("b", "GGGG", False))
    with pytest.raises(BenchmarkEvaluationRefused, match="split manifest"):
        BenchmarkRunner(three_arms()).run(
            values,
            manifest=None,
            top_n=1,
            locked_at=LOCKED_AT,
            outcome_accessed_at=OUTCOME_ACCESS_AT,
        )


def test_benchmark_without_baseline_arm_is_invalid() -> None:
    arms = three_arms()
    del arms["baseline"]
    with pytest.raises(BenchmarkConfigurationError, match="baseline"):
        BenchmarkRunner(arms)


def test_three_arm_synthetic_run_produces_all_four_metrics_and_is_probative(tmp_path: Path) -> None:
    run = run_synthetic_benchmark(tmp_path, locked_at=LOCKED_AT, outcome_accessed_at=OUTCOME_ACCESS_AT)

    assert set(run.arm_results) == {"platform", "frontier_llm", "baseline"}
    for result in run.arm_results.values():
        assert set(result.metrics) == {
            "top_n_enrichment",
            "exclusion_performance",
            "calibration_quality",
            "budget_normalized_effective_candidate_yield",
        }
        assert result.metrics["calibration_quality"].strata
    assert run.split_manifest_artifact.exists()
    assert run.split_manifest_digest.startswith("sha256:")
    assert (
        run.arm_results["platform"].metrics["top_n_enrichment"].precision_at_n
        > run.arm_results["baseline"].metrics["top_n_enrichment"].precision_at_n
    ), "the synthetic benchmark is non-probative unless baseline measurably differs"


def test_calibration_uses_documented_fixed_weight_macro_aggregation_not_micro_pooling() -> None:
    large = tuple(item(f"large-{index}", "AAAA", True) for index in range(9))
    small = (item("small", "CCCC", True, assay_condition_family_hash="sha256:condition-v2"),)
    values = large + small
    predicted = list(predictions_for(large))
    predicted.append(
        ArmPrediction(
            **{
                **predictions_for(small)[0].as_dict(),
                "confidence": 0.0,
            }
        )
    )
    report = calibration_quality(tuple(predicted), values)

    assert report.aggregation_method == "fixed_weight_macro_average"
    assert {row.n for row in report.strata} == {1, 9}
    assert all(row.predictor_signature == "pipeline-v1" for row in report.strata)
    assert all(row.weight == 1.0 for row in report.strata)
    # Stratum qualities are 1.0 and 0.0. Equal preregistered weights produce
    # 0.5; micro-pooling by the 9:1 sample counts would produce 0.9.
    assert report.overall == pytest.approx(0.5)


def test_prediction_locked_after_outcome_access_is_rejected() -> None:
    values = (item("a", "GGGG", True), item("b", "AAAA", False))
    manifest = build_leak_proof_split(values, threshold=0.9)
    with pytest.raises(BenchmarkEvaluationRefused, match="locked_at.*outcome"):
        BenchmarkRunner(three_arms()).run(
            values,
            manifest=manifest,
            top_n=1,
            locked_at=OUTCOME_ACCESS_AT + timedelta(seconds=1),
            outcome_accessed_at=OUTCOME_ACCESS_AT,
        )


def test_manifest_digest_or_dataset_mismatch_is_refused() -> None:
    values = (item("a", "GGGG", True), item("b", "AAAA", False))
    manifest = build_leak_proof_split(values, threshold=0.9)
    stale_values = values + (item("new", "CCCC", True),)
    with pytest.raises(BenchmarkEvaluationRefused, match="dataset"):
        BenchmarkRunner(three_arms()).run(
            stale_values,
            manifest=manifest,
            top_n=1,
            locked_at=LOCKED_AT,
            outcome_accessed_at=OUTCOME_ACCESS_AT,
        )


def test_evaluation_split_roles_cannot_train_the_calibrator() -> None:
    def pair(role: BenchmarkSplitRole):
        return SimpleNamespace(
            observation=SimpleNamespace(
                evidence_tier=EvidenceTier.PURIFIED_ENZYME,
                qc_status=QCStatus.PASS,
            ),
            prediction=SimpleNamespace(origin=PredictionOrigin.PLATFORM_COMPUTATION),
            measurement=SimpleNamespace(
                pair_relation=PairRelation.DIRECT_ESTIMAND,
                pairing_design=PairingDesign.RETROSPECTIVE_BLINDED,
                benchmark_split_role=role,
            ),
        )

    assert calibration_training_input([pair(BenchmarkSplitRole.TRAIN)])
    for role in (BenchmarkSplitRole.VALIDATION, BenchmarkSplitRole.TEST):
        with pytest.raises(CalibrationInputRejected, match="reserved for evaluation"):
            calibration_training_input([pair(role)])


def test_calibration_stratum_is_the_five_field_contract() -> None:
    fields = tuple(CalibrationStratum.__dataclass_fields__)
    assert fields == (
        "predictor_signature",
        "endpoint_definition_hash",
        "evidence_tier",
        "assay_condition_family_hash",
        "pairing_design",
    )
