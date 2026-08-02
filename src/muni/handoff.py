"""Research review persistence and dry-lab handoff artifact generation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Mapping

from src.muni._store import (
    PersistenceIntegrityError,
    append_json_records,
    atomic_write_pair,
    read_json_array,
)
from src.muni.collection import load_collected_data, load_collection_jobs
from src.muni.study import load_study
from src.muni.workflows.diagnostic import load_diagnostic_workflow_records
from src.muni.workflows.screening import load_screening_workflow_records
from src.muni_contracts import (
    CandidateSet,
    ReviewDecision,
    ReviewRecord,
    Study,
    WetLabHandoff,
    WorkflowKind,
)
from src.platform_contracts import canonical_json, digest

DISCLAIMER = (
    "DRY-LAB SIMULATION RESULTS ONLY - AWAITING WET-LAB VALIDATION; "
    "NO LABORATORY OUTCOME IS ESTABLISHED."
)


@dataclass(frozen=True)
class _EvidenceBoundWetLabHandoff(WetLabHandoff):
    """Schema-v4 handoff identity including its exported evidence digest."""

    evidence_digest: str


class HandoffError(RuntimeError):
    """Raised when review or traceability requirements prevent a handoff."""


def _root() -> Path:
    return Path(os.environ.get("MUNI_DATA_ROOT", ".muni")).expanduser().resolve()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _read_array(path: Path) -> list[object]:
    return read_json_array(path, require_objects=True)


def _candidate_locations(root: Path):
    directory = root / "studies"
    if not directory.exists():
        return
    suffixes = (
        ".diagnostic-candidate-sets.json",
        ".compound-candidate-sets.json",
    )
    for path in sorted(directory.iterdir()):
        suffix = next((item for item in suffixes if path.name.endswith(item)), None)
        if suffix is None:
            continue
        study_id = path.name[: -len(suffix)]
        study = load_study(study_id, root=root)
        for payload in _read_array(path):
            yield study, CandidateSet.from_payload(payload)  # type: ignore[arg-type]


def _find_candidate_set(
    candidate_set_ref: str, root: Path
) -> tuple[Study, CandidateSet] | None:
    for study, candidate_set in _candidate_locations(root) or ():
        if candidate_set.set_id == candidate_set_ref:
            return study, candidate_set
    return None


def _reviews_path(study: Study, root: Path) -> Path:
    return root / "studies" / f"{study.study_id}.reviews.json"


def _persisted_review(review: ReviewRecord, root: Path) -> tuple[Study, ReviewRecord] | None:
    directory = root / "studies"
    if not directory.exists():
        return None
    for path in sorted(directory.glob("muni_study_*.reviews.json")):
        study_id = path.name.removesuffix(".reviews.json")
        for payload in _read_array(path):
            persisted = ReviewRecord.from_payload(payload)  # type: ignore[arg-type]
            if persisted.review_id == review.review_id:
                if persisted.to_json() != review.to_json():
                    raise HandoffError("persisted review content does not match the supplied review")
                return load_study(study_id, root=root), persisted
    return None


def record_review(
    candidate_set: CandidateSet,
    *,
    reviewer: str,
    decision: ReviewDecision | str,
    note: str,
) -> ReviewRecord:
    """Persist a researcher decision bound to an existing CandidateSet."""
    if not isinstance(candidate_set, CandidateSet):
        raise TypeError("candidate_set must be a CandidateSet")
    root = _root()
    located = _find_candidate_set(candidate_set.set_id, root)
    if located is None:
        raise HandoffError(
            f"CandidateSet {candidate_set.set_id} is not persisted and cannot be reviewed"
        )
    study, persisted_set = located
    if persisted_set.to_json() != candidate_set.to_json():
        raise HandoffError("persisted CandidateSet content does not match the supplied set")
    review = ReviewRecord(
        review_id="",
        candidate_set_ref=candidate_set.set_id,
        reviewer=reviewer,
        decision=decision,  # type: ignore[arg-type]
        note=note,
        decided_at=_timestamp(),
    )
    append_json_records(
        _reviews_path(study, root), review.to_payload(), require_objects=True
    )
    return review


def _workflow_lineage(study: Study, candidate_set: CandidateSet, root: Path) -> dict[str, object]:
    if candidate_set.kind is WorkflowKind.DIAGNOSTIC_DISCOVERY:
        records = load_diagnostic_workflow_records(study, root=root)
        tool_identity = "muni.diagnostic-discovery"
    elif candidate_set.kind is WorkflowKind.COMPOUND_SCREENING:
        records = load_screening_workflow_records(study, root=root)
        tool_identity = "muni.compound-screening"
    else:  # The contract currently prevents this, but keeps the boundary explicit.
        raise HandoffError(f"unsupported CandidateSet kind: {candidate_set.kind}")
    matching = [record for record in records if record.run.run_id == candidate_set.workflow_ref]
    if not matching:
        raise HandoffError("required execution lineage is missing: no matching workflow run")
    record = matching[-1]
    payload = record.to_payload()
    parameters: dict[str, object] = {
        "query_revision_ids": sorted(
            {
                str(item["query_revision_id"])
                for item in candidate_set.items
                if isinstance(item, Mapping) and item.get("query_revision_id")
            }
        )
    }
    for name in ("purpose", "application_type", "resolved_constraints"):
        if name in payload:
            parameters[name] = payload[name]
    seeds = sorted(_named_values(payload, "seed"), key=str)
    lineage: dict[str, object] = {
        "tool_identity": tool_identity,
        "run": payload["run"],
        "parameters": parameters,
    }
    if seeds:
        lineage["seed"] = seeds[0] if len(seeds) == 1 else seeds
    return lineage


def _named_values(value: object, name: str) -> list[object]:
    found: list[object] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == name:
                found.append(item)
            else:
                found.extend(_named_values(item, name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_named_values(item, name))
    return found


def _traceability(
    study: Study, candidate_set: CandidateSet, root: Path
) -> tuple[dict[str, object], dict[str, object]]:
    collected = load_collected_data(study, root=root)
    if not collected:
        raise HandoffError("required collected-data provenance is missing")
    jobs = load_collection_jobs(study, root=root)
    source_by_job = {job.job_id: job.source_ref for job in jobs}
    provenance_items = []
    for item in collected:
        source_ref = source_by_job.get(item.job_ref)
        provenance_items.append(
            {
                "job_ref": item.job_ref,
                "source_ref": source_ref,
                "source_record_ref": item.source_record_ref,
                "digest": item.digest,
            }
        )
    if any(item["source_ref"] is None for item in provenance_items):
        raise HandoffError(
            "required execution lineage is missing: collected data has no source adapter record"
        )
    workflow = _workflow_lineage(study, candidate_set, root)
    adapters = [
        {
            "adapter_identity": item["source_ref"],
            "job_ref": item["job_ref"],
        }
        for item in provenance_items
    ]
    return (
        {"collected_data": provenance_items},
        {"collection_adapters": adapters, "workflow": workflow},
    )


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _candidate_item(item: object) -> dict[str, object]:
    if not isinstance(item, Mapping):
        raise HandoffError("CandidateSet item is malformed: expected an object")
    candidate_content = {
        str(key): _plain(value)
        for key, value in item.items()
        if key != "candidate_content_hash"
    }
    result = dict(candidate_content)
    result["candidate_content"] = candidate_content
    result["candidate_content_hash"] = digest(candidate_content)
    result["rationale"] = {
        "reasons": list(item.get("reasons", [])),
        "objective_evaluations": list(item.get("objective_evaluations", [])),
        "per_objective_utility_ppm": dict(item.get("per_objective_utility_ppm", {})),
        "gate_result_ids": list(item.get("gate_result_ids", [])),
    }
    result["uncertainty"] = {
        "abstention_reasons": list(item.get("abstention_reasons", [])),
        "required_next_evidence": list(item.get("required_next_evidence", [])),
    }
    return result


def _markdown(payload: Mapping[str, object]) -> str:
    study = payload["study"]
    candidate_set = payload["candidate_set"]
    review = payload["review"]
    assert isinstance(study, Mapping)
    assert isinstance(candidate_set, Mapping)
    assert isinstance(review, Mapping)
    lines = [
        "# MUNI Research Handoff",
        "",
        f"> **{DISCLAIMER}**",
        "",
        "## Study",
        "",
        f"- Target crop: `{study['target_crop']}`",
        f"- Target pathogen: `{study['target_pathogen']}`",
        f"- Purpose: {study['purpose']}",
        "",
        "## Researcher review",
        "",
        f"- Reviewer: {review['reviewer']}",
        f"- Decision: {review['decision']}",
        f"- Note: {review['note']}",
        "",
        "## Candidate set",
        "",
        f"- Kind: `{candidate_set['kind']}`",
        f"- Count: {candidate_set['count']}",
        "",
    ]
    items = candidate_set["items"]
    assert isinstance(items, list)
    for index, item in enumerate(items, start=1):
        assert isinstance(item, Mapping)
        lines.extend(
            [
                f"### Candidate {index}: `{item.get('candidate_id', 'unnamed')}`",
                "",
                f"- Score (ppm): {item.get('composite_score_ppm')}",
                f"- Disposition: {item.get('disposition')}",
                "- Rationale and uncertainty:",
                "",
                "```json",
                json.dumps(
                    _plain(
                        {
                            "rationale": item["rationale"],
                            "uncertainty": item["uncertainty"],
                        }
                    ),
                    sort_keys=True,
                    indent=2,
                ),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Collected-data provenance",
            "",
            "```json",
            json.dumps(payload["provenance"], sort_keys=True, indent=2),
            "```",
            "",
            "## Execution lineage",
            "",
            "```json",
            json.dumps(payload["lineage"], sort_keys=True, indent=2),
            "```",
            "",
            f"> **{DISCLAIMER}**",
            "",
        ]
    )
    return "\n".join(lines)


def create_handoff(review: ReviewRecord, *, out_dir: str | Path) -> WetLabHandoff:
    """Create deterministic JSON and Markdown artifacts for an approved review."""
    if not isinstance(review, ReviewRecord):
        raise TypeError("review must be a ReviewRecord")
    root = _root()
    found_review = _persisted_review(review, root)
    if found_review is None:
        raise HandoffError(
            f"no persisted review exists for CandidateSet {review.candidate_set_ref}"
        )
    review_study, persisted_review = found_review
    if persisted_review.decision is not ReviewDecision.APPROVED:
        raise HandoffError(
            f"handoff refused because review decision is {persisted_review.decision.value}"
        )
    located = _find_candidate_set(persisted_review.candidate_set_ref, root)
    if located is None:
        raise HandoffError(
            f"reviewed CandidateSet {persisted_review.candidate_set_ref} is missing"
        )
    study, candidate_set = located
    if study.study_id != review_study.study_id:
        raise HandoffError("review and CandidateSet study bindings do not match")
    provenance, lineage = _traceability(study, candidate_set, root)
    evidence_digest = digest({"provenance": provenance, "lineage": lineage})

    boundary_set = CandidateSet(
        set_id="",
        workflow_ref=candidate_set.workflow_ref,
        kind=candidate_set.kind,
        items=tuple(_candidate_item(item) for item in candidate_set.items),
        count=candidate_set.count,
    )
    boundary_review = ReviewRecord(
        review_id="",
        candidate_set_ref=boundary_set.set_id,
        reviewer=persisted_review.reviewer,
        decision=persisted_review.decision,
        note=persisted_review.note,
        decided_at=persisted_review.decided_at,
    )
    destination = Path(out_dir).expanduser().resolve()
    json_path = destination / f"handoff-{persisted_review.review_id}.json"
    markdown_path = destination / f"handoff-{persisted_review.review_id}.md"
    handoff = _EvidenceBoundWetLabHandoff(
        handoff_id="",
        review_ref=persisted_review.review_id,
        artifact_paths=(str(json_path), str(markdown_path)),
        disclaimer=DISCLAIMER,
        evidence_digest=evidence_digest,
    )
    handoff_payload = handoff.to_payload()
    handoff_payload["candidate_set_ref"] = candidate_set.set_id
    payload: dict[str, object] = {
        "schema_version": "muni-research-handoff.v4",
        "handoff": handoff_payload,
        "persisted": {
            "review_ref": persisted_review.review_id,
            "candidate_set_ref": candidate_set.set_id,
        },
        "boundary": {
            "review_id": boundary_review.review_id,
            "candidate_set_id": boundary_set.set_id,
            "evidence_digest": evidence_digest,
        },
        "disclaimer": DISCLAIMER,
        "study": study.to_payload(),
        "review": persisted_review.to_payload(),
        "candidate_set": {
            **boundary_set.to_payload(),
            "set_id": candidate_set.set_id,
        },
        "provenance": provenance,
        "lineage": lineage,
    }
    json_bytes = canonical_json(payload) + b"\n"
    markdown_bytes = _markdown(payload).encode("utf-8")

    atomic_write_pair(
        (json_path, json_bytes),
        (markdown_path, markdown_bytes),
    )
    return handoff


__all__ = [
    "DISCLAIMER",
    "HandoffError",
    "PersistenceIntegrityError",
    "create_handoff",
    "record_review",
]
