"""Standalone diagnostic-candidate discovery for collected MUNI studies."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

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
from src.platform_contracts import ApplicationType, ConstraintOutcome, ObjectiveTerm


class DiagnosticDiscoveryError(RuntimeError):
    """Raised when diagnostic discovery cannot produce a candidate set."""


@dataclass(frozen=True)
class DiagnosticWorkflowRecord:
    """A persisted workflow snapshot with its three disjoint result lists."""

    run: WorkflowRun
    ranked: tuple[Mapping[str, object], ...] = ()
    excluded: tuple[Mapping[str, object], ...] = ()
    abstained: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        for name in ("ranked", "excluded", "abstained"):
            values = tuple(MappingProxyType(dict(item)) for item in getattr(self, name))
            object.__setattr__(self, name, values)

    def to_payload(self) -> dict[str, object]:
        return {
            "run": self.run.to_payload(),
            "ranked": [dict(item) for item in self.ranked],
            "excluded": [dict(item) for item in self.excluded],
            "abstained": [dict(item) for item in self.abstained],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "DiagnosticWorkflowRecord":
        if set(payload) != {"run", "ranked", "excluded", "abstained"}:
            raise ValueError("diagnostic workflow record fields are frozen")
        run = payload["run"]
        if not isinstance(run, Mapping):
            raise ValueError("diagnostic workflow run must be an object")

        def decisions(name: str) -> tuple[Mapping[str, object], ...]:
            values = payload[name]
            if not isinstance(values, list) or any(not isinstance(item, Mapping) for item in values):
                raise ValueError(f"diagnostic workflow {name} must be an array of objects")
            return tuple(item for item in values if isinstance(item, Mapping))

        return cls(
            WorkflowRun.from_payload(run),
            decisions("ranked"),
            decisions("excluded"),
            decisions("abstained"),
        )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _record_path(study: Study, root: str | Path | None) -> Path:
    return _root(root) / "studies" / f"{study.study_id}.diagnostic-workflow-runs.json"


def _candidate_set_path(study: Study, root: str | Path | None) -> Path:
    return _root(root) / "studies" / f"{study.study_id}.diagnostic-candidate-sets.json"


def load_diagnostic_workflow_records(
    study: Study, root: str | Path | None = None
) -> tuple[DiagnosticWorkflowRecord, ...]:
    """Load lifecycle snapshots and their preserved disposition lists."""
    if not isinstance(study, Study):
        raise TypeError("study must be a Study")
    return tuple(
        DiagnosticWorkflowRecord.from_payload(item)  # type: ignore[arg-type]
        for item in read_json_array(
            _record_path(study, root), require_objects=True
        )
    )


def _save_record(
    study: Study,
    record: DiagnosticWorkflowRecord,
    root: str | Path | None,
) -> None:
    append_json_records(
        _record_path(study, root), record.to_payload(), require_objects=True
    )


def _default_objectives() -> tuple[ObjectiveTerm, ...]:
    return tuple(
        ObjectiveTerm.from_content(
            {
                "term_id": objective_id,
                "objective_ref": OBJECTIVE_REGISTRY[objective_id].objective_ref,
                "weight_units": 500_000,
                "parameters": {},
            }
        )
        for objective_id in ("detectability", "non_target_avoidance")
    )


def _validate_detection_objectives(
    objectives: Sequence[ObjectiveTerm] | None,
) -> tuple[ObjectiveTerm, ...]:
    terms = _default_objectives() if objectives is None else tuple(objectives)
    objective_ids = {
        term.objective_ref.get("id")
        for term in terms
        if isinstance(term, ObjectiveTerm)
    }
    if len(terms) != 2 or objective_ids != {"detectability", "non_target_avoidance"}:
        raise DiagnosticDiscoveryError(
            "diagnostic objectives must contain detectability and non_target_avoidance"
        )
    return terms


def _utility(data: CollectedData, objective_id: str) -> int:
    material = f"{data.content_hash}:{objective_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % 1_000_001


def _default_candidates(
    collected: Sequence[CollectedData],
    terms: Sequence[ObjectiveTerm],
    constraint_ids: Sequence[str],
) -> tuple[CandidateInput, ...]:
    candidates = []
    for data in sorted(collected, key=lambda item: (item.content_hash, item.source_record_ref)):
        candidate_id = f"diagnostic-{data.content_hash.removeprefix('sha256:')[:24]}"
        candidates.append(
            CandidateInput(
                candidate_id,
                {
                    "source_record_ref": data.source_record_ref,
                    "collected_data_hash": data.content_hash,
                },
                {
                    term.term_id: _utility(data, str(term.objective_ref["id"]))
                    for term in terms
                },
                {constraint_id: ConstraintOutcome.PASS for constraint_id in constraint_ids},
            )
        )
    return tuple(candidates)


def _decision_payload(decision: CandidateDecision) -> dict[str, object]:
    return {
        "candidate_id": decision.candidate_id,
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


def _run(
    study: Study,
    status: WorkflowStatus,
    started_at: str,
    *,
    finished: bool = False,
) -> WorkflowRun:
    return WorkflowRun(
        run_id="",
        study_ref=study.study_id,
        kind=WorkflowKind.DIAGNOSTIC_DISCOVERY,
        status=status,
        started_at=started_at,
        finished_at=_timestamp() if finished else None,
    )


def run_diagnostic_discovery(
    study: Study,
    *,
    objectives: Sequence[ObjectiveTerm] | None = None,
    candidates: Sequence[CandidateInput] | None = None,
    root: str | Path | None = None,
) -> CandidateSet:
    """Rank diagnostic candidates from a Study's collected-data provenance."""
    if not isinstance(study, Study):
        raise TypeError("study must be a Study")
    collected = load_collected_data(study, root=root)
    if not collected:
        raise DiagnosticDiscoveryError(
            f"study {study.study_id} has no collected data; run collection first"
        )

    started_at = _timestamp()
    pending = _run(study, WorkflowStatus.PENDING, started_at)
    running = _run(study, WorkflowStatus.RUNNING, started_at)
    _save_record(study, DiagnosticWorkflowRecord(pending), root)
    _save_record(study, DiagnosticWorkflowRecord(running), root)

    try:
        terms = _validate_detection_objectives(objectives)
        revision = create_query_revision(
            query_id=f"diagnostic:{study.study_id}",
            application_type=ApplicationType.EX_VIVO_DIAGNOSTIC,
            objectives=terms,
            user_constraints=(),
            actor="muni-diagnostic-workflow",
            created_at=started_at,
        )
        supplied = (
            _default_candidates(
                collected,
                terms,
                [constraint.constraint_id for constraint in resolve_constraints(revision)],
            )
            if candidates is None
            else tuple(candidates)
        )
        result = combine_candidates(revision, supplied)
        ranked = tuple(_decision_payload(item) for item in result.ranked)
        excluded = tuple(_decision_payload(item) for item in result.excluded)
        abstained = tuple(_decision_payload(item) for item in result.abstained)
        succeeded = _run(
            study, WorkflowStatus.SUCCEEDED, started_at, finished=True
        )
        candidate_set = CandidateSet(
            set_id="",
            workflow_ref=succeeded.run_id,
            kind=WorkflowKind.DIAGNOSTIC_DISCOVERY,
            items=ranked,
            count=len(ranked),
        )
    except Exception:
        _save_record(
            study,
            DiagnosticWorkflowRecord(
                _run(study, WorkflowStatus.FAILED, started_at, finished=True)
            ),
            root,
        )
        raise

    _save_record(
        study,
        DiagnosticWorkflowRecord(succeeded, ranked, excluded, abstained),
        root,
    )
    append_json_records(
        _candidate_set_path(study, root),
        candidate_set.to_payload(),
        require_objects=True,
    )
    return candidate_set


__all__ = [
    "DiagnosticDiscoveryError",
    "DiagnosticWorkflowRecord",
    "load_diagnostic_workflow_records",
    "run_diagnostic_discovery",
]
