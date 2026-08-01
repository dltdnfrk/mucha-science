from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import inspect

import pytest

from src.evidence_ladder import (
    AppendOnlyEvidenceLedger,
    BlindingManifest,
    CalibrationEligibility,
    CalibrationInputRejected,
    EvidenceLadderError,
    PairingProof,
    Supersession,
    calibration_input,
    derive_auto_calibration_eligibility,
    emit_human_interpretation_signal,
    hit_rate_statistics,
    is_above,
    is_below,
    tier_rank,
    validate_pairing,
)
from src.platform_contracts import (
    AssayObservation,
    EvidenceTier,
    Measurement,
    Prediction,
    SourceRecord,
    SourceSpan,
)

TS0 = "2026-08-01T00:00:00.000000Z"
TS1 = "2026-08-01T01:00:00.000000Z"
TS2 = "2026-08-01T02:00:00.000000Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def prediction(**changes: object) -> Prediction:
    content: dict[str, object] = {
        "prediction_series_id": "series-1",
        "origin": "PLATFORM_COMPUTATION",
        "estimand": {
            "candidate_id": "candidate-1", "target_id": "target-1",
            "endpoint_ref": "endpoint.ic50", "unit": "uM",
            "condition_scope_hash": HASH_A,
        },
        "result": {"kind": "POINT", "value": "2.0"},
        "issued_at": TS0,
        "locked_at": TS0,
        "invocation_lineage_hash": HASH_A,
        "revision": 1,
        "recomputes_prediction_id": None,
        "predictor_signature": HASH_A,
        "input_hashes": [HASH_A],
        "uncertainty": {},
        "objective_normalizer_hash": HASH_B,
        "calibration_model_hash": None,
        "epistemic_status": "RANKABLE_PREDICTION",
    }
    content.update(changes)
    return Prediction.from_content(content)


def observation(**changes: object) -> AssayObservation:
    content: dict[str, object] = {
        "evidence_tier": "PURIFIED_ENZYME",
        "origin": "PLATFORM_ASSAY",
        "candidate_id": "candidate-1",
        "target_id": "target-1",
        "endpoint_ref": "endpoint.ic50",
        "assay_condition_id": "condition-1",
        "result": {"kind": "POINT", "value": "2.5", "unit": "uM"},
        "raw_artifact_refs": ["well-a", "well-b", "well-c"],
        "replicate_group_ref": "technical-replicates-1",
        "source_record_id": None,
        "assay_started_at": TS1,
        "observed_at": TS2,
        "qc_status": "PASS",
    }
    content.update(changes)
    return AssayObservation.from_content(content)


def measurement(pred: Prediction, obs: AssayObservation, **changes: object) -> Measurement:
    content: dict[str, object] = {
        "observation_id": obs.observation_id,
        "originating_prediction_id": pred.prediction_id,
        "pairing_design": "PROSPECTIVE_LOCKED",
        "pair_relation": "DIRECT_ESTIMAND",
        "benchmark_split_role": "NONE",
        "pair_created_at": TS2,
        "compatibility_check_ref": "units-registry-v1:uM",
    }
    content.update(changes)
    return Measurement.from_content(content)


def source_record() -> SourceRecord:
    return SourceRecord.from_content({
        "source_kind": "PUBLICATION", "namespace": "doi", "accession": "10.1/pre",
        "source_release": "2025", "version_status": "PINNED", "schema_version": "1",
        "api_version": "1", "canonical_uri": "https://doi.org/10.1/pre", "retrieved_at": TS0,
        "artifact": {"sha256": HASH_A, "media_type": "application/pdf", "byte_size": 10},
        "license": {"expression": "CC-BY-4.0", "terms_uri": None,
                    "terms_snapshot_sha256": None, "decision": "ALLOWED", "restrictions": [],
                    "decided_by": None, "decided_at": None},
        "citation": {"title": "Preexisting prediction"},
        "provenance": {"parent_source_ids": [], "adapter_invocation_id": None},
    })


def source_span(source: SourceRecord) -> SourceSpan:
    return SourceSpan.from_content({
        "source_id": source.source_id, "artifact_sha256": source.artifact["sha256"],
        "selector": {"type": "PDF_PAGE_BOX", "value": {"page": 1, "box": [0, 0, 1, 1]}},
        "quoted_text_sha256": HASH_B, "quoted_text": "prediction issued before assay",
    })


def valid_pair(**measurement_changes: object) -> tuple[Measurement, Prediction, AssayObservation]:
    pred = prediction()
    obs = observation()
    return measurement(pred, obs, **measurement_changes), pred, obs


