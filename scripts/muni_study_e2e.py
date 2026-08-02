#!/usr/bin/env python3
"""Run an offline, target-agnostic MUNI Study dry-lab proof."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import time
from typing import Mapping, Sequence, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.muni.collection import (  # noqa: E402
    AdapterResult,
    collect_for_study,
    load_collected_data,
    load_collection_jobs,
)
from src.muni.handoff import DISCLAIMER, create_handoff, record_review  # noqa: E402
from src.muni.study import create_study, save_study  # noqa: E402
from src.muni.workflows.diagnostic import (  # noqa: E402
    DiagnosticDiscoveryError,
    load_diagnostic_workflow_records,
    run_diagnostic_discovery,
)
from src.muni.workflows.screening import (  # noqa: E402
    load_screening_workflow_records,
    run_compound_screening,
)
from src.muni_contracts import (  # noqa: E402
    CandidateSet,
    CollectionJobStatus,
    ReviewDecision,
    Study,
)

SCREENING_PURPOSE = "crop coating agent"
SEED_REF = "seed_984cb6855063"


class E2EGateError(RuntimeError):
    """A proof invariant was not met."""


class SyntheticCollectionAdapter:
    """Offline collection adapter injected through the public collection seam."""

    def __init__(
        self,
        source: str,
        license_decision: str,
        *,
        rendezvous: Barrier | None = None,
    ) -> None:
        self.source = source
        self.license_decision = license_decision
        self._rendezvous = rendezvous

    def __call__(self, study: Study) -> AdapterResult:
        if self._rendezvous is not None:
            self._rendezvous.wait(timeout=5)
        study_id = study.study_id
        payload = json.dumps(
            {
                "source": self.source,
                "study_ref": study_id,
                "synthetic": True,
                "disclaimer": DISCLAIMER,
            },
            sort_keys=True,
        ).encode("utf-8")
        return AdapterResult(f"{self.source}-record", payload)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--target-crop", default="synthetic-target-crop-a")
    parser.add_argument("--target-pathogen", default="synthetic-target-pathogen-x")
    parser.add_argument("--skip-collection", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _candidate(candidate_id: str, score: int) -> dict[str, object]:
    return {
        "id": candidate_id,
        "structure_like": f"SYNSTRUCT::{candidate_id}",
        "synthetic": True,
        "synthesizable": True,
        "objective_utilities_ppm": {
            "inhibition_kill": score,
            "non_target_avoidance": score,
            "stability": score,
            "surface_adhesion_persistence": score,
            "detectability": score,
        },
        "constraint_metrics": {
            "metric.synthesizability_probability": "0.95",
            "metric.crop_phytotoxicity_risk": "0.01",
            "metric.soil_beneficial_microbe_risk": "0.01",
            "metric.handler_exposure_risk": "0.01",
        },
    }


def _make_candidate_pack(directory: Path) -> Path:
    directory.mkdir(parents=True)
    candidate_payload = {
        "schema_version": "synthetic-screening-candidates.v1",
        "synthetic": True,
        "disclaimer": DISCLAIMER,
        "candidates": [
            _candidate("synthetic-compound-alpha", 910_000),
            _candidate("synthetic-compound-beta", 780_000),
            _candidate("synthetic-compound-gamma", 650_000),
        ],
    }
    raw = (json.dumps(candidate_payload, sort_keys=True) + "\n").encode("utf-8")
    (directory / "candidates.json").write_bytes(raw)
    manifest = {
        "name": "synthetic-muni-candidate-library",
        "semver": "1.0.0",
        "schema_version": "1",
        "title": "Synthetic MUNI candidate library",
        "license": {
            "expression": "LicenseRef-Synthetic",
            "terms_uri": None,
            "decision": "ALLOWED",
            "restrictions": [],
        },
        "references": [],
        "files": [
            {
                "path": "candidates.json",
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
        ],
    }
    (directory / "pack.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    return directory


def _run_diagnostic(study: Study) -> CandidateSet:
    return run_diagnostic_discovery(study)


def _run_screening(study: Study, candidate_source: Path) -> CandidateSet:
    return run_compound_screening(
        study,
        purpose=SCREENING_PURPOSE,
        candidate_source=candidate_source,
        top_n=3,
    )


def _write_json(path: Path, artifact_kind: str, records: object) -> None:
    payload = {
        "artifact_kind": artifact_kind,
        "synthetic": True,
        "disclaimer": DISCLAIMER,
        "records": records,
    }
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _audit_markdown(audit: dict[str, object]) -> str:
    constraint_ids = cast(list[object], audit["screening_constraint_ids"])
    candidate_traces = cast(list[object], audit["candidate_traces"])
    return "\n".join(
        [
            "# MUNI Study Provenance Audit",
            "",
            f"> **{DISCLAIMER}**",
            "",
            f"- Study: `{audit['study_ref']}`",
            f"- Seed reference: `{audit['seed_ref']}`",
            f"- Screening constraint count: {len(constraint_ids)}",
            f"- Candidate trace count: {len(candidate_traces)}",
            "",
            "## Complete machine-readable trace",
            "",
            "```json",
            json.dumps(audit, sort_keys=True, indent=2),
            "```",
            "",
            f"> **{DISCLAIMER}**",
            "",
        ]
    )


def _workflow_lineage(
    study: Study, candidate_set: CandidateSet, root: Path
) -> dict[str, object]:
    candidate_items = [cast(Mapping[str, object], item) for item in candidate_set.items]
    if candidate_set.kind.value == "DIAGNOSTIC_DISCOVERY":
        records = load_diagnostic_workflow_records(study, root=root)
        record = next(
            item for item in records if item.run.run_id == candidate_set.workflow_ref
        )
        return {
            "tool_identity": "muni.diagnostic-discovery",
            "run": record.run.to_payload(),
            "parameters": {
                "objective_profile": ["detectability", "non_target_avoidance"],
                "query_revision_ids": sorted(
                    {str(item["query_revision_id"]) for item in candidate_items}
                ),
            },
            "seed": None,
        }
    records = load_screening_workflow_records(study, root=root)
    record = next(
        item for item in records if item.run.run_id == candidate_set.workflow_ref
    )
    return {
        "tool_identity": "muni.compound-screening",
        "run": record.run.to_payload(),
        "parameters": {
            "purpose": record.purpose,
            "application_type": record.application_type,
            "top_n": 3,
            "query_revision_ids": sorted(
                {str(item["query_revision_id"]) for item in candidate_items}
            ),
        },
        "seed": None,
    }


def _build_audit(
    study: Study,
    candidate_sets: Sequence[CandidateSet],
    adapters: Sequence[SyntheticCollectionAdapter],
    elapsed_seconds: float,
    root: Path,
) -> dict[str, object]:
    jobs = load_collection_jobs(study, root=root)
    collected = load_collected_data(study, root=root)
    source_by_job = {job.job_id: job.source_ref for job in jobs}
    adapter_by_source = {adapter.source: adapter for adapter in adapters}
    collection_trace = []
    for item in collected:
        source = source_by_job[item.job_ref]
        adapter = adapter_by_source[source]
        collection_trace.append(
            {
                "collection_job_ref": item.job_ref,
                "source_ref": source,
                "source_record_ref": item.source_record_ref,
                "digest": item.digest,
                "execution_lineage": {
                    "adapter_identity": f"synthetic-adapter:{source}",
                    "parameters": {"license_decision": adapter.license_decision},
                    "seed": None,
                },
            }
        )
    final_screening = load_screening_workflow_records(study, root=root)[-1]
    constraint_ids = sorted(
        str(item["constraint_id"]) for item in final_screening.resolved_constraints
    )
    study_identity = study.to_payload()
    candidate_traces = []
    for candidate_set in candidate_sets:
        workflow = _workflow_lineage(study, candidate_set, root)
        for raw_item in candidate_set.items:
            item = cast(Mapping[str, object], raw_item)
            candidate_traces.append(
                {
                    "candidate_id": item["candidate_id"],
                    "candidate_set_ref": candidate_set.set_id,
                    "study_identity": study_identity,
                    "collection_trace": collection_trace,
                    "execution_lineage": workflow,
                }
            )
    return {
        "schema_version": "muni-provenance-audit.v1",
        "synthetic": True,
        "disclaimer": DISCLAIMER,
        "study_ref": study.study_id,
        "seed_ref": SEED_REF,
        "collection": {
            "parallel": True,
            "max_workers": len(adapters),
            "elapsed_seconds": elapsed_seconds,
            "jobs": [job.to_payload() for job in jobs],
        },
        "screening_constraint_ids": constraint_ids,
        "candidate_traces": candidate_traces,
    }


def _execute(args: argparse.Namespace) -> None:
    output = args.out.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise E2EGateError(f"output directory must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="muni-e2e-runtime-") as runtime_name:
        runtime = Path(runtime_name)
        os.environ["MUNI_DATA_ROOT"] = str(runtime / "store")
        candidate_source = (
            args.pack.expanduser().resolve()
            if args.pack is not None
            else _make_candidate_pack(runtime / "candidate-pack")
        )
        study = create_study(
            args.target_crop,
            args.target_pathogen,
            "synthetic dry-lab candidate assessment",
            pack_ref=str(candidate_source),
        )
        save_study(study)
        print(f"STUDY {study.study_id} created")

        if args.skip_collection:
            try:
                _run_diagnostic(study)
            except DiagnosticDiscoveryError as exc:
                raise E2EGateError(
                    f"workflow gate refused before collection: {exc}"
                ) from exc
            raise E2EGateError("workflow gate accepted a study without collected data")

        rendezvous = Barrier(2)
        adapters = [
            SyntheticCollectionAdapter(
                "synthetic-source-alpha", "ALLOWED", rendezvous=rendezvous
            ),
            SyntheticCollectionAdapter(
                "synthetic-source-beta", "ALLOWED", rendezvous=rendezvous
            ),
            SyntheticCollectionAdapter("synthetic-deferred-source", "DENIED"),
        ]
        started = time.perf_counter()
        final_jobs = collect_for_study(study, adapters, max_workers=len(adapters))
        elapsed = time.perf_counter() - started
        statuses = {job.status for job in final_jobs}
        required = {CollectionJobStatus.SUCCEEDED, CollectionJobStatus.SKIPPED}
        if not required <= statuses:
            raise E2EGateError("collection did not record both SUCCEEDED and SKIPPED")
        print(f"COLLECTION parallel jobs={len(final_jobs)} elapsed={elapsed:.6f}s")
        for job in final_jobs:
            detail = f" reason={job.reason}" if job.reason else ""
            print(f"  {job.source_ref}: {job.status.value}{detail}")

        diagnostic_set = _run_diagnostic(study)
        print(f"DIAGNOSTIC candidate_set={diagnostic_set.set_id} count={diagnostic_set.count}")

        screening_set = _run_screening(study, candidate_source)
        print(f"SCREENING candidate_set={screening_set.set_id} count={screening_set.count}")

        candidate_sets = (diagnostic_set, screening_set)
        reviews = []
        handoffs = []
        for candidate_set in candidate_sets:
            review = record_review(
                candidate_set,
                reviewer="synthetic-reviewer-alpha",
                decision=ReviewDecision.APPROVED,
                note="Reviewed for downstream wet-lab validation planning.",
            )
            kind = candidate_set.kind.value.lower().replace("_", "-")
            handoff = create_handoff(review, out_dir=output / "handoffs" / kind)
            reviews.append(review)
            handoffs.append(handoff)
            print(f"HANDOFF kind={candidate_set.kind.value} id={handoff.handoff_id}")

        root = Path(os.environ["MUNI_DATA_ROOT"])
        jobs = load_collection_jobs(study, root=root)
        audit = _build_audit(study, candidate_sets, adapters, elapsed, root)
        _write_json(output / "study-record.json", "Study", [study.to_payload()])
        _write_json(
            output / "collection-job-table.json",
            "CollectionJobTable",
            {
                "parallel": True,
                "elapsed_seconds": elapsed,
                "rows": [job.to_payload() for job in jobs],
            },
        )
        _write_json(
            output / "candidate-sets.json",
            "CandidateSets",
            [item.to_payload() for item in candidate_sets],
        )
        _write_json(
            output / "review-records.json",
            "ReviewRecords",
            [item.to_payload() for item in reviews],
        )
        _write_json(
            output / "wet-lab-handoffs.json",
            "WetLabHandoffs",
            [item.to_payload() for item in handoffs],
        )
        (output / "provenance-audit.json").write_text(
            json.dumps(audit, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        (output / "provenance-audit.md").write_text(
            _audit_markdown(audit), encoding="utf-8"
        )
        print(f"AUDIT {output / 'provenance-audit.json'}")
        print(f"MUNI E2E SUCCESS: {DISCLAIMER}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        _execute(_arguments(argv))
    except Exception as exc:
        print(f"MUNI E2E FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
