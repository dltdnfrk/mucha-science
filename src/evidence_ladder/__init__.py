"""Evidence-tier and prediction/observation pairing rules.

This module deliberately operates on the immutable records in
:mod:`src.platform_contracts`.  It derives decisions and projections without
adding mutable state to those canonical records.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Mapping

from src.platform_contracts import (
    AssayObservation,
    BenchmarkSplitRole,
    EvidenceTier,
    Measurement,
    PairingDesign,
    PairRelation,
    Prediction,
    PredictionOrigin,
    QCStatus,
    SourceRecord,
    SourceSpan,
)


class EvidenceLadderError(ValueError):
    """A D2 evidence-ladder invariant was violated."""


class CalibrationInputRejected(EvidenceLadderError):
    """At least one pair is ineligible for automatic calibration."""


_TIER_ORDER: tuple[EvidenceTier, ...] = (
    EvidenceTier.PURIFIED_ENZYME,
    EvidenceTier.LYSATE,
    EvidenceTier.WHOLE_ISOLATE,
    EvidenceTier.SPIKED_MATRIX,
    EvidenceTier.RETROSPECTIVE_FIELD,
    EvidenceTier.PROSPECTIVE_FIELD,
)
_TIER_RANK = {tier: index for index, tier in enumerate(_TIER_ORDER)}


def tier_rank(tier: EvidenceTier) -> int:
    """Return the canonical zero-based rank of an evidence tier."""
    if not isinstance(tier, EvidenceTier):
        raise EvidenceLadderError("tier must be an EvidenceTier")
    return _TIER_RANK[tier]


def is_below(left: EvidenceTier, right: EvidenceTier) -> bool:
    return tier_rank(left) < tier_rank(right)


def is_above(left: EvidenceTier, right: EvidenceTier) -> bool:
    return tier_rank(left) > tier_rank(right)


@dataclass(frozen=True)
class BlindingManifest:
    """Proof that a retrospective evaluation was fixed before outcomes were accessed."""

    reference: str
    committed_at: str
    split_precommitted: bool
    outcome_hidden: bool

    def __post_init__(self) -> None:
        if not self.reference:
            raise EvidenceLadderError("blinding manifest reference must be nonempty")


@dataclass(frozen=True)
class PairingProof:
    """Design-specific evidence supplied while validating a pairing."""

    source_record: SourceRecord | None = None
    source_span: SourceSpan | None = None
    blinding_manifest: BlindingManifest | None = None


@dataclass(frozen=True)
class ValidatedPair:
    """A measurement and its resolved immutable prediction and observation."""

    measurement: Measurement
    prediction: Prediction
    observation: AssayObservation


def _validate_identity(measurement: Measurement, prediction: Prediction, observation: AssayObservation) -> None:
    if measurement.originating_prediction_id != prediction.prediction_id:
        raise EvidenceLadderError("measurement prediction reference does not resolve to the supplied immutable prediction")
    if measurement.observation_id != observation.observation_id:
        raise EvidenceLadderError("measurement observation reference does not resolve to the supplied empirical observation")


def _validate_estimand(prediction: Prediction, observation: AssayObservation) -> None:
    estimand = prediction.estimand
    if estimand["candidate_id"] != observation.candidate_id:
        raise EvidenceLadderError("prediction and observation candidate must agree")
    if estimand["target_id"] != observation.target_id:
        raise EvidenceLadderError("prediction and observation target must agree")
    if estimand["endpoint_ref"] != observation.endpoint_ref:
        raise EvidenceLadderError("prediction and observation endpoint must agree")


def _validate_units(
    prediction: Prediction,
    observation: AssayObservation,
    convertible_units: Iterable[tuple[str, str]],
) -> None:
    predicted_unit = prediction.estimand["unit"]
    observed_unit = observation.result["unit"]
    conversions = set(convertible_units)
    if observed_unit is None or (predicted_unit, observed_unit) not in conversions:
        raise EvidenceLadderError(
            f"prediction unit {predicted_unit!r} and observation unit {observed_unit!r} must be convertible"
        )


def _validate_design(
    measurement: Measurement,
    prediction: Prediction,
    observation: AssayObservation,
    proof: PairingProof,
) -> None:
    design = measurement.pairing_design
    assay_started_at = observation.assay_started_at
    if design is PairingDesign.PROSPECTIVE_LOCKED:
        if assay_started_at is None or prediction.locked_at > assay_started_at:
            raise EvidenceLadderError("prospective prediction must be locked no later than assay start")
        return

    if design is PairingDesign.RETROSPECTIVE_BLINDED:
        manifest = proof.blinding_manifest
        if (
            manifest is None
            or not manifest.split_precommitted
            or not manifest.outcome_hidden
            or manifest.committed_at >= measurement.pair_created_at
        ):
            raise EvidenceLadderError(
                "retrospective blinded pairing requires a precommitted split and outcome-hiding manifest"
            )
        return

    if design is PairingDesign.EXTERNAL_PREEXISTING:
        source = proof.source_record
        span = proof.source_span
        source_and_span_match = (
            source is not None
            and span is not None
            and span.source_id == source.source_id
            and span.artifact_sha256 == source.artifact["sha256"]
        )
        if not source_and_span_match:
            raise EvidenceLadderError("external preexisting pairing requires a matching SourceRecord and source span")
        if prediction.origin is not PredictionOrigin.EXTERNAL_COMPUTATION:
            raise EvidenceLadderError("external preexisting pairing requires an external prediction")
        if assay_started_at is None or prediction.locked_at > assay_started_at:
            raise EvidenceLadderError("external prediction must preexist the assay")
        return

    raise EvidenceLadderError(f"unsupported pairing design: {design}")


def validate_pairing(
    measurement: Measurement,
    prediction: Prediction,
    observation: AssayObservation,
    *,
    convertible_units: Iterable[tuple[str, str]],
    proof: PairingProof | None = None,
) -> ValidatedPair:
    """Validate all D2 invariants for one resolved prediction/observation pair.

    The canonical ``Measurement`` shape itself supplies exactly one prediction
    identifier and one observation identifier.  Resolution here binds those
    identifiers to exactly one immutable record of each kind.
    """
    if not isinstance(measurement, Measurement):
        raise EvidenceLadderError("measurement must be a Measurement")
    if not isinstance(prediction, Prediction):
        raise EvidenceLadderError("prediction must be a Prediction")
    if not isinstance(observation, AssayObservation):
        raise EvidenceLadderError("observation must be an AssayObservation")
    resolved_proof = proof or PairingProof()
    _validate_identity(measurement, prediction, observation)
    _validate_estimand(prediction, observation)
    _validate_units(prediction, observation, convertible_units)
    _validate_design(measurement, prediction, observation, resolved_proof)
    return ValidatedPair(measurement, prediction, observation)


@dataclass(frozen=True)
class Supersession:
    superseded_record_id: str
    replacement_record_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.superseded_record_id or not self.replacement_record_id or not self.reason:
            raise EvidenceLadderError("supersession identifiers and reason must be nonempty")
        if self.superseded_record_id == self.replacement_record_id:
            raise EvidenceLadderError("a correction must create a new superseding record")


EvidenceRecord = Prediction | AssayObservation | Measurement


class AppendOnlyEvidenceLedger:
    """Minimal append-only guard for D2 evidence records and their corrections."""

    def __init__(self) -> None:
        self._records: dict[str, EvidenceRecord] = {}
        self._superseded_by: dict[str, str] = {}

    @staticmethod
    def _record_id(record: EvidenceRecord) -> str:
        identifier = record.record_id
        if not isinstance(identifier, str) or not identifier:
            raise EvidenceLadderError("evidence record must have a canonical identifier")
        return identifier

    def _add(self, record: EvidenceRecord) -> None:
        identifier = self._record_id(record)
        existing = self._records.get(identifier)
        if existing is not None and existing != record:
            raise EvidenceLadderError("evidence records are immutable and cannot be rewritten")
        self._records.setdefault(identifier, record)

    def add_prediction(self, record: Prediction) -> None:
        self._add(record)

    def add_observation(self, record: AssayObservation) -> None:
        self._add(record)

    def add_measurement(self, record: Measurement) -> None:
        self._add(record)

    def supersede(self, event: Supersession, replacement: EvidenceRecord) -> None:
        if event.superseded_record_id not in self._records:
            raise EvidenceLadderError("cannot supersede an unknown evidence record")
        if event.superseded_record_id in self._superseded_by:
            raise EvidenceLadderError("record is already superseded; immutable history cannot be rewritten")
        if self._record_id(replacement) != event.replacement_record_id:
            raise EvidenceLadderError("supersession replacement identifier does not match replacement record")
        old_record = self._records[event.superseded_record_id]
        if type(old_record) is not type(replacement):
            raise EvidenceLadderError("a correction must supersede the same evidence record type")
        if isinstance(replacement, Prediction) and replacement.recomputes_prediction_id != event.superseded_record_id:
            raise EvidenceLadderError("a corrected prediction must link to the prediction it supersedes")
        self._add(replacement)
        self._superseded_by[event.superseded_record_id] = event.replacement_record_id

    def get(self, record_id: str) -> EvidenceRecord:
        return self._records[record_id]

    def superseded_by(self, record_id: str) -> str | None:
        return self._superseded_by.get(record_id)


@dataclass(frozen=True, init=False)
class CalibrationEligibility:
    """A read-only derivation result with no public construction path."""

    eligible: bool
    reasons: tuple[str, ...]


def _calibration_eligibility(eligible: bool, reasons: tuple[str, ...]) -> CalibrationEligibility:
    result = object.__new__(CalibrationEligibility)
    object.__setattr__(result, "eligible", eligible)
    object.__setattr__(result, "reasons", reasons)
    return result


def derive_auto_calibration_eligibility(pair: ValidatedPair) -> CalibrationEligibility:
    """Derive automatic-calibration eligibility; callers cannot override it."""
    reasons: list[str] = []
    observation = pair.observation
    prediction = pair.prediction
    measurement = pair.measurement
    if observation.evidence_tier not in {EvidenceTier.PURIFIED_ENZYME, EvidenceTier.LYSATE}:
        reasons.append("evidence tier is above LYSATE")
    if observation.qc_status is not QCStatus.PASS:
        reasons.append("observation QC status is not PASS")
    if measurement.pair_relation is not PairRelation.DIRECT_ESTIMAND:
        reasons.append("pair relation is not DIRECT_ESTIMAND")
    if prediction.origin is not PredictionOrigin.PLATFORM_COMPUTATION:
        reasons.append("prediction origin is not PLATFORM_COMPUTATION")
    if measurement.pairing_design not in {
        PairingDesign.PROSPECTIVE_LOCKED,
        PairingDesign.RETROSPECTIVE_BLINDED,
    }:
        reasons.append("pairing design is not eligible")
    if measurement.benchmark_split_role in {BenchmarkSplitRole.VALIDATION, BenchmarkSplitRole.TEST}:
        reasons.append("benchmark split role is reserved for evaluation")
    return _calibration_eligibility(not reasons, tuple(reasons))


def calibration_input(pairs: Iterable[ValidatedPair]) -> tuple[ValidatedPair, ...]:
    """Return a frozen calibration input only when every pair is eligible."""
    material = tuple(pairs)
    for pair in material:
        eligibility = derive_auto_calibration_eligibility(pair)
        if not eligibility.eligible:
            raise CalibrationInputRejected("; ".join(eligibility.reasons))
    return material


@dataclass(frozen=True)
class HumanInterpretationSignal:
    """A high-tier prediction disagreement for human scientific interpretation."""

    measurement_id: str
    prediction_id: str
    observation_id: str
    evidence_tier: EvidenceTier
    disagrees: bool


def emit_human_interpretation_signal(
    pair: ValidatedPair,
    *,
    agrees: bool,
) -> HumanInterpretationSignal | None:
    """Emit a signal for disagreement above LYSATE, with no computational side effect."""
    if not isinstance(agrees, bool):
        raise EvidenceLadderError("agreement must be a boolean interpretation")
    if agrees or not is_above(pair.observation.evidence_tier, EvidenceTier.LYSATE):
        return None
    return HumanInterpretationSignal(
        measurement_id=pair.measurement.measurement_id,
        prediction_id=pair.prediction.prediction_id,
        observation_id=pair.observation.observation_id,
        evidence_tier=pair.observation.evidence_tier,
        disagrees=True,
    )


@dataclass(frozen=True)
class HitRateStatistics:
    total_observations: int
    unpaired_observations: int
    paired_measurements: int
    successes: int
    hit_rate: Fraction | None


def hit_rate_statistics(
    observations: Iterable[AssayObservation],
    pairs: Iterable[ValidatedPair],
    agreement_by_measurement: Mapping[str, bool],
) -> HitRateStatistics:
    """Project hit-rate statistics from pairs, never from unpaired observations.

    Raw artifacts and ``replicate_group_ref`` describe technical replication
    inside an observation.  Counting is therefore by unique Measurement, not
    by raw artifact or technical replicate.
    """
    observation_records = tuple(observations)
    observation_ids = {item.observation_id for item in observation_records}
    unique_pairs: dict[str, ValidatedPair] = {}
    for pair in pairs:
        measurement_id = pair.measurement.measurement_id
        existing = unique_pairs.get(measurement_id)
        if existing is not None and existing != pair:
            raise EvidenceLadderError("one measurement identifier cannot resolve to different records")
        unique_pairs[measurement_id] = pair
    replicate_groups: dict[str, str] = {}
    for measurement_id, pair in unique_pairs.items():
        group = pair.observation.replicate_group_ref
        if group is not None and group in replicate_groups and replicate_groups[group] != measurement_id:
            raise EvidenceLadderError("technical replicates must be grouped under one measurement")
        if group is not None:
            replicate_groups[group] = measurement_id
    paired_observation_ids = {
        pair.observation.observation_id
        for pair in unique_pairs.values()
        if pair.observation.observation_id in observation_ids
    }
    counted_ids = set(unique_pairs)
    agreement_ids = set(agreement_by_measurement)
    if agreement_ids != counted_ids:
        raise EvidenceLadderError(
            "agreement keys must exactly match counted measurement IDs"
        )
    if any(type(value) is not bool for value in agreement_by_measurement.values()):
        raise EvidenceLadderError("every agreement value must be an actual bool")
    successes = sum(agreement_by_measurement[identifier] for identifier in unique_pairs)
    count = len(unique_pairs)
    return HitRateStatistics(
        total_observations=len(observation_records),
        unpaired_observations=len(observation_ids - paired_observation_ids),
        paired_measurements=count,
        successes=successes,
        hit_rate=Fraction(successes, count) if count else None,
    )


__all__ = [
    "AppendOnlyEvidenceLedger",
    "BlindingManifest",
    "CalibrationEligibility",
    "CalibrationInputRejected",
    "EvidenceLadderError",
    "HitRateStatistics",
    "HumanInterpretationSignal",
    "PairingProof",
    "Supersession",
    "ValidatedPair",
    "calibration_input",
    "derive_auto_calibration_eligibility",
    "emit_human_interpretation_signal",
    "hit_rate_statistics",
    "is_above",
    "is_below",
    "tier_rank",
    "validate_pairing",
]