def test_evidence_tiers_have_the_canonical_six_step_order() -> None:
    tiers = list(EvidenceTier)
    assert [tier_rank(tier) for tier in tiers] == list(range(6))
    assert is_below(EvidenceTier.PURIFIED_ENZYME, EvidenceTier.LYSATE)
    assert is_above(EvidenceTier.PROSPECTIVE_FIELD, EvidenceTier.SPIKED_MATRIX)
    assert not is_below(EvidenceTier.LYSATE, EvidenceTier.LYSATE)
    assert not is_above(EvidenceTier.LYSATE, EvidenceTier.LYSATE)


def test_valid_pair_references_exactly_one_immutable_prediction_and_observation() -> None:
    pair, pred, obs = valid_pair()
    validated = validate_pairing(pair, pred, obs, convertible_units={("uM", "uM")})
    assert validated.measurement is pair
    with pytest.raises(FrozenInstanceError):
        pair.observation_id = "replacement"  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("prediction_ref", "prediction"),
        ("observation_ref", "observation"),
        ("candidate", "candidate"),
        ("target", "target"),
        ("endpoint", "endpoint"),
        ("unit", "convertible"),
        ("prospective_time", "locked"),
    ],
)
def test_pairing_invariant_violations_are_rejected(mutation: str, message: str) -> None:
    pair, pred, obs = valid_pair()
    units = {("uM", "uM")}
    if mutation == "prediction_ref":
        pair = measurement(pred, obs, originating_prediction_id="pred_missing")
    elif mutation == "observation_ref":
        pair = measurement(pred, obs, observation_id="observation_missing")
    elif mutation == "candidate":
        obs = observation(candidate_id="candidate-2")
        pair = measurement(pred, obs)
    elif mutation == "target":
        obs = observation(target_id="target-2")
        pair = measurement(pred, obs)
    elif mutation == "endpoint":
        obs = observation(endpoint_ref="endpoint.ec50")
        pair = measurement(pred, obs)
    elif mutation == "unit":
        obs = observation(result={"kind": "POINT", "value": "2.5", "unit": "mg/L"})
        pair = measurement(pred, obs)
    elif mutation == "prospective_time":
        pred = prediction(locked_at=TS2)
        pair = measurement(pred, obs)
    with pytest.raises(EvidenceLadderError, match=message):
        validate_pairing(pair, pred, obs, convertible_units=units)


def test_convertible_nonidentical_units_are_accepted() -> None:
    pred = prediction()
    obs = observation(result={"kind": "POINT", "value": "2500", "unit": "nM"})
    pair = measurement(pred, obs)
    validate_pairing(pair, pred, obs, convertible_units={("uM", "nM")})


def test_retrospective_blinded_requires_a_precommitted_split_and_hidden_outcome() -> None:
    pair, pred, obs = valid_pair(pairing_design="RETROSPECTIVE_BLINDED")
    for proof in (
        PairingProof(),
        PairingProof(blinding_manifest=BlindingManifest("manifest-1", TS0, False, True)),
        PairingProof(blinding_manifest=BlindingManifest("manifest-1", TS0, True, False)),
        PairingProof(blinding_manifest=BlindingManifest("manifest-1", TS2, True, True)),
    ):
        with pytest.raises(EvidenceLadderError, match="manifest"):
            validate_pairing(pair, pred, obs, proof=proof, convertible_units={("uM", "uM")})
    proof = PairingProof(blinding_manifest=BlindingManifest("manifest-1", TS0, True, True))
    validate_pairing(pair, pred, obs, proof=proof, convertible_units={("uM", "uM")})


def test_external_preexisting_requires_external_prediction_source_record_and_span() -> None:
    pred = prediction(origin="EXTERNAL_COMPUTATION")
    obs = observation()
    pair = measurement(pred, obs, pairing_design="EXTERNAL_PREEXISTING")
    source = source_record()
    span = source_span(source)
    for proof in (PairingProof(), PairingProof(source_record=source), PairingProof(source_record=source, source_span=replace(span, source_id="source_wrong"))):
        with pytest.raises(EvidenceLadderError, match="SourceRecord.*span"):
            validate_pairing(pair, pred, obs, proof=proof, convertible_units={("uM", "uM")})
    validate_pairing(pair, pred, obs, proof=PairingProof(source, span), convertible_units={("uM", "uM")})


