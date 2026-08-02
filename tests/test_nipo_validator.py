from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Callable

import pytest

from src.muni.handoff import DISCLAIMER as PRODUCER_DISCLAIMER

ROOT = Path(__file__).parents[1]
VALIDATOR = ROOT / "handoff" / "nipo" / "validate_handoff.py"
FIXTURES = tuple((ROOT / "handoff" / "nipo" / "fixtures").glob("*.json"))
assert len(FIXTURES) == 1
FIXTURE = FIXTURES[0]

Mutation = Callable[[dict[str, object]], None]


def _run_validator(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _mutated_fixture(tmp_path: Path, mutation: Mutation) -> Path:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mutation(payload)
    path = tmp_path / "tampered-handoff.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _first_candidate(payload: dict[str, object]) -> dict[str, object]:
    candidate_set = payload["candidate_set"]
    assert isinstance(candidate_set, dict)
    items = candidate_set["items"]
    assert isinstance(items, list) and isinstance(items[0], dict)
    return items[0]


def _double_score(payload: dict[str, object]) -> None:
    candidate = _first_candidate(payload)
    score = candidate["composite_score_ppm"]
    assert isinstance(score, int)
    candidate["composite_score_ppm"] = score * 2


def _tamper_crop(payload: dict[str, object]) -> None:
    study = payload["study"]
    assert isinstance(study, dict)
    study["target_crop"] = "tampered-crop-z"


def _tamper_review_note(payload: dict[str, object]) -> None:
    review = payload["review"]
    assert isinstance(review, dict) and isinstance(review["note"], str)
    review["note"] += " TAMPERED"


def _tamper_candidate_content_with_hash_intact(payload: dict[str, object]) -> None:
    candidate = _first_candidate(payload)
    candidate_content = candidate["candidate_content"]
    assert isinstance(candidate_content, dict)
    assert isinstance(candidate_content["disposition"], str)
    candidate_content["disposition"] += "-TAMPERED"


def _collected_data(payload: dict[str, object]) -> dict[str, object]:
    provenance = payload["provenance"]
    assert isinstance(provenance, dict)
    collected = provenance["collected_data"]
    assert isinstance(collected, list) and isinstance(collected[0], dict)
    return collected[0]


def _workflow_lineage(payload: dict[str, object]) -> dict[str, object]:
    lineage = payload["lineage"]
    assert isinstance(lineage, dict)
    workflow = lineage["workflow"]
    assert isinstance(workflow, dict)
    return workflow


def _tamper_provenance_digest(payload: dict[str, object]) -> None:
    _collected_data(payload)["digest"] = "sha256:" + "0" * 64


def _tamper_source_record_ref(payload: dict[str, object]) -> None:
    _collected_data(payload)["source_record_ref"] = "forged-source-record"


def _tamper_tool_identity(payload: dict[str, object]) -> None:
    _workflow_lineage(payload)["tool_identity"] = "forged-tool"


def _tamper_workflow_parameters(payload: dict[str, object]) -> None:
    _workflow_lineage(payload)["parameters"] = {"forged": True}


def _validator_algorithms() -> ModuleType:
    """Load the standalone validator the way a document holder could."""
    spec = importlib.util.spec_from_file_location("nipo_validate_handoff", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recompute_candidate_content_hash(
    module: ModuleType, candidate: dict[str, object]
) -> None:
    candidate["candidate_content_hash"] = module.digest(candidate["candidate_content"])


def _recompute_boundary_identity(module: ModuleType, payload: dict[str, object]) -> None:
    """Recompute the boundary CandidateSet/Review IDs after an items mutation."""
    candidate_set = payload["candidate_set"]
    boundary = payload["boundary"]
    review = payload["review"]
    assert isinstance(candidate_set, dict)
    assert isinstance(boundary, dict)
    assert isinstance(review, dict)
    boundary["candidate_set_id"] = module.deterministic_id(
        "muni_candidate_set",
        {
            name: candidate_set[name]
            for name in ("workflow_ref", "kind", "items", "count")
        },
    )
    boundary["review_id"] = module.deterministic_id(
        "muni_review",
        {
            "candidate_set_ref": boundary["candidate_set_id"],
            **{
                name: review[name]
                for name in ("reviewer", "decision", "note", "decided_at")
            },
        },
    )


def _recompute_evidence_and_handoff(module: ModuleType, payload: dict[str, object]) -> None:
    """Recompute the evidence digest and handoff ID after an evidence mutation."""
    boundary = payload["boundary"]
    handoff = payload["handoff"]
    assert isinstance(boundary, dict)
    assert isinstance(handoff, dict)
    evidence = module.digest(
        {"provenance": payload["provenance"], "lineage": payload["lineage"]}
    )
    boundary["evidence_digest"] = evidence
    handoff["evidence_digest"] = evidence
    handoff["handoff_id"] = module.deterministic_id(
        "muni_wet_lab_handoff",
        {
            name: handoff[name]
            for name in ("review_ref", "artifact_paths", "disclaimer", "evidence_digest")
        },
    )


@pytest.mark.parametrize(
    ("mutation", "expected_field"),
    [
        (_double_score, "$.boundary.candidate_set_id"),
        (_tamper_crop, "$.study.study_id"),
        (_tamper_review_note, "$.boundary.review_id"),
        (
            _tamper_candidate_content_with_hash_intact,
            "$.candidate_set.items[0].candidate_content_hash",
        ),
    ],
    ids=["score", "target-crop", "review-note", "candidate-content"],
)
def test_validator_rejects_content_tampering(
    tmp_path: Path, mutation: Mutation, expected_field: str
) -> None:
    result = _run_validator(_mutated_fixture(tmp_path, mutation))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert expected_field in result.stdout


@pytest.mark.parametrize(
    ("field", "expected_path"),
    [
        ("review_ref", "$.handoff.review_ref"),
        ("candidate_set_ref", "$.handoff.candidate_set_ref"),
    ],
)
def test_validator_rejects_persisted_linkage_mismatch(
    tmp_path: Path, field: str, expected_path: str
) -> None:
    def mutate_linkage(payload: dict[str, object]) -> None:
        handoff = payload["handoff"]
        assert isinstance(handoff, dict)
        prefix = "muni_review_" if field == "review_ref" else "muni_candidate_set_"
        handoff[field] = prefix + "0" * 32

    result = _run_validator(_mutated_fixture(tmp_path, mutate_linkage))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert expected_path in result.stdout


@pytest.mark.parametrize(
    "mutation",
    [
        _tamper_provenance_digest,
        _tamper_source_record_ref,
        _tamper_tool_identity,
        _tamper_workflow_parameters,
    ],
    ids=[
        "provenance-digest",
        "source-record-ref",
        "tool-identity",
        "workflow-parameters",
    ],
)
def test_validator_rejects_evidence_chain_tampering(
    tmp_path: Path, mutation: Mutation
) -> None:
    result = _run_validator(_mutated_fixture(tmp_path, mutation))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert "$.boundary.evidence_digest" in result.stdout
    assert "expected sha256:" in result.stdout
    assert "actual sha256:" in result.stdout


def test_validator_rejects_recomputed_evidence_digest_with_stale_handoff_id(
    tmp_path: Path,
) -> None:
    def rewrite_evidence_digest(payload: dict[str, object]) -> None:
        _tamper_tool_identity(payload)
        evidence = {
            "provenance": payload["provenance"],
            "lineage": payload["lineage"],
        }
        canonical = json.dumps(
            evidence, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        rewritten = "sha256:" + hashlib.sha256(canonical).hexdigest()
        boundary = payload["boundary"]
        handoff = payload["handoff"]
        assert isinstance(boundary, dict) and isinstance(handoff, dict)
        boundary["evidence_digest"] = rewritten
        handoff["evidence_digest"] = rewritten

    result = _run_validator(_mutated_fixture(tmp_path, rewrite_evidence_digest))

    assert result.returncode != 0, result.stdout + result.stderr
    assert "$.handoff.handoff_id" in result.stdout
    assert "expected muni_wet_lab_handoff_" in result.stdout
    assert "actual muni_wet_lab_handoff_" in result.stdout


def test_validator_fails_closed_when_evidence_material_is_missing(
    tmp_path: Path,
) -> None:
    def strip_evidence_material(payload: dict[str, object]) -> None:
        payload.pop("provenance")

    result = _run_validator(_mutated_fixture(tmp_path, strip_evidence_material))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert "$.boundary.evidence_digest" in result.stdout
    assert "cannot verify evidence digest" in result.stdout


def test_validator_fails_closed_when_identity_material_is_missing(
    tmp_path: Path,
) -> None:
    def strip_identity_material(payload: dict[str, object]) -> None:
        study = payload["study"]
        candidate = _first_candidate(payload)
        assert isinstance(study, dict)
        study.pop("created_at")
        study.pop("pack_ref")
        candidate.pop("candidate_content")

    result = _run_validator(_mutated_fixture(tmp_path, strip_identity_material))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert "cannot verify identity" in result.stdout
    assert "$.study.study_id" in result.stdout
    assert "$.candidate_set.items[0].candidate_content_hash" in result.stdout


def test_validator_accepts_pristine_fixture() -> None:
    result = _run_validator(FIXTURE)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == f"VALID {FIXTURE}\n"
    assert result.stderr == ""


def test_disclaimer_constant_does_not_drift() -> None:
    spec = importlib.util.spec_from_file_location("nipo_validate_handoff", VALIDATOR)
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)

    assert validator.DISCLAIMER == PRODUCER_DISCLAIMER


def test_validator_rejects_outer_inner_candidate_identity_contradiction(
    tmp_path: Path,
) -> None:
    """Finding A: the outer candidate_id must name the hashed content's subject."""
    module = _validator_algorithms()
    fixture_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    content_value = _first_candidate(fixture_payload)["candidate_content"]
    assert isinstance(content_value, dict)
    hashed_candidate_id = content_value["candidate_id"]

    def detach_outer_identity(payload: dict[str, object]) -> None:
        candidate = _first_candidate(payload)
        candidate["candidate_id"] = "different-external-subject"
        _recompute_boundary_identity(module, payload)

    result = _run_validator(_mutated_fixture(tmp_path, detach_outer_identity))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert "$.candidate_set.items[0].candidate_id" in result.stdout
    assert "different-external-subject" in result.stdout
    assert str(hashed_candidate_id) in result.stdout


def test_validator_rejects_candidate_content_field_dropped_from_outer_mirror(
    tmp_path: Path,
) -> None:
    """Finding A: removing an outer mirror field while content keeps it is bound."""
    module = _validator_algorithms()

    def drop_outer_mirror(payload: dict[str, object]) -> None:
        candidate = _first_candidate(payload)
        assert "rank" in candidate
        del candidate["rank"]
        _recompute_boundary_identity(module, payload)

    result = _run_validator(_mutated_fixture(tmp_path, drop_outer_mirror))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert "$.candidate_set.items[0].rank" in result.stdout
    assert "mirror" in result.stdout


def test_validator_rejects_outer_candidate_field_not_in_hashed_content(
    tmp_path: Path,
) -> None:
    """Finding A: an outer-only candidate field is not a mirror and not declared."""
    module = _validator_algorithms()

    def inject_outer_only(payload: dict[str, object]) -> None:
        _first_candidate(payload)["unbound_outer_field"] = "injected"
        _recompute_boundary_identity(module, payload)

    result = _run_validator(_mutated_fixture(tmp_path, inject_outer_only))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert "$.candidate_set.items[0].unbound_outer_field" in result.stdout


def test_validator_rejects_derived_projection_desync(tmp_path: Path) -> None:
    """Finding A: outer rationale must equal the projection of hashed content."""
    module = _validator_algorithms()

    def desync_rationale(payload: dict[str, object]) -> None:
        candidate = _first_candidate(payload)
        rationale = candidate["rationale"]
        assert isinstance(rationale, dict)
        rationale["reasons"] = ["forged-outer-reason"]
        _recompute_boundary_identity(module, payload)

    result = _run_validator(_mutated_fixture(tmp_path, desync_rationale))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert "$.candidate_set.items[0].rationale" in result.stdout


@pytest.mark.parametrize(
    "block",
    ["study", "review", "handoff", "boundary", "persisted", "candidate_set"],
)
def test_validator_rejects_undeclared_nested_field(tmp_path: Path, block: str) -> None:
    """Finding C: contract-defined blocks are closed; version bumps extend them."""

    def inject_undeclared(payload: dict[str, object]) -> None:
        target = payload[block]
        assert isinstance(target, dict)
        target["undeclared_field"] = "injected"

    result = _run_validator(_mutated_fixture(tmp_path, inject_undeclared))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert f"$.{block}.undeclared_field" in result.stdout
    assert "not declared" in result.stdout


def _inject_rationale(payload: dict[str, object]) -> None:
    rationale = _first_candidate(payload)["rationale"]
    assert isinstance(rationale, dict)
    rationale["undeclared_field"] = True


def _inject_uncertainty(payload: dict[str, object]) -> None:
    uncertainty = _first_candidate(payload)["uncertainty"]
    assert isinstance(uncertainty, dict)
    uncertainty["undeclared_field"] = True


def _workflow_run(payload: dict[str, object]) -> dict[str, object]:
    run = _workflow_lineage(payload)["run"]
    assert isinstance(run, dict)
    return run


def _inject_workflow_run(payload: dict[str, object]) -> None:
    _workflow_run(payload)["undeclared_field"] = True


def _inject_collected_data_entry(payload: dict[str, object]) -> None:
    _collected_data(payload)["undeclared_field"] = True


def _inject_adapter_entry(payload: dict[str, object]) -> None:
    lineage = payload["lineage"]
    assert isinstance(lineage, dict)
    adapters = lineage["collection_adapters"]
    assert isinstance(adapters, list) and isinstance(adapters[0], dict)
    adapters[0]["undeclared_field"] = True


def _inject_workflow(payload: dict[str, object]) -> None:
    _workflow_lineage(payload)["undeclared_field"] = True


def _inject_provenance(payload: dict[str, object]) -> None:
    provenance = payload["provenance"]
    assert isinstance(provenance, dict)
    provenance["undeclared_field"] = True


def _inject_lineage(payload: dict[str, object]) -> None:
    lineage = payload["lineage"]
    assert isinstance(lineage, dict)
    lineage["undeclared_field"] = True


@pytest.mark.parametrize(
    ("mutation", "recompute", "expected_path"),
    [
        (
            _inject_rationale,
            "boundary",
            "$.candidate_set.items[0].rationale.undeclared_field",
        ),
        (
            _inject_uncertainty,
            "boundary",
            "$.candidate_set.items[0].uncertainty.undeclared_field",
        ),
        (
            _inject_workflow_run,
            "evidence",
            "$.lineage.workflow.run.undeclared_field",
        ),
        (
            _inject_collected_data_entry,
            "evidence",
            "$.provenance.collected_data[0].undeclared_field",
        ),
        (
            _inject_adapter_entry,
            "evidence",
            "$.lineage.collection_adapters[0].undeclared_field",
        ),
        (_inject_workflow, "evidence", "$.lineage.workflow.undeclared_field"),
        (_inject_provenance, "evidence", "$.provenance.undeclared_field"),
        (_inject_lineage, "evidence", "$.lineage.undeclared_field"),
    ],
    ids=[
        "rationale",
        "uncertainty",
        "workflow-run",
        "collected-data-entry",
        "adapter-entry",
        "workflow",
        "provenance",
        "lineage",
    ],
)
def test_validator_rejects_undeclared_field_in_hashed_blocks(
    tmp_path: Path,
    mutation: Mutation,
    recompute: str,
    expected_path: str,
) -> None:
    """Finding C: closed blocks stay rejected even with a self-consistent rehash."""
    module = _validator_algorithms()

    def inject_and_recompute(payload: dict[str, object]) -> None:
        mutation(payload)
        if recompute == "boundary":
            _recompute_boundary_identity(module, payload)
        else:
            _recompute_evidence_and_handoff(module, payload)

    result = _run_validator(_mutated_fixture(tmp_path, inject_and_recompute))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert expected_path in result.stdout
    assert "not declared" in result.stdout


def test_validator_accepts_mirrored_workflow_attribute(tmp_path: Path) -> None:
    """Control: declared-optional workflow attributes stay accepted when mirrored."""
    module = _validator_algorithms()

    def add_mirrored_attribute(payload: dict[str, object]) -> None:
        candidate = _first_candidate(payload)
        content = candidate["candidate_content"]
        assert isinstance(content, dict)
        attribute = {"nested": ["preserved-by-workflow", 2]}
        content["extra_workflow_attribute"] = attribute
        candidate["extra_workflow_attribute"] = attribute
        _recompute_candidate_content_hash(module, candidate)
        _recompute_boundary_identity(module, payload)

    result = _run_validator(_mutated_fixture(tmp_path, add_mirrored_attribute))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("VALID ")


@pytest.mark.parametrize(
    ("mutation", "recompute"),
    [
        ("parameters", "evidence"),
        ("top_level", "none"),
    ],
    ids=["workflow-parameters", "top-level"],
)
def test_validator_keeps_documented_open_blocks_open(
    tmp_path: Path, mutation: str, recompute: str
) -> None:
    """Control: workflow.parameters and the top level stay open by contract."""
    module = _validator_algorithms()

    def inject_into_open_block(payload: dict[str, object]) -> None:
        if mutation == "parameters":
            parameters = _workflow_lineage(payload)["parameters"]
            assert isinstance(parameters, dict)
            parameters["caller_provided_parameter"] = "value"
        else:
            payload["receiver_note"] = "outside every digest by contract"
        if recompute == "evidence":
            _recompute_evidence_and_handoff(module, payload)

    result = _run_validator(_mutated_fixture(tmp_path, inject_into_open_block))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("VALID ")


def test_validator_rejects_reversed_workflow_chronology(tmp_path: Path) -> None:
    """Finding D: finished_at must not precede started_at, even when rehashed."""
    module = _validator_algorithms()

    def reverse_chronology(payload: dict[str, object]) -> None:
        run = _workflow_run(payload)
        run["started_at"], run["finished_at"] = run["finished_at"], run["started_at"]
        _recompute_evidence_and_handoff(module, payload)

    result = _run_validator(_mutated_fixture(tmp_path, reverse_chronology))

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.startswith("INVALID ")
    assert "$.lineage.workflow.run.finished_at" in result.stdout
