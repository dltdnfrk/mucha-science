from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

import pytest

from src.muni import PersistenceIntegrityError
from src.muni.collection import AdapterResult, collect_for_study
from src.muni.handoff import HandoffError, create_handoff, record_review
from src.muni.study import create_study, save_study
from src.muni.workflows.diagnostic import run_diagnostic_discovery
from src.muni.workflows.screening import run_compound_screening
from src.muni_contracts import (
    CandidateSet,
    CollectedData,
    ReviewDecision,
    ReviewRecord,
    Study,
    WorkflowKind,
)
from src.platform_contracts import digest

DISCLAIMER_FRAGMENT = "DRY-LAB SIMULATION RESULTS ONLY"
FORBIDDEN_EFFICACY_CLAIMS = (
    "proven",
    "effective",
    "efficacy",
    "kills",
    "performs better",
)


class _SyntheticAdapter:
    source = "synthetic-source-alpha"
    license_decision = "ALLOWED"

    def __call__(self, _study):
        return AdapterResult("synthetic-record-alpha", b"synthetic-observation-alpha")


def _collected_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "store"
    monkeypatch.setenv("MUNI_DATA_ROOT", str(root))
    study = create_study(
        "synthetic-host-alpha",
        "synthetic-agent-omega",
        "synthetic simulation assessment",
    )
    collect_for_study(study, [_SyntheticAdapter()])
    return study


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
        },
        "constraint_metrics": {
            "metric.synthesizability_probability": "0.95",
            "metric.crop_phytotoxicity_risk": "0.01",
            "metric.soil_beneficial_microbe_risk": "0.01",
            "metric.handler_exposure_risk": "0.01",
        },
    }