def test_external_preexisting_rejects_platform_or_post_assay_prediction() -> None:
    source = source_record()
    proof = PairingProof(source, source_span(source))
    obs = observation()
    for pred in (prediction(), prediction(origin="EXTERNAL_COMPUTATION", locked_at=TS2)):
        pair = measurement(pred, obs, pairing_design="EXTERNAL_PREEXISTING")
        with pytest.raises(EvidenceLadderError):
            validate_pairing(pair, pred, obs, proof=proof, convertible_units={("uM", "uM")})


def test_corrections_append_superseding_records_and_never_rewrite_prior_records() -> None:
    pair, pred, obs = valid_pair()
    ledger = AppendOnlyEvidenceLedger()
    ledger.add_prediction(pred)
    ledger.add_observation(obs)
    ledger.add_measurement(pair)
    corrected_obs = observation(result={"kind": "POINT", "value": "2.6", "unit": "uM"})
    ledger.supersede(Supersession(obs.observation_id, corrected_obs.observation_id, "corrected import"), corrected_obs)
    assert ledger.get(obs.observation_id) is obs
    assert ledger.get(corrected_obs.observation_id) is corrected_obs
    assert ledger.superseded_by(obs.observation_id) == corrected_obs.observation_id
    with pytest.raises(EvidenceLadderError, match="immutable|supersed"):
        ledger.supersede(Supersession(obs.observation_id, observation(qc_status="FAIL").observation_id, "rewrite"), observation(qc_status="FAIL"))


def test_one_prediction_can_origin_many_measurements_across_tiers() -> None:
    pred = prediction()
    low = observation()
    high = observation(evidence_tier="WHOLE_ISOLATE", assay_condition_id="condition-2")
    first = measurement(pred, low)
    second = measurement(pred, high)
    validated = [
        validate_pairing(first, pred, low, convertible_units={("uM", "uM")}),
        validate_pairing(second, pred, high, convertible_units={("uM", "uM")}),
    ]
    assert {item.measurement.originating_prediction_id for item in validated} == {pred.prediction_id}


@pytest.mark.parametrize(
    "flip",
    ["tier", "qc", "relation", "origin", "design", "validation", "test"],
)
def test_auto_calibration_eligibility_each_condition_has_a_boundary(flip: str) -> None:
    pair, pred, obs = valid_pair()
    proof = PairingProof()
    if flip == "tier":
        obs = observation(evidence_tier="WHOLE_ISOLATE")
        pair = measurement(pred, obs)
    elif flip == "qc":
        obs = observation(qc_status="FAIL")
        pair = measurement(pred, obs)
    elif flip == "relation":
        pair = measurement(pred, obs, pair_relation="DOWNSTREAM_CONTEXT")
    elif flip == "origin":
        pred = prediction(origin="EXTERNAL_COMPUTATION")
        pair = measurement(pred, obs)
    elif flip == "design":
        pair = measurement(pred, obs, pairing_design="EXTERNAL_PREEXISTING")
    elif flip == "validation":
        pair = measurement(pred, obs, benchmark_split_role="VALIDATION")
    elif flip == "test":
        pair = measurement(pred, obs, benchmark_split_role="TEST")
    if flip == "design":
        # Isolate the derivation boundary: a platform-origin external pairing is
        # not itself a valid D2 pair, but all other eligibility terms stay true.
        from src.evidence_ladder import ValidatedPair
        validated = ValidatedPair(pair, pred, obs)
    else:
        validated = validate_pairing(pair, pred, obs, proof=proof, convertible_units={("uM", "uM")})
    eligibility = derive_auto_calibration_eligibility(validated)
    assert not eligibility.eligible
    assert eligibility.reasons


def test_both_low_tiers_and_both_eligible_designs_are_eligible() -> None:
    for tier in ("PURIFIED_ENZYME", "LYSATE"):
        for design in ("PROSPECTIVE_LOCKED", "RETROSPECTIVE_BLINDED"):
            pred = prediction()
            obs = observation(evidence_tier=tier)
            pair = measurement(pred, obs, pairing_design=design)
            proof = PairingProof()
            if design == "RETROSPECTIVE_BLINDED":
                proof = PairingProof(blinding_manifest=BlindingManifest("manifest", TS0, True, True))
            validated = validate_pairing(pair, pred, obs, proof=proof, convertible_units={("uM", "uM")})
            assert derive_auto_calibration_eligibility(validated).eligible


