"""Leak-proof retrospective benchmark harness.

The harness keeps outcomes out of arm inputs, requires a content-addressed split
manifest, and evaluates exactly three preregistered arms. Calibration is reported
for the D3 five-field strata and aggregated with fixed, equal stratum weights;
sample counts never affect the aggregate weight.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence, TYPE_CHECKING

from src.pipeline.scientific_contracts import canonical_json, digest

if TYPE_CHECKING:
    from src.evidence_ladder import ValidatedPair


_REQUIRED_ARMS = frozenset({"platform", "frontier_llm", "baseline"})
_SPLIT_METHOD = "connected_components:normalized_levenshtein:v1"


class BenchmarkError(ValueError):
    """Base class for benchmark contract violations."""


class BenchmarkConfigurationError(BenchmarkError):
    """The benchmark design is incomplete or invalid."""


class BenchmarkEvaluationRefused(BenchmarkError):
    """Evaluation cannot proceed without leakage controls."""


@dataclass(frozen=True)
class SyntheticItem:
    """A benchmark item. ``succeeded`` is never exposed to ranking arms."""

    item_id: str
    sequence: str
    succeeded: bool
    endpoint_definition_hash: str
    evidence_tier: str
    assay_condition_family_hash: str
    pairing_design: str

    def __post_init__(self) -> None:
        if not self.item_id or not self.sequence:
            raise BenchmarkConfigurationError("item_id and sequence must be nonempty")
        if not isinstance(self.succeeded, bool):
            raise BenchmarkConfigurationError("succeeded must be boolean")


@dataclass(frozen=True)
class BenchmarkCandidate:
    """Outcome-free view passed to every benchmark arm."""

    item_id: str
    sequence: str
    endpoint_definition_hash: str
    evidence_tier: str
    assay_condition_family_hash: str
    pairing_design: str

    @classmethod
    def from_item(cls, value: SyntheticItem) -> "BenchmarkCandidate":
        return cls(
            value.item_id,
            value.sequence,
            value.endpoint_definition_hash,
            value.evidence_tier,
            value.assay_condition_family_hash,
            value.pairing_design,
        )


@dataclass(frozen=True)
class ArmPrediction:
    item_id: str
    score: float
    confidence: float
    excluded: bool
    locked_at: datetime
    predictor_signature: str
    endpoint_definition_hash: str
    evidence_tier: str
    assay_condition_family_hash: str
    pairing_design: str

    def __post_init__(self) -> None:
        if not self.item_id:
            raise BenchmarkConfigurationError("prediction item_id must be nonempty")
        if not 0.0 <= self.score <= 1.0 or not 0.0 <= self.confidence <= 1.0:
            raise BenchmarkConfigurationError("prediction score and confidence must be in [0, 1]")
        _aware_datetime(self.locked_at, "prediction locked_at")

    @classmethod
    def from_candidate(
        cls,
        candidate: BenchmarkCandidate,
        *,
        score: float,
        confidence: float,
        excluded: bool,
        locked_at: datetime,
    ) -> "ArmPrediction":
        return cls(
            candidate.item_id,
            score,
            confidence,
            excluded,
            locked_at,
            "unassigned",
            candidate.endpoint_definition_hash,
            candidate.evidence_tier,
            candidate.assay_condition_family_hash,
            candidate.pairing_design,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "score": self.score,
            "confidence": self.confidence,
            "excluded": self.excluded,
            "locked_at": self.locked_at,
            "predictor_signature": self.predictor_signature,
            "endpoint_definition_hash": self.endpoint_definition_hash,
            "evidence_tier": self.evidence_tier,
            "assay_condition_family_hash": self.assay_condition_family_hash,
            "pairing_design": self.pairing_design,
        }


ArmScorer = Callable[[tuple[BenchmarkCandidate, ...], datetime], Sequence[ArmPrediction]]


class RankedArm:
    """Contract for a deterministic ranking arm."""

    def __init__(self, name: str, predictor_signature: str, scorer: ArmScorer):
        if not name or not predictor_signature or not callable(scorer):
            raise BenchmarkConfigurationError("arm name, signature, and scorer are required")
        self.name = name
        self.predictor_signature = predictor_signature
        self._scorer = scorer

    def rank(
        self, candidates: tuple[BenchmarkCandidate, ...], locked_at: datetime
    ) -> tuple[ArmPrediction, ...]:
        predictions = tuple(self._scorer(candidates, locked_at))
        return tuple(replace(value, predictor_signature=self.predictor_signature) for value in predictions)


class FrontierLLMArm(RankedArm):
    """Real frontier-LLM arm boundary backed by an injected offline stub.

    No provider client or network path exists in this package. Production callers
    may inject a separately governed recommender implementing ``ArmScorer``.
    """

    def __init__(self, predictor_signature: str, recommender: ArmScorer):
        super().__init__("frontier_llm", predictor_signature, recommender)


@dataclass(frozen=True)
class SplitManifest:
    split_method: str
    threshold: Decimal
    assignments: Mapping[str, str]
    dataset_digest: str
    digest: str

    def __post_init__(self) -> None:
        if self.split_method != _SPLIT_METHOD:
            raise BenchmarkConfigurationError("split manifest method is invalid")
        threshold = _threshold_decimal(self.threshold)
        if not Decimal("0") <= threshold <= Decimal("1"):
            raise BenchmarkConfigurationError("split manifest threshold must be in [0, 1]")
        if not isinstance(self.assignments, Mapping) or not self.assignments:
            raise BenchmarkConfigurationError("split manifest assignments must be a nonempty mapping")
        snapshot = dict(self.assignments)
        if any(not isinstance(key, str) or not key for key in snapshot):
            raise BenchmarkConfigurationError("split manifest item IDs must be nonempty strings")
        if any(value not in {"TRAIN", "TEST"} for value in snapshot.values()):
            raise BenchmarkConfigurationError("split manifest assignments must be TRAIN or TEST")
        if not _is_digest(self.dataset_digest) or not _is_digest(self.digest):
            raise BenchmarkConfigurationError("split manifest digests must be sha256 values")
        object.__setattr__(self, "threshold", threshold)
        object.__setattr__(self, "assignments", MappingProxyType(snapshot))

    def _content(self) -> dict[str, object]:
        return {
            "split_method": self.split_method,
            "threshold": _decimal_string(self.threshold),
            "assignments": dict(sorted(self.assignments.items())),
            "dataset_digest": self.dataset_digest,
        }

    def verify_digest(self) -> bool:
        return self.digest == digest(self._content())

    def to_payload(self) -> dict[str, object]:
        return {**self._content(), "digest": self.digest}

    def write_artifact(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json(self.to_payload()) + b"\n")
        return path


@dataclass(frozen=True)
class CalibrationStratum:
    predictor_signature: str
    endpoint_definition_hash: str
    evidence_tier: str
    assay_condition_family_hash: str
    pairing_design: str


@dataclass(frozen=True)
class CalibrationStratumReport:
    stratum: CalibrationStratum
    n: int
    predictor_signature: str
    brier_score: float
    expected_calibration_error: float
    quality: float
    weight: float


@dataclass(frozen=True)
class CalibrationQuality:
    overall: float
    strata: tuple[CalibrationStratumReport, ...]
    aggregation_method: str = "fixed_weight_macro_average"
    weighting_policy: str = "equal_preregistered_weight_per_observed_stratum_v1"


@dataclass(frozen=True)
class TopNEnrichment:
    n: int
    selected: int
    successes: int
    precision_at_n: float
    prevalence: float
    enrichment_over_prevalence: float


@dataclass(frozen=True)
class ExclusionPerformance:
    excluded: int
    true_failures_excluded: int
    exclusion_precision: float
    failure_recall: float


@dataclass(frozen=True)
class BudgetNormalizedYield:
    budget_units: int
    effective_candidates: int
    yield_per_budget_unit: float


@dataclass(frozen=True)
class ArmResult:
    predictions: tuple[ArmPrediction, ...]
    metrics: Mapping[str, object]


@dataclass(frozen=True)
class BenchmarkRun:
    split_method: str
    split_manifest_digest: str
    split_manifest_artifact: Path
    arm_results: Mapping[str, ArmResult]
    locked_at: datetime
    outcome_accessed_at: datetime


class BenchmarkRunner:
    """Execute and assess the required three-arm retrospective comparison."""

    def __init__(self, arms: Mapping[str, RankedArm]):
        names = set(arms)
        if names != _REQUIRED_ARMS:
            missing = sorted(_REQUIRED_ARMS - names)
            extra = sorted(names - _REQUIRED_ARMS)
            detail = f"missing required arms: {', '.join(missing)}" if missing else f"unexpected arms: {', '.join(extra)}"
            raise BenchmarkConfigurationError(detail)
        if any(arm.name != name for name, arm in arms.items()):
            raise BenchmarkConfigurationError("arm mapping keys must match arm names")
        self._arms = dict(arms)

    def run(
        self,
        items: Sequence[SyntheticItem],
        *,
        manifest: SplitManifest | None,
        top_n: int,
        locked_at: datetime,
        outcome_accessed_at: datetime,
        artifact_path: Path | None = None,
    ) -> BenchmarkRun:
        material = tuple(items)
        if manifest is None:
            raise BenchmarkEvaluationRefused("evaluation requires a split manifest")
        _validate_manifest(manifest, material)
        _aware_datetime(locked_at, "locked_at")
        _aware_datetime(outcome_accessed_at, "outcome_accessed_at")
        if locked_at >= outcome_accessed_at:
            raise BenchmarkEvaluationRefused("locked_at must be earlier than outcome access")
        if top_n < 1:
            raise BenchmarkConfigurationError("top_n must be positive")

        test_items = tuple(value for value in material if manifest.assignments[value.item_id] == "TEST")
        if not test_items:
            raise BenchmarkEvaluationRefused("split manifest has no TEST items")
        candidates = tuple(BenchmarkCandidate.from_item(value) for value in test_items)
        path = artifact_path or Path("split-manifest.json")
        # Persist the preregistered split before invoking any arm or reading an
        # outcome. The manifest dataset identity is outcome-blind.
        manifest.write_artifact(path)

        # Arms receive only outcome-free candidates. Outcomes are read below only
        # after every prediction set has passed the pre-registration checks.
        arm_predictions: dict[str, tuple[ArmPrediction, ...]] = {}
        for name in sorted(self._arms):
            predictions = self._arms[name].rank(candidates, locked_at)
            _validate_predictions(predictions, candidates, locked_at, outcome_accessed_at)
            arm_predictions[name] = predictions

        outcomes = {value.item_id: value.succeeded for value in test_items}
        results: dict[str, ArmResult] = {}
        for name, predictions in arm_predictions.items():
            results[name] = ArmResult(
                predictions,
                _metrics(predictions, test_items, outcomes, min(top_n, len(test_items))),
            )

        return BenchmarkRun(
            manifest.split_method,
            manifest.digest,
            path,
            results,
            locked_at,
            outcome_accessed_at,
        )


def sequence_similarity(left: str, right: str) -> float:
    """Return deterministic normalized Levenshtein similarity in ``[0, 1]``."""
    if not left or not right:
        return 1.0 if left == right else 0.0
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return 1.0 - (previous[-1] / max(len(left), len(right)))


def build_leak_proof_split(
    items: Sequence[SyntheticItem], *, threshold: float
) -> SplitManifest:
    """Group threshold-similar sequences, then assign whole components."""
    material = tuple(items)
    if len(material) < 2 or not 0.0 <= threshold <= 1.0:
        raise BenchmarkConfigurationError("split requires at least two items and threshold in [0, 1]")
    identifiers = [value.item_id for value in material]
    if len(set(identifiers)) != len(identifiers):
        raise BenchmarkConfigurationError("benchmark item_id values must be unique")

    parent = list(range(len(material)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for left_index, left in enumerate(material):
        for right_index in range(left_index + 1, len(material)):
            if sequence_similarity(left.sequence, material[right_index].sequence) >= threshold:
                union(left_index, right_index)

    components: dict[int, list[str]] = {}
    for index, value in enumerate(material):
        components.setdefault(find(index), []).append(value.item_id)
    ordered = sorted((sorted(component) for component in components.values()), key=lambda values: values[0])
    if len(ordered) < 2:
        raise BenchmarkConfigurationError("similarity threshold yields only one component; no leak-proof holdout is possible")
    assignments: dict[str, str] = {}
    for index, component in enumerate(ordered):
        role = "TRAIN" if index % 2 == 0 else "TEST"
        assignments.update((item_id, role) for item_id in component)

    canonical_threshold = _threshold_decimal(threshold)
    content = {
        "split_method": _SPLIT_METHOD,
        "threshold": _decimal_string(canonical_threshold),
        "assignments": dict(sorted(assignments.items())),
        "dataset_digest": _dataset_digest(material),
    }
    return SplitManifest(
        _SPLIT_METHOD,
        canonical_threshold,
        assignments,
        content["dataset_digest"],
        digest(content),
    )


def calibration_quality(
    predictions: Sequence[ArmPrediction],
    items: Sequence[SyntheticItem],
    *,
    fixed_weights: Mapping[CalibrationStratum, float] | None = None,
) -> CalibrationQuality:
    """Report Brier/ECE by D3 stratum and a fixed-weight macro aggregate.

    The default preregistration policy assigns weight 1.0 to every observed
    stratum. Callers may supply positive weights fixed before outcome access.
    Neither policy uses stratum sample counts as weights.
    """
    outcomes = {value.item_id: value.succeeded for value in items}
    grouped: dict[CalibrationStratum, list[ArmPrediction]] = {}
    for prediction in predictions:
        if prediction.item_id not in outcomes:
            raise BenchmarkEvaluationRefused("calibration prediction does not match dataset")
        key = CalibrationStratum(
            prediction.predictor_signature,
            prediction.endpoint_definition_hash,
            prediction.evidence_tier,
            prediction.assay_condition_family_hash,
            prediction.pairing_design,
        )
        grouped.setdefault(key, []).append(prediction)
    if not grouped:
        raise BenchmarkEvaluationRefused("calibration requires predictions")
    weights = dict(fixed_weights) if fixed_weights is not None else {key: 1.0 for key in grouped}
    if set(weights) != set(grouped) or any(value <= 0 for value in weights.values()):
        raise BenchmarkConfigurationError("fixed calibration weights must cover every stratum and be positive")

    reports: list[CalibrationStratumReport] = []
    for key in sorted(grouped, key=lambda value: tuple(value.__dict__.values())):
        rows = grouped[key]
        errors = [
            (prediction.confidence - float(outcomes[prediction.item_id])) ** 2
            for prediction in rows
        ]
        brier = sum(errors) / len(errors)
        ece = _ece(rows, outcomes)
        reports.append(
            CalibrationStratumReport(
                key,
                len(rows),
                key.predictor_signature,
                brier,
                ece,
                1.0 - brier,
                weights[key],
            )
        )
    total_weight = sum(row.weight for row in reports)
    overall = sum(row.quality * row.weight for row in reports) / total_weight
    return CalibrationQuality(overall, tuple(reports))


def calibration_training_input(pairs: Iterable["ValidatedPair"]) -> tuple["ValidatedPair", ...]:
    """Use the evidence-ladder gate; VALIDATION and TEST pairs are rejected."""
    from src.evidence_ladder import calibration_input

    return calibration_input(pairs)


def synthetic_dataset() -> tuple[SyntheticItem, ...]:
    """Return a deterministic, nontrivial dataset with both outcomes in holdout."""
    metadata = {
        "endpoint_definition_hash": "sha256:endpoint-synthetic-v1",
        "evidence_tier": "PURIFIED_ENZYME",
        "assay_condition_family_hash": "sha256:condition-synthetic-v1",
        "pairing_design": "RETROSPECTIVE_BLINDED",
    }
    rows = (
        ("c01", "GGGGCCCC", True),
        ("c02", "AAAAAAAA", False),
        ("c03", "GGGGTTTT", True),
        ("c04", "GGGGACAC", True),
        ("c05", "AAAATTTT", False),
        ("c06", "CCCCAAAA", False),
        ("c07", "GGCCGGTT", True),
        ("c08", "GGTTCGGT", True),
        ("c09", "TTTTAAAA", False),
        ("c10", "AACCAAAA", False),
    )
    return tuple(SyntheticItem(item_id, sequence, outcome, **metadata) for item_id, sequence, outcome in rows)


def run_synthetic_benchmark(
    artifact_directory: Path,
    *,
    locked_at: datetime | None = None,
    outcome_accessed_at: datetime | None = None,
) -> BenchmarkRun:
    """Exercise split, all arms, pre-registration, and all metrics offline."""
    locked = locked_at or datetime(2026, 8, 1, tzinfo=timezone.utc)
    accessed = outcome_accessed_at or datetime(2026, 8, 1, 1, tzinfo=timezone.utc)
    items = synthetic_dataset()
    manifest = build_leak_proof_split(items, threshold=0.80)

    def platform(candidates: tuple[BenchmarkCandidate, ...], when: datetime) -> tuple[ArmPrediction, ...]:
        return tuple(
            ArmPrediction.from_candidate(
                value,
                score=value.sequence.count("G") / len(value.sequence),
                confidence=0.85 if value.sequence.count("G") >= 3 else 0.15,
                excluded=value.sequence.count("G") < 2,
                locked_at=when,
            )
            for value in candidates
        )

    def llm_stub(candidates: tuple[BenchmarkCandidate, ...], when: datetime) -> tuple[ArmPrediction, ...]:
        # Deterministic literature-recommendation stand-in; deliberately weaker
        # than the platform signal and never connected to a live model API.
        return tuple(
            ArmPrediction.from_candidate(
                value,
                score=(0.7 if value.sequence.startswith("GG") else 0.3),
                confidence=(0.7 if value.sequence.startswith("GG") else 0.3),
                excluded=False,
                locked_at=when,
            )
            for value in candidates
        )

    def baseline(candidates: tuple[BenchmarkCandidate, ...], when: datetime) -> tuple[ArmPrediction, ...]:
        return tuple(
            ArmPrediction.from_candidate(
                value,
                score=sequence_similarity(value.sequence, "AAAAAAAA"),
                confidence=0.5,
                excluded=False,
                locked_at=when,
            )
            for value in candidates
        )

    arms: dict[str, RankedArm] = {
        "platform": RankedArm("platform", "pipeline-synthetic-v1", platform),
        "frontier_llm": FrontierLLMArm("llm-stub-synthetic-v1", llm_stub),
        "baseline": RankedArm("baseline", "similarity-baseline-v1", baseline),
    }
    return BenchmarkRunner(arms).run(
        items,
        manifest=manifest,
        top_n=2,
        locked_at=locked,
        outcome_accessed_at=accessed,
        artifact_path=artifact_directory / "synthetic-split-manifest.json",
    )


def _metrics(
    predictions: tuple[ArmPrediction, ...],
    items: tuple[SyntheticItem, ...],
    outcomes: Mapping[str, bool],
    top_n: int,
) -> Mapping[str, object]:
    ranked = sorted(
        (value for value in predictions if not value.excluded),
        key=lambda value: (-value.score, value.item_id),
    )[:top_n]
    successes = sum(outcomes[value.item_id] for value in ranked)
    precision = successes / len(ranked) if ranked else 0.0
    prevalence = sum(outcomes.values()) / len(outcomes)
    enrichment = precision / prevalence if prevalence else 0.0
    excluded = [value for value in predictions if value.excluded]
    true_failures = sum(not outcome for outcome in outcomes.values())
    true_failures_excluded = sum(not outcomes[value.item_id] for value in excluded)
    exclusion = ExclusionPerformance(
        len(excluded),
        true_failures_excluded,
        true_failures_excluded / len(excluded) if excluded else 0.0,
        true_failures_excluded / true_failures if true_failures else 0.0,
    )
    return {
        "top_n_enrichment": TopNEnrichment(
            top_n, len(ranked), successes, precision, prevalence, enrichment
        ),
        "exclusion_performance": exclusion,
        "calibration_quality": calibration_quality(predictions, items),
        "budget_normalized_effective_candidate_yield": BudgetNormalizedYield(
            top_n, successes, successes / top_n
        ),
    }


def _validate_manifest(manifest: SplitManifest, items: tuple[SyntheticItem, ...]) -> None:
    if manifest.split_method != _SPLIT_METHOD or not manifest.verify_digest():
        raise BenchmarkEvaluationRefused("split manifest digest or method is invalid")
    if set(manifest.assignments) != {value.item_id for value in items} or manifest.dataset_digest != _dataset_digest(items):
        raise BenchmarkEvaluationRefused("split manifest does not match benchmark dataset")
    if set(manifest.assignments.values()) - {"TRAIN", "TEST"}:
        raise BenchmarkEvaluationRefused("split manifest contains an invalid assignment")
    for left_index, left in enumerate(items):
        for right in items[left_index + 1 :]:
            if sequence_similarity(left.sequence, right.sequence) >= manifest.threshold:
                if manifest.assignments[left.item_id] != manifest.assignments[right.item_id]:
                    raise BenchmarkEvaluationRefused("split manifest permits sequence-similarity leakage")


def _validate_predictions(
    predictions: tuple[ArmPrediction, ...],
    candidates: tuple[BenchmarkCandidate, ...],
    registered_at: datetime,
    outcome_accessed_at: datetime,
) -> None:
    expected = {value.item_id: value for value in candidates}
    if len(predictions) != len(expected) or {value.item_id for value in predictions} != set(expected):
        raise BenchmarkEvaluationRefused("each arm must predict every held-out item exactly once")
    for prediction in predictions:
        candidate = expected[prediction.item_id]
        if prediction.locked_at != registered_at or prediction.locked_at >= outcome_accessed_at:
            raise BenchmarkEvaluationRefused("prediction locked_at must precede outcome access")
        fields = (
            "endpoint_definition_hash",
            "evidence_tier",
            "assay_condition_family_hash",
            "pairing_design",
        )
        if any(getattr(prediction, field) != getattr(candidate, field) for field in fields):
            raise BenchmarkEvaluationRefused("prediction calibration stratum does not match candidate")


def _ece(predictions: Sequence[ArmPrediction], outcomes: Mapping[str, bool]) -> float:
    # Ten equal-width bins, including confidence 1.0 in the final bin.
    bins: list[list[ArmPrediction]] = [[] for _ in range(10)]
    for prediction in predictions:
        bins[min(int(prediction.confidence * 10), 9)].append(prediction)
    total = len(predictions)
    return sum(
        (len(rows) / total)
        * abs(
            (sum(value.confidence for value in rows) / len(rows))
            - (sum(outcomes[value.item_id] for value in rows) / len(rows))
        )
        for rows in bins
        if rows
    )


def _dataset_digest(items: Sequence[SyntheticItem]) -> str:
    # The split is preregistered before outcome access, so its dataset identity
    # deliberately covers candidate inputs and strata but never labels.
    rows = [
        {
            "item_id": value.item_id,
            "sequence": value.sequence,
            "endpoint_definition_hash": value.endpoint_definition_hash,
            "evidence_tier": value.evidence_tier,
            "assay_condition_family_hash": value.assay_condition_family_hash,
            "pairing_design": value.pairing_design,
        }
        for value in sorted(items, key=lambda row: row.item_id)
    ]
    return digest(rows)


def _threshold_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise BenchmarkConfigurationError("split manifest threshold must be decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BenchmarkConfigurationError("split manifest threshold must be decimal") from exc
    if not result.is_finite():
        raise BenchmarkConfigurationError("split manifest threshold must be finite")
    return result


def _decimal_string(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _aware_datetime(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BenchmarkConfigurationError(f"{name} must be timezone-aware")


__all__ = [
    "ArmPrediction",
    "ArmResult",
    "BenchmarkCandidate",
    "BenchmarkConfigurationError",
    "BenchmarkError",
    "BenchmarkEvaluationRefused",
    "BenchmarkRun",
    "BenchmarkRunner",
    "BudgetNormalizedYield",
    "CalibrationQuality",
    "CalibrationStratum",
    "CalibrationStratumReport",
    "ExclusionPerformance",
    "FrontierLLMArm",
    "RankedArm",
    "SplitManifest",
    "SyntheticItem",
    "TopNEnrichment",
    "build_leak_proof_split",
    "calibration_quality",
    "calibration_training_input",
    "run_synthetic_benchmark",
    "sequence_similarity",
    "synthetic_dataset",
]