def _pack(tmp_path: Path, candidates: list[dict[str, object]]) -> Path:
    directory = tmp_path / "synthetic-candidate-pack"
    directory.mkdir()
    payload = {
        "schema_version": "synthetic-candidates.v1",
        "synthetic": True,
        "candidates": candidates,
    }
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    (directory / "candidates.json").write_bytes(raw)
    manifest = {
        "name": "synthetic-candidate-library",
        "semver": "1.0.0",
        "schema_version": "1",
        "title": "Synthetic candidate library",
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
    (directory / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def _assert_artifacts(handoff, expected_count: int) -> dict[str, object]:
    assert len(handoff.artifact_paths) == 2
    json_path, markdown_path = map(Path, handoff.artifact_paths)
    assert json_path.exists()
    assert markdown_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert DISCLAIMER_FRAGMENT in payload["disclaimer"]
    assert DISCLAIMER_FRAGMENT in markdown
    assert payload["study"]["target_crop"] == "synthetic-host-alpha"
    assert payload["study"]["target_pathogen"] == "synthetic-agent-omega"
    assert payload["study"]["purpose"] == "synthetic simulation assessment"
    assert "created_at" in payload["study"]
    assert "pack_ref" in payload["study"]
    Study.from_payload(payload["study"])
    assert payload["schema_version"] == "muni-research-handoff.v4"
    assert len(payload["candidate_set"]["items"]) == expected_count
    assert payload["provenance"]["collected_data"]
    assert payload["lineage"]["collection_adapters"]
    assert payload["lineage"]["workflow"]["tool_identity"]
    assert payload["lineage"]["workflow"]["parameters"]
    assert payload["boundary"]["evidence_digest"] == digest(
        {"provenance": payload["provenance"], "lineage": payload["lineage"]}
    )
    assert (
        payload["handoff"]["evidence_digest"]
        == payload["boundary"]["evidence_digest"]
    )
    for item in payload["candidate_set"]["items"]:
        assert "composite_score_ppm" in item
        assert "disposition" in item
        assert "rationale" in item
        assert "uncertainty" in item
        assert item["candidate_content_hash"] == digest(item["candidate_content"])

    combined = json_path.read_text(encoding="utf-8") + "\n" + markdown
    for phrase in FORBIDDEN_EFFICACY_CLAIMS:
        assert re.search(rf"\b{re.escape(phrase)}\b", combined, re.IGNORECASE) is None
    return payload


def test_approved_diagnostic_review_creates_complete_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    candidate_set = run_diagnostic_discovery(study)
    review = record_review(
        candidate_set,
        reviewer="synthetic-researcher-alpha",
        decision=ReviewDecision.APPROVED,
        note="Reviewed for downstream validation planning.",
    )

    handoff = create_handoff(review, out_dir=tmp_path / "diagnostic-handoff")

    payload = _assert_artifacts(handoff, expected_count=1)
    assert payload["candidate_set"]["kind"] == "DIAGNOSTIC_DISCOVERY"
    first_bytes = [Path(path).read_bytes() for path in handoff.artifact_paths]
    repeated = create_handoff(review, out_dir=tmp_path / "diagnostic-handoff")
    assert [Path(path).read_bytes() for path in repeated.artifact_paths] == first_bytes


def test_handoff_links_to_persisted_review_and_candidate_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    candidate_set = run_diagnostic_discovery(study)
    review = record_review(
        candidate_set,
        reviewer="synthetic-linkage-reviewer",
        decision=ReviewDecision.APPROVED,
        note="Linkage invariant review.",
    )

    handoff = create_handoff(review, out_dir=tmp_path / "linkage-handoff")
    payload = json.loads(Path(handoff.artifact_paths[0]).read_text(encoding="utf-8"))
    persisted_reviews = json.loads(
        (
            tmp_path
            / "store"
            / "studies"
            / f"{study.study_id}.reviews.json"
        ).read_text(encoding="utf-8")
    )
    persisted_sets = json.loads(
        (
            tmp_path
            / "store"
            / "studies"
            / f"{study.study_id}.diagnostic-candidate-sets.json"
        ).read_text(encoding="utf-8")
    )

    assert handoff.review_ref == review.review_id
    assert {Path(path).name for path in handoff.artifact_paths} == {
        f"handoff-{review.review_id}.json",
        f"handoff-{review.review_id}.md",
    }
    assert payload["handoff"]["review_ref"] == review.review_id
    assert payload["handoff"]["candidate_set_ref"] == candidate_set.set_id
    assert payload["persisted"] == {
        "review_ref": review.review_id,
        "candidate_set_ref": candidate_set.set_id,
    }
    assert payload["review"]["review_id"] == review.review_id
    assert payload["review"]["candidate_set_ref"] == candidate_set.set_id
    assert payload["candidate_set"]["set_id"] == candidate_set.set_id
    assert payload["boundary"]["review_id"] != review.review_id
    assert payload["boundary"]["candidate_set_id"] != candidate_set.set_id
    assert any(item["review_id"] == handoff.review_ref for item in persisted_reviews)
    assert any(
        item["set_id"] == payload["handoff"]["candidate_set_ref"]
        for item in persisted_sets
    )


def test_failed_second_publish_restores_existing_handoff_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    candidate_set = run_diagnostic_discovery(study)
    review = record_review(
        candidate_set,
        reviewer="synthetic-researcher-rollback",
        decision=ReviewDecision.APPROVED,
        note="Rollback fixture review.",
    )
    handoff = create_handoff(review, out_dir=tmp_path / "rollback-handoff")
    paths = tuple(Path(path) for path in handoff.artifact_paths)
    prior = tuple(path.read_bytes() for path in paths)
    real_replace = os.replace
    publishes = 0

    def fail_second_publish(source, destination):
        nonlocal publishes
        destination_path = Path(destination)
        if destination_path in paths:
            publishes += 1
            if publishes == 2:
                raise OSError("injected second publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_publish)

    with pytest.raises(OSError, match="injected second publish failure"):
        create_handoff(review, out_dir=tmp_path / "rollback-handoff")

    assert tuple(path.read_bytes() for path in paths) == prior


def test_approved_compound_review_carries_multiple_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    source = _pack(
        tmp_path,
        [
            _candidate("synthetic-compound-alpha", 910_000),
            _candidate("synthetic-compound-beta", 780_000),
            _candidate("synthetic-compound-gamma", 650_000),
        ],
    )
    candidate_set = run_compound_screening(
        study,
        purpose="fungicide/control agent",
        candidate_source=source,
        top_n=3,
    )
    review = record_review(
        candidate_set,
        reviewer="synthetic-researcher-beta",
        decision="APPROVED",
        note="Candidate ordering reviewed for validation planning.",
    )

    handoff = create_handoff(review, out_dir=tmp_path / "compound-handoff")

    payload = _assert_artifacts(handoff, expected_count=3)
    assert payload["candidate_set"]["kind"] == "COMPOUND_SCREENING"
    assert [item["candidate_id"] for item in payload["candidate_set"]["items"]] == [
        "synthetic-compound-alpha",
        "synthetic-compound-beta",
        "synthetic-compound-gamma",
    ]


def test_candidate_scan_reports_non_object_with_path_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    path = (
        tmp_path
        / "store"
        / "studies"
        / f"{study.study_id}.diagnostic-candidate-sets.json"
    )
    path.write_text(json.dumps([None]), encoding="utf-8")
    candidate_set = CandidateSet(
        set_id="",
        workflow_ref="muni_workflow_run_integrity",
        kind=WorkflowKind.DIAGNOSTIC_DISCOVERY,
        items=(),
        count=0,
    )

    with pytest.raises(
        PersistenceIntegrityError,
        match=rf"{study.study_id}.*index 0",
    ):
        record_review(
            candidate_set,
            reviewer="synthetic-integrity-reviewer",
            decision=ReviewDecision.APPROVED,
            note="Integrity probe.",
        )


def test_review_scan_reports_non_object_with_path_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    candidate_set = run_diagnostic_discovery(study)
    review = record_review(
        candidate_set,
        reviewer="synthetic-integrity-reviewer",
        decision=ReviewDecision.APPROVED,
        note="Integrity probe.",
    )
    path = tmp_path / "store" / "studies" / f"{study.study_id}.reviews.json"
    path.write_text(json.dumps([None]), encoding="utf-8")

    with pytest.raises(
        PersistenceIntegrityError,
        match=rf"{study.study_id}.*index 0",
    ):
        create_handoff(review, out_dir=tmp_path / "integrity-handoff")


def test_unpersisted_review_is_explicitly_refused_without_partial_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    candidate_set = run_diagnostic_discovery(study)
    unpersisted = ReviewRecord(
        review_id="",
        candidate_set_ref=candidate_set.set_id,
        reviewer="synthetic-researcher-gamma",
        decision=ReviewDecision.APPROVED,
        note="Synthetic unpersisted review.",
        decided_at="2026-08-02T00:00:00.000000Z",
    )
    out_dir = tmp_path / "unreviewed-handoff"

    with pytest.raises(HandoffError, match="no persisted review exists for CandidateSet"):
        create_handoff(unpersisted, out_dir=out_dir)

    assert not out_dir.exists() or tuple(out_dir.iterdir()) == ()


@pytest.mark.parametrize("decision", [ReviewDecision.REJECTED, ReviewDecision.NEEDS_MORE])
def test_nonapproved_review_is_explicitly_refused(
    decision: ReviewDecision, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    candidate_set = run_diagnostic_discovery(study)
    review = record_review(
        candidate_set,
        reviewer="synthetic-researcher-delta",
        decision=decision,
        note="Additional assessment recorded.",
    )
    out_dir = tmp_path / decision.value.lower()

    with pytest.raises(HandoffError, match=rf"review decision is {decision.value}"):
        create_handoff(review, out_dir=out_dir)

    assert not out_dir.exists() or tuple(out_dir.iterdir()) == ()


def _persist_deficient_candidate_set(
    root: Path, *, include_provenance: bool
) -> tuple[CandidateSet, ReviewRecord]:
    study = create_study(
        "synthetic-host-alpha",
        "synthetic-agent-omega",
        "synthetic simulation assessment",
    )
    save_study(study, root=root)
    candidate_set = CandidateSet(
        set_id="",
        workflow_ref="muni_workflow_run_missing-lineage",
        kind=WorkflowKind.DIAGNOSTIC_DISCOVERY,
        items=(
            {
                "candidate_id": "synthetic-marker-alpha",
                "disposition": "RANKED",
                "composite_score_ppm": 500_000,
                "reasons": [],
                "required_next_evidence": [],
            },
        ),
        count=1,
    )
    path = root / "studies" / f"{study.study_id}.diagnostic-candidate-sets.json"
    path.write_text(json.dumps([candidate_set.to_payload()]), encoding="utf-8")
    if include_provenance:
        collected = CollectedData(
            job_ref="muni_collection_job_synthetic",
            source_record_ref="synthetic-record-alpha",
            digest="sha256:" + "a" * 64,
        )
        data_path = root / "studies" / f"{study.study_id}.collected-data.json"
        data_path.write_text(json.dumps([collected.to_payload()]), encoding="utf-8")
    review = record_review(
        candidate_set,
        reviewer="synthetic-researcher-epsilon",
        decision=ReviewDecision.APPROVED,
        note="Deficient fixture review.",
    )
    return candidate_set, review


def test_missing_provenance_is_explicitly_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    monkeypatch.setenv("MUNI_DATA_ROOT", str(root))
    _, review = _persist_deficient_candidate_set(root, include_provenance=False)
    out_dir = tmp_path / "missing-provenance"

    with pytest.raises(HandoffError, match="required collected-data provenance is missing"):
        create_handoff(review, out_dir=out_dir)

    assert not out_dir.exists() or tuple(out_dir.iterdir()) == ()


def test_missing_lineage_is_explicitly_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    monkeypatch.setenv("MUNI_DATA_ROOT", str(root))
    _, review = _persist_deficient_candidate_set(root, include_provenance=True)
    out_dir = tmp_path / "missing-lineage"

    with pytest.raises(HandoffError, match="required execution lineage is missing"):
        create_handoff(review, out_dir=out_dir)

    assert not out_dir.exists() or tuple(out_dir.iterdir()) == ()