def test_eligibility_is_derived_and_never_user_settable() -> None:
    signature = inspect.signature(derive_auto_calibration_eligibility)
    assert tuple(signature.parameters) == ("pair",)
    assert "eligible" not in inspect.signature(calibration_input).parameters
    with pytest.raises(TypeError):
        CalibrationEligibility(eligible=True, reasons=())  # type: ignore[call-arg]


def test_spiked_matrix_is_rejected_from_calibration_and_emits_human_signal() -> None:
    pred = prediction()
    obs = observation(evidence_tier="SPIKED_MATRIX")
    pair = measurement(pred, obs)
    validated = validate_pairing(pair, pred, obs, convertible_units={("uM", "uM")})
    with pytest.raises(CalibrationInputRejected, match="evidence tier"):
        calibration_input([validated])
    signal = emit_human_interpretation_signal(validated, agrees=False)
    assert signal is not None
    assert signal.measurement_id == pair.measurement_id
    assert signal.evidence_tier is EvidenceTier.SPIKED_MATRIX
    assert signal.disagrees is True
    assert not hasattr(signal, "model_parameters")


def test_higher_tier_agreement_and_low_tier_disagreement_do_not_emit_signal() -> None:
    for tier, agrees in (("SPIKED_MATRIX", True), ("LYSATE", False)):
        pred = prediction()
        obs = observation(evidence_tier=tier)
        pair = measurement(pred, obs)
        validated = validate_pairing(pair, pred, obs, convertible_units={("uM", "uM")})
        assert emit_human_interpretation_signal(validated, agrees=agrees) is None


def test_human_signal_module_has_no_model_parameter_update_path() -> None:
    import src.evidence_ladder as module

    source = inspect.getsource(module)
    forbidden = ("update_model", "fit_model", "set_parameters", "parameter_update")
    assert not any(term in source for term in forbidden)


def test_technical_replicates_count_as_one_prediction_success() -> None:
    pair, pred, obs = valid_pair()
    validated = validate_pairing(pair, pred, obs, convertible_units={("uM", "uM")})
    stats = hit_rate_statistics([obs], [validated], {pair.measurement_id: True})
    assert len(obs.raw_artifact_refs) == 3
    assert stats.paired_measurements == 1
    assert stats.successes == 1
    assert stats.hit_rate == 1


@pytest.mark.parametrize("malformed", ["true", 1, None])
def test_hit_rate_rejects_non_boolean_agreement_values(malformed: object) -> None:
    pair, pred, obs = valid_pair()
    validated = validate_pairing(pair, pred, obs, convertible_units={("uM", "uM")})

    with pytest.raises(EvidenceLadderError, match="actual bool"):
        hit_rate_statistics(
            [obs], [validated], {pair.measurement_id: malformed}  # type: ignore[dict-item]
        )


def test_hit_rate_rejects_extra_measurement_agreement_keys() -> None:
    pair, pred, obs = valid_pair()
    validated = validate_pairing(pair, pred, obs, convertible_units={("uM", "uM")})

    with pytest.raises(EvidenceLadderError, match="exactly match"):
        hit_rate_statistics(
            [obs], [validated], {pair.measurement_id: True, "measurement-extra": False}
        )


def test_separate_measurements_cannot_turn_one_technical_replicate_group_into_independent_hits() -> None:
    pred = prediction()
    first_obs = observation()
    second_obs = observation(observed_at="2026-08-01T03:00:00.000000Z")
    first = validate_pairing(measurement(pred, first_obs), pred, first_obs, convertible_units={("uM", "uM")})
    second = validate_pairing(measurement(pred, second_obs), pred, second_obs, convertible_units={("uM", "uM")})
    with pytest.raises(EvidenceLadderError, match="technical replicate"):
        hit_rate_statistics(
            [first_obs, second_obs], [first, second],
            {first.measurement.measurement_id: True, second.measurement.measurement_id: True},
        )


def test_unpaired_observations_are_first_class_and_excluded_from_statistics() -> None:
    pair, pred, paired = valid_pair()
    unpaired = observation(candidate_id=None, target_id=None, endpoint_ref="endpoint.control", assay_condition_id="condition-control")
    validated = validate_pairing(pair, pred, paired, convertible_units={("uM", "uM")})
    stats = hit_rate_statistics([paired, unpaired], [validated], {pair.measurement_id: True})
    assert unpaired.observation_id
    assert stats.total_observations == 2
    assert stats.unpaired_observations == 1
    assert stats.paired_measurements == 1
    assert stats.successes == 1
    assert stats.hit_rate == 1
    assert not hasattr(stats, "fabricated_prediction_id")
