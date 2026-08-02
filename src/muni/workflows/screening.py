"""Standalone compound screening for collected, target-agnostic MUNI studies."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from src.muni._store import append_json_records, read_json_array
from src.muni.collection import load_collected_data
from src.muni.study import _root
from src.muni_contracts import (
    CandidateSet,
    CollectedData,
    Study,
    WorkflowKind,
    WorkflowRun,
    WorkflowStatus,
)
from src.objectives import (
    OBJECTIVE_REGISTRY,
    CandidateDecision,
    CandidateInput,
    combine_candidates,
    create_query_revision,
    resolve_constraints,
)
from src.packs_loader import load_pack
from src.pipeline.scientific_contracts import canonical_json
from src.platform_contracts import (
    ApplicationType,
    Constraint,
    ConstraintOperator,
    ConstraintOutcome,
    ObjectiveTerm,
)

_DEFAULT_TOP_N = 3
_PURPOSE_PROFILES: Mapping[str, tuple[ApplicationType, tuple[str, ...]]] = MappingProxyType(
    {
        "molecular-diagnostic reagent": (
            ApplicationType.EX_VIVO_DIAGNOSTIC,
            ("detectability", "non_target_avoidance", "stability"),
        ),
        "fungicide/control agent": (
            ApplicationType.ENVIRONMENTAL_SPRAY,
            ("inhibition_kill", "non_target_avoidance", "stability"),
        ),
        "crop coating agent": (
            ApplicationType.ENVIRONMENTAL_COATING,
            ("surface_adhesion_persistence", "inhibition_kill", "stability"),
        ),
        "other environmental control agent": (
            ApplicationType.OTHER_ENVIRONMENTAL,
            ("inhibition_kill", "non_target_avoidance", "stability"),
        ),
        "contained-lab reagent": (
            ApplicationType.CONTAINED_LAB,
            ("target_binding_activity", "detectability", "stability"),
        ),
    }
)


class ScreeningWorkflowError(RuntimeError):
    """Raised when compound screening cannot safely produce candidates."""


@dataclass(frozen=True)
class ScreeningWorkflowRecord:
    """One persisted lifecycle snapshot and its disjoint screening results."""

    run: WorkflowRun
    purpose: str
    application_type: str
    resolved_constraints: tuple[Mapping[str, object], ...] = ()
    ranked: tuple[Mapping[str, object], ...] = ()
    excluded: tuple[Mapping[str, object], ...] = ()
    abstained: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, str) or not self.purpose:
            raise ValueError("screening purpose must be a nonempty string")
        try:
            ApplicationType(self.application_type)
        except (TypeError, ValueError) as exc:
            raise ValueError("screening application_type is invalid") from exc
        for name in ("resolved_constraints", "ranked", "excluded", "abstained"):
            values = tuple(MappingProxyType(dict(item)) for item in getattr(self, name))
            object.__setattr__(self, name, values)

    def to_payload(self) -> dict[str, object]:
        return {
            "run": self.run.to_payload(),
            "purpose": self.purpose,
            "application_type": self.application_type,
            "resolved_constraints": [dict(item) for item in self.resolved_constraints],
            "ranked": [dict(item) for item in self.ranked],
            "excluded": [dict(item) for item in self.excluded],
            "abstained": [dict(item) for item in self.abstained],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "ScreeningWorkflowRecord":
        expected = {
            "run",
            "purpose",
            "application_type",
            "resolved_constraints",
            "ranked",
            "excluded",
            "abstained",
        }
        if set(payload) != expected:
            raise ValueError("screening workflow record fields are frozen")
        run = payload["run"]
        if not isinstance(run, Mapping):
            raise ValueError("screening workflow run must be an object")

        def objects(name: str) -> tuple[Mapping[str, object], ...]:
            values = payload[name]
            if not isinstance(values, list) or any(not isinstance(item, Mapping) for item in values):
                raise ValueError(f"screening workflow {name} must be an array of objects")
            return tuple(item for item in values if isinstance(item, Mapping))

        return cls(
            run=WorkflowRun.from_payload(run),
            purpose=str(payload["purpose"]),
            application_type=str(payload["application_type"]),
            resolved_constraints=objects("resolved_constraints"),
            ranked=objects("ranked"),
            excluded=objects("excluded"),
            abstained=objects("abstained"),
        )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _record_path(study: Study, root: str | Path | None) -> Path:
    return _root(root) / "studies" / f"{study.study_id}.screening-workflow-runs.json"


def _candidate_set_path(study: Study, root: str | Path | None) -> Path:
    return _root(root) / "studies" / f"{study.study_id}.compound-candidate-sets.json"


def load_screening_workflow_records(
    study: Study, root: str | Path | None = None
) -> tuple[ScreeningWorkflowRecord, ...]:
    """Load screening lifecycle snapshots in persisted transition order."""
    if not isinstance(study, Study):
        raise TypeError("study must be a Study")
    return tuple(
        ScreeningWorkflowRecord.from_payload(item)  # type: ignore[arg-type]
        for item in read_json_array(
            _record_path(study, root), require_objects=True
        )
    )


def _save_record(
    study: Study, record: ScreeningWorkflowRecord, root: str | Path | None
) -> None:
    append_json_records(
        _record_path(study, root), record.to_payload(), require_objects=True
    )


def _profile(purpose: str) -> tuple[str, ApplicationType, tuple[str, ...]]:
    if not isinstance(purpose, str):
        raise ScreeningWorkflowError("purpose must be a string selected at runtime")
    normalized = " ".join(purpose.strip().lower().split())
    profile = _PURPOSE_PROFILES.get(normalized)
    if profile is None:
        supported = ", ".join(sorted(_PURPOSE_PROFILES))
        raise ScreeningWorkflowError(f"unsupported screening purpose; choose one of: {supported}")
    return normalized, profile[0], profile[1]


def _default_objectives(objective_ids: Sequence[str]) -> tuple[ObjectiveTerm, ...]:
    return tuple(
        ObjectiveTerm.from_content(
            {
                "term_id": objective_id,
                "objective_ref": OBJECTIVE_REGISTRY[objective_id].objective_ref,
                "weight_units": 1,
                "parameters": {},
            }
        )
        for objective_id in objective_ids
    )


def _load_candidate_library(candidate_source: str | Path | None) -> tuple[Mapping[str, object], ...]:
    if candidate_source is None or isinstance(candidate_source, str) and not candidate_source.strip():
        raise ScreeningWorkflowError("candidate source is required")
    if not isinstance(candidate_source, (str, Path)):
        raise TypeError("candidate_source must be a pack directory path")
    directory = Path(candidate_source)
    handle = load_pack(directory)
    candidate_path = directory / "candidates.json"
    try:
        manifest = json.loads((directory / "pack.json").read_text(encoding="utf-8"))
        declared_files = manifest["files"]
        if not any(
            isinstance(item, Mapping) and item.get("path") == "candidates.json"
            for item in declared_files
        ):
            raise ScreeningWorkflowError(
                "candidate source pack must declare candidates.json for integrity checking"
            )
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    except ScreeningWorkflowError:
        raise
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise ScreeningWorkflowError("candidate source pack needs valid candidates.json") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("candidates"), list):
        raise ScreeningWorkflowError("candidate source candidates.json needs a candidates array")
    candidates = payload["candidates"]
    if not candidates:
        raise ScreeningWorkflowError("candidate source contains no candidates")
    if any(not isinstance(item, Mapping) for item in candidates):
        raise ScreeningWorkflowError("candidate source candidates must be objects")
    provenance = {
        "name": handle.name,
        "version": handle.version,
        "manifest_sha256": handle.manifest_sha256,
    }
    return tuple({**dict(item), "candidate_pack": provenance} for item in candidates if isinstance(item, Mapping))


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or isinstance(value, float):
        return None
    try:
        result = Decimal(value)  # type: ignore[arg-type]
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _constraint_outcome(candidate: Mapping[str, object], constraint: Constraint) -> ConstraintOutcome:
    metrics_value = candidate.get("constraint_metrics", {})
    metrics = metrics_value if isinstance(metrics_value, Mapping) else {}
    observed = metrics.get(constraint.metric_ref)
    if observed is None and constraint.metric_ref == "metric.synthesizability_probability":
        synthesizable = candidate.get("synthesizable")
        if isinstance(synthesizable, bool):
            observed = "1" if synthesizable else "0"
    value = _decimal(observed)
    threshold = _decimal(constraint.threshold["value"])
    if value is None or threshold is None:
        return ConstraintOutcome.UNKNOWN
    if constraint.operator is ConstraintOperator.GTE:
        passed = value >= threshold
    elif constraint.operator is ConstraintOperator.LTE:
        passed = value <= threshold
    elif constraint.operator is ConstraintOperator.EQ:
        passed = value == threshold
    else:
        return ConstraintOutcome.UNKNOWN
    return ConstraintOutcome.PASS if passed else ConstraintOutcome.FAIL


def _utility(
    candidate: Mapping[str, object],
    collected: Sequence[CollectedData],
    term: ObjectiveTerm,
) -> int:
    values = candidate.get("objective_utilities_ppm", {})
    if isinstance(values, Mapping):
        supplied = values.get(term.term_id, values.get(term.objective_ref["id"]))
        if isinstance(supplied, int) and not isinstance(supplied, bool) and 0 <= supplied <= 1_000_000:
            return supplied
    material = canonical_json(
        {
            "candidate": candidate,
            "collected_data": sorted(item.content_hash for item in collected),
            "objective_id": term.objective_ref["id"],
        }
    )
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % 1_000_001


def _candidate_inputs(
    library: Sequence[Mapping[str, object]],
    collected: Sequence[CollectedData],
    objectives: Sequence[ObjectiveTerm],
    constraints: Sequence[Constraint],
) -> tuple[CandidateInput, ...]:
    result = []
    for index, content in enumerate(library, start=1):
        candidate_id = content.get("id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ScreeningWorkflowError(f"candidate {index} needs a nonempty id")
        result.append(
            CandidateInput(
                candidate_id=candidate_id,
                candidate_content=content,
                objective_evaluations={term.term_id: _utility(content, collected, term) for term in objectives},
                constraint_outcomes={
                    constraint.constraint_id: _constraint_outcome(content, constraint)
                    for constraint in constraints
                },
            )
        )
    return tuple(result)


def _decision_payload(
    decision: CandidateDecision, candidates: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    return {
        "candidate_id": decision.candidate_id,
        "candidate": dict(candidates[decision.candidate_id]),
        "query_revision_id": decision.query_revision_id,
        "candidate_content_hash": decision.candidate_content_hash,
        "disposition": decision.disposition.value,
        "rank": decision.rank,
        "composite_score_ppm": decision.composite_score_ppm,
        "objective_evaluations": [item.to_content() for item in decision.objective_evaluations],
        "per_objective_utility_ppm": dict(decision.per_objective_utility_ppm),
        "abstention_reasons": [item.value for item in decision.abstention_reasons],
        "gate_result_ids": list(decision.gate_result_ids),
        "reasons": list(decision.reasons),
        "required_next_evidence": list(decision.required_next_evidence),
    }


def _run(study: Study, status: WorkflowStatus, started_at: str, *, finished: bool = False) -> WorkflowRun:
    return WorkflowRun(
        run_id="",
        study_ref=study.study_id,
        kind=WorkflowKind.COMPOUND_SCREENING,
        status=status,
        started_at=started_at,
        finished_at=_timestamp() if finished else None,
    )


def run_compound_screening(
    study: Study,
    *,
    purpose: str,
    candidate_source: str | Path | None,
    top_n: int = _DEFAULT_TOP_N,
    objectives: Sequence[ObjectiveTerm] | None = None,
    user_constraints: Sequence[Constraint] = (),
    removed_constraint_ids: Iterable[str] = (),
    root: str | Path | None = None,
) -> CandidateSet:
    """Run compound ranking independently using a runtime-selected purpose.

    Candidate libraries are activated through the pack loader. The purpose,
    never the study target, selects the application type and default objectives.
    Platform policy constraints are resolved by the authoritative objectives
    bundle and cannot be removed or weakened through this entrypoint.
    """
    if not isinstance(study, Study):
        raise TypeError("study must be a Study")
    if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
        raise ScreeningWorkflowError("top_n must be a positive integer")
    normalized_purpose, application_type, default_ids = _profile(purpose)
    library = _load_candidate_library(candidate_source)
    collected = load_collected_data(study, root=root)
    if not collected:
        raise ScreeningWorkflowError(
            f"study {study.study_id} has no collected data; run collection first"
        )

    started_at = _timestamp()
    pending = _run(study, WorkflowStatus.PENDING, started_at)
    running = _run(study, WorkflowStatus.RUNNING, started_at)
    empty = {
        "purpose": normalized_purpose,
        "application_type": application_type.value,
    }
    _save_record(study, ScreeningWorkflowRecord(pending, **empty), root)
    _save_record(study, ScreeningWorkflowRecord(running, **empty), root)

    try:
        terms = _default_objectives(default_ids) if objectives is None else tuple(objectives)
        revision = create_query_revision(
            query_id=f"compound-screening:{study.study_id}:{normalized_purpose}",
            application_type=application_type,
            objectives=terms,
            user_constraints=tuple(user_constraints),
            actor="muni-compound-screening-workflow",
            created_at=started_at,
        )
        constraints = resolve_constraints(
            revision, removed_constraint_ids=tuple(removed_constraint_ids)
        )
        supplied = _candidate_inputs(library, collected, terms, constraints)
        combination = combine_candidates(revision, supplied)
        by_id = {item.candidate_id: item.candidate_content for item in supplied}
        ranked = tuple(_decision_payload(item, by_id) for item in combination.ranked)
        excluded = tuple(_decision_payload(item, by_id) for item in combination.excluded)
        abstained = tuple(_decision_payload(item, by_id) for item in combination.abstained)
        resolved = tuple(item.to_content() for item in combination.resolved_constraints)
        succeeded = _run(study, WorkflowStatus.SUCCEEDED, started_at, finished=True)
        selected = ranked[:top_n]
        candidate_set = CandidateSet(
            set_id="",
            workflow_ref=succeeded.run_id,
            kind=WorkflowKind.COMPOUND_SCREENING,
            items=selected,
            count=len(selected),
        )
    except Exception:
        _save_record(
            study,
            ScreeningWorkflowRecord(
                _run(study, WorkflowStatus.FAILED, started_at, finished=True), **empty
            ),
            root,
        )
        raise

    _save_record(
        study,
        ScreeningWorkflowRecord(
            succeeded,
            normalized_purpose,
            application_type.value,
            resolved,
            ranked,
            excluded,
            abstained,
        ),
        root,
    )
    append_json_records(
        _candidate_set_path(study, root),
        candidate_set.to_payload(),
        require_objects=True,
    )
    return candidate_set


__all__ = [
    "ScreeningWorkflowError",
    "ScreeningWorkflowRecord",
    "load_screening_workflow_records",
    "run_compound_screening",
]
