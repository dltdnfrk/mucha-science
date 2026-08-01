"""R1 replay capsules and R2 conformance checks for adapter invocations."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from src.pipeline.scientific_contracts import byte_digest, canonical_json

from .contract import InvocationRecord, ToolContractError
from .invoker import InvocationResult, ToolInvoker
from .registry import AdapterRegistry

_COMPARATORS = frozenset({"ABS_ERROR", "REL_ERROR", "RANK_CORRELATION", "TOP_K_OVERLAP"})
_INVARIANTS = frozenset({"same_constraint_disposition", "same_abstention_disposition"})


class ReplayError(ValueError):
    """The frozen replay recipe is malformed, stale, or unsupported."""


@dataclass(frozen=True)
class Comparator:
    field_or_artifact: str
    metric: str
    threshold: str
    top_k: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.field_or_artifact, str) or not self.field_or_artifact:
            raise ToolContractError("comparator field_or_artifact is required")
        if self.metric not in _COMPARATORS:
            raise ToolContractError(f"unsupported tolerance metric: {self.metric}")
        threshold = _decimal(self.threshold, "comparator threshold")
        if threshold < 0:
            raise ToolContractError("comparator threshold cannot be negative")
        if self.metric in {"RANK_CORRELATION", "TOP_K_OVERLAP"} and threshold > 1:
            raise ToolContractError("correlation and overlap thresholds cannot exceed one")
        if self.metric == "TOP_K_OVERLAP":
            if not isinstance(self.top_k, int) or isinstance(self.top_k, bool) or self.top_k < 1:
                raise ToolContractError("TOP_K_OVERLAP requires positive top_k")
        elif self.top_k is not None:
            raise ToolContractError("top_k is only valid for TOP_K_OVERLAP")

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "field_or_artifact": self.field_or_artifact,
            "metric": self.metric,
            "threshold": self.threshold,
        }
        if self.top_k is not None:
            value["top_k"] = self.top_k
        return value


@dataclass(frozen=True)
class ToleranceProfile:
    profile_id: str
    version: str
    comparators: tuple[Comparator, ...]
    decision_invariants: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id or not isinstance(self.version, str) or not self.version:
            raise ToolContractError("tolerance profile requires id and version")
        object.__setattr__(self, "comparators", tuple(self.comparators))
        object.__setattr__(self, "decision_invariants", tuple(self.decision_invariants))
        if not self.comparators:
            raise ToolContractError("tolerance profile requires at least one comparator")
        if any(not isinstance(item, Comparator) for item in self.comparators):
            raise ToolContractError("tolerance comparators must be Comparator records")
        if len({item.field_or_artifact for item in self.comparators}) != len(self.comparators):
            raise ToolContractError("tolerance comparator fields must be unique")
        if any(item not in _INVARIANTS for item in self.decision_invariants):
            raise ToolContractError("unknown tolerance decision invariant")
        if len(set(self.decision_invariants)) != len(self.decision_invariants):
            raise ToolContractError("tolerance decision invariants must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "comparators": [item.to_dict() for item in self.comparators],
            "decision_invariants": list(self.decision_invariants),
        }

    @property
    def content_hash(self) -> str:
        return byte_digest(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class ConformanceReport:
    passed: bool
    expected_sha256: str
    actual_sha256: str
    failures: tuple[str, ...]


@dataclass(frozen=True)
class ReplayReport:
    passed: bool
    expected_sha256: str
    actual_sha256: str
    failures: tuple[str, ...]


@dataclass(frozen=True)
class ReplayResult:
    invocation: InvocationResult
    r1: ReplayReport


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ToolContractError(f"{name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ToolContractError(f"{name} must be numeric") from exc
    if not result.is_finite():
        raise ToolContractError(f"{name} must be finite")
    return result


def _field(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    parts = path[1:].split("/") if path.startswith("/") else path.split(".")
    for part in parts:
        if not isinstance(current, Mapping) or part not in current:
            raise ToolContractError(f"conformance field is missing: {path}")
        current = current[part]
    return current


def _ranking(value: Any, field: str) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)) or not value or len(set(map(repr, value))) != len(value):
        raise ToolContractError(f"{field} must be a nonempty ranking with unique items")
    return tuple(value)


def _metric_passes(comparator: Comparator, expected: Any, actual: Any) -> bool:
    threshold = _decimal(comparator.threshold, "comparator threshold")
    if comparator.metric == "ABS_ERROR":
        return abs(_decimal(actual, comparator.field_or_artifact) - _decimal(expected, comparator.field_or_artifact)) <= threshold
    if comparator.metric == "REL_ERROR":
        reference = _decimal(expected, comparator.field_or_artifact)
        difference = abs(_decimal(actual, comparator.field_or_artifact) - reference)
        error = Decimal(0) if difference == 0 else (Decimal("Infinity") if reference == 0 else difference / abs(reference))
        return error <= threshold
    expected_rank = _ranking(expected, comparator.field_or_artifact)
    actual_rank = _ranking(actual, comparator.field_or_artifact)
    if comparator.metric == "RANK_CORRELATION":
        if len(expected_rank) != len(actual_rank) or set(map(repr, expected_rank)) != set(map(repr, actual_rank)):
            return False
        positions = {repr(item): position for position, item in enumerate(actual_rank)}
        squared = sum((position - positions[repr(item)]) ** 2 for position, item in enumerate(expected_rank))
        count = len(expected_rank)
        correlation = Decimal(1) if count == 1 else Decimal(1) - Decimal(6 * squared) / Decimal(count * (count * count - 1))
        return correlation >= threshold
    assert comparator.top_k is not None
    k = comparator.top_k
    if len(expected_rank) < k or len(actual_rank) < k:
        return False
    overlap = len(set(map(repr, expected_rank[:k])) & set(map(repr, actual_rank[:k])))
    return Decimal(overlap) / Decimal(k) >= threshold


def _invariant_value(value: Mapping[str, Any], invariant: str) -> Any:
    aliases = {
        "same_constraint_disposition": ("constraint_disposition", "hard_filter_disposition"),
        "same_abstention_disposition": ("abstention_disposition",),
    }[invariant]
    for path in aliases:
        try:
            return _field(value, path)
        except ToolContractError:
            try:
                return _field(value, f"decision.{path}")
            except ToolContractError:
                pass
    raise ToolContractError(f"decision invariant field is missing: {invariant}")


class R2ConformanceRunner:
    """Apply exact hashes or a pinned tolerance profile, always fail-closing decisions."""

    def __init__(self, profile: ToleranceProfile | None = None) -> None:
        self.profile = profile

    def evaluate(
        self,
        record: InvocationRecord,
        actual_canonical_output: bytes,
        expected_canonical_output: bytes | Mapping[str, Any] | None = None,
    ) -> ConformanceReport:
        if not isinstance(record, InvocationRecord) or not isinstance(actual_canonical_output, bytes):
            raise ToolContractError("R2 evaluation requires an invocation record and canonical output bytes")
        actual_hash = byte_digest(actual_canonical_output)
        if record.reproducibility_mode == "CANONICAL_EXACT":
            failures: tuple[str, ...] = ()
            if actual_hash != record.canonical_output_sha256:
                failures = (f"canonical output hash mismatch: expected {record.canonical_output_sha256}, actual {actual_hash}",)
            return ConformanceReport(not failures, record.canonical_output_sha256, actual_hash, failures)
        if self.profile is None or expected_canonical_output is None:
            raise ToolContractError("TOLERANCE evaluation requires its pinned profile and expected output")
        if record.tolerance_profile_sha256 != self.profile.content_hash:
            raise ToolContractError("tolerance profile hash does not match invocation record")
        import json
        try:
            actual = json.loads(actual_canonical_output)
            expected = json.loads(expected_canonical_output) if isinstance(expected_canonical_output, bytes) else expected_canonical_output
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolContractError("tolerance outputs must be JSON") from exc
        if not isinstance(actual, Mapping) or not isinstance(expected, Mapping):
            raise ToolContractError("tolerance outputs must be JSON objects")
        return self.compare(expected, actual)

    def compare(self, expected: Mapping[str, Any], actual: Mapping[str, Any]) -> ConformanceReport:
        if self.profile is None:
            raise ToolContractError("numeric comparison requires a tolerance profile")
        canonical_expected = canonical_json(expected)
        canonical_actual = canonical_json(actual)
        failures: list[str] = []
        for comparator in self.profile.comparators:
            if not _metric_passes(
                comparator,
                _field(expected, comparator.field_or_artifact),
                _field(actual, comparator.field_or_artifact),
            ):
                failures.append(f"{comparator.field_or_artifact}:{comparator.metric}")
        for invariant in self.profile.decision_invariants:
            if _invariant_value(expected, invariant) != _invariant_value(actual, invariant):
                failures.append(invariant)
        return ConformanceReport(
            not failures,
            byte_digest(canonical_expected),
            byte_digest(canonical_actual),
            tuple(failures),
        )


class ReplayCapsule:
    """Reconstruct and execute a built-in adapter call solely from its frozen record."""

    def __init__(self, record: InvocationRecord) -> None:
        if not isinstance(record, InvocationRecord):
            raise ReplayError("replay capsule requires an InvocationRecord")
        self.record = record

    def execute(self, staging_root: str | Path, *, timeout_seconds: float | None = None) -> ReplayResult:
        record = self.record
        if record.status != "SUCCEEDED":
            raise ReplayError("only successful invocations can be replayed")
        if record.reproducibility_mode != "CANONICAL_EXACT":
            raise ReplayError("reference replay capsule supports CANONICAL_EXACT records")
        if record.adapter.get("id") != "reference.mock_scorer":
            raise ReplayError(f"unsupported replay adapter: {record.adapter.get('id')!r}")

        from .adapters.mock_scorer import (
            MockScorerAdapter,
            mock_scorer_config,
            mock_scorer_inputs,
            mock_scorer_request,
        )
        try:
            if byte_digest(canonical_json(record.full_parameters)) != record.parameter_sha256:
                raise ReplayError("parameter_sha256 does not match frozen full_parameters")
            inputs = mock_scorer_inputs(record.full_parameters)
            manifest = [
                {"name": name, "byte_size": len(inputs[name]), "sha256": byte_digest(inputs[name])}
                for name in sorted(inputs)
            ]
            if byte_digest(canonical_json(manifest)) != record.input_manifest_sha256:
                raise ReplayError("input_manifest_sha256 does not match reconstructed inputs")
            config = mock_scorer_config()
            if record.adapter != {
                "id": config.adapter_id,
                "contract_version": config.contract_version,
                "build_sha256": config.adapter_build_sha256,
            }:
                raise ReplayError("adapter build or contract version is stale")
            if record.tool.get("dependency_lock_sha256") != config.dependency_lock_sha256:
                raise ReplayError("dependency lock is stale")
            request = mock_scorer_request(record.full_parameters, record.requested_seed)
        except (ToolContractError, OSError) as exc:
            raise ReplayError(f"invalid replay recipe: {exc}") from exc

        registry = AdapterRegistry()
        registry.register(config, MockScorerAdapter())
        registered = registry.probe(config.adapter_id)
        if (record.tool.get("name") != registered.identity.name
                or record.tool.get("reported_version") != registered.identity.reported_version
                or record.tool.get("container_digest") != config.container_digest):
            raise ReplayError("tool identity or container pin is stale")
        invocation = ToolInvoker(staging_root, timeout_seconds=timeout_seconds).invoke(
            registered,
            request,
            full_parameters=record.full_parameters,
            requested_seed=record.requested_seed,
            seed_handling=record.seed_handling,
            inputs=inputs,
            source_snapshot_ids=record.source_snapshot_ids,
        )
        failures: list[str] = []
        if invocation.record.status != "SUCCEEDED":
            failures.append(f"replay subprocess status was {invocation.record.status}")
        if invocation.record.canonical_output_sha256 != record.canonical_output_sha256:
            failures.append("canonical output hash mismatch")
        if invocation.record.environment != record.environment:
            failures.append("environment manifest mismatch")
        if invocation.record.tool != record.tool:
            failures.append("tool identity or executable hash mismatch")
        report = ReplayReport(
            not failures,
            record.canonical_output_sha256,
            invocation.record.canonical_output_sha256,
            tuple(failures),
        )
        return ReplayResult(invocation, report)


__all__ = [
    "Comparator", "ConformanceReport", "ReplayCapsule", "ReplayError", "ReplayReport",
    "ReplayResult", "R2ConformanceRunner", "ToleranceProfile",
]
