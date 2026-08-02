from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.muni import PersistenceIntegrityError
from src.muni.collection import AdapterResult, collect_for_study
from src.muni.study import create_study
from src.muni.workflows.diagnostic import (
    DiagnosticDiscoveryError,
    load_diagnostic_workflow_records,
    run_diagnostic_discovery,
)
from src.muni_contracts import Study, WorkflowKind, WorkflowStatus
from src.objectives import (
    OBJECTIVE_REGISTRY,
    CandidateInput,
    create_query_revision,
    resolve_constraints,
)
from src.platform_contracts import ApplicationType, ConstraintOutcome, ObjectiveTerm


def _term(objective_id: str, weight: int) -> ObjectiveTerm:
    return ObjectiveTerm.from_content(
        {
            "term_id": objective_id,
            "objective_ref": OBJECTIVE_REGISTRY[objective_id].objective_ref,
            "weight_units": weight,
            "parameters": {},
        }
    )


def _objectives() -> tuple[ObjectiveTerm, ...]:
    return (_term("detectability", 600_000), _term("non_target_avoidance", 400_000))


def _candidate(
    candidate_id: str,
    detectability: int,
    selectivity: int,
    constraint: ConstraintOutcome,
) -> CandidateInput:
    revision = create_query_revision(
        query_id="diagnostic-fixture",
        application_type=ApplicationType.CONTAINED_LAB,
        objectives=_objectives(),
        user_constraints=(),
        actor="synthetic-scientist",
        created_at="2026-08-02T00:00:00.000000Z",
    )
    constraint_id = resolve_constraints(revision)[0].constraint_id
    return CandidateInput(
        candidate_id,
        {"marker_ref": f"marker-{candidate_id}"},
        {
            "detectability": detectability,
            "non_target_avoidance": selectivity,
        },
        {constraint_id: constraint},
    )


def _collected_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropA", "pathogenX", "diagnosticPurpose")

    class Adapter:
        source = "synthetic-source"
        license_decision = "ALLOWED"

        def __call__(self, _study):
            return AdapterResult("synthetic-record", b"synthetic-payload")

    collect_for_study(study, [Adapter()])
    return study


def test_discovery_returns_diagnostic_set_and_persists_three_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    candidates = (
        _candidate("candidate-low", 500_000, 600_000, ConstraintOutcome.PASS),
        _candidate("candidate-high", 900_000, 800_000, ConstraintOutcome.PASS),
        _candidate("candidate-excluded", 990_000, 990_000, ConstraintOutcome.FAIL),
        _candidate("candidate-abstained", 990_000, 990_000, ConstraintOutcome.UNKNOWN),
    )

    candidate_set = run_diagnostic_discovery(
        study, objectives=_objectives(), candidates=candidates
    )

    assert candidate_set.kind is WorkflowKind.DIAGNOSTIC_DISCOVERY
    assert [item["candidate_id"] for item in candidate_set.items] == [
        "candidate-high",
        "candidate-low",
    ]
    records = load_diagnostic_workflow_records(study)
    assert [record.run.status for record in records] == [
        WorkflowStatus.PENDING,
        WorkflowStatus.RUNNING,
        WorkflowStatus.SUCCEEDED,
    ]
    final = records[-1]
    assert [item["candidate_id"] for item in final.ranked] == [
        "candidate-high",
        "candidate-low",
    ]
    assert [item["candidate_id"] for item in final.excluded] == ["candidate-excluded"]
    assert [item["candidate_id"] for item in final.abstained] == ["candidate-abstained"]
    assert candidate_set.workflow_ref == final.run.run_id


def test_run_timestamps_come_from_invocation_not_study_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = Study.from_content(
        {
            "target_crop": "crop-old",
            "target_pathogen": "pathogen-old",
            "purpose": "diagnosticPurpose",
            "created_at": "2001-01-01T00:00:00.000000Z",
            "pack_ref": None,
        }
    )

    class Adapter:
        source = "synthetic-source"
        license_decision = "ALLOWED"

        def __call__(self, _study):
            return AdapterResult("synthetic-record", b"synthetic-payload")

    collect_for_study(study, [Adapter()])
    run_diagnostic_discovery(study)

    records = load_diagnostic_workflow_records(study)
    started_at = records[0].run.started_at
    assert started_at != study.created_at
    assert {record.run.started_at for record in records} == {started_at}
    assert records[-1].run.finished_at is not None
    assert records[-1].run.finished_at >= started_at


def test_no_collected_data_refuses_without_run_or_candidate_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropB", "pathogenY", "diagnosticPurpose")

    with pytest.raises(DiagnosticDiscoveryError, match="no collected data"):
        run_diagnostic_discovery(study)

    assert load_diagnostic_workflow_records(study) == ()
    study_files = tuple((tmp_path / "studies").glob(f"{study.study_id}*"))
    assert all("candidate-set" not in path.name for path in study_files)


def test_loader_reports_non_object_record_with_path_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    path = tmp_path / "studies" / f"{study.study_id}.diagnostic-workflow-runs.json"
    path.write_text(json.dumps([None]), encoding="utf-8")

    with pytest.raises(
        PersistenceIntegrityError,
        match=rf"{study.study_id}.*index 0",
    ):
        load_diagnostic_workflow_records(study)


def test_diagnostic_module_has_no_screening_dependency() -> None:
    module_path = Path("src/muni/workflows/diagnostic.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
    assert not any("screening" in name for name in imported)


def test_same_inputs_keep_deterministic_ranking_order_across_invocations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    candidates = (
        _candidate("candidate-b", 800_000, 800_000, ConstraintOutcome.PASS),
        _candidate("candidate-a", 800_000, 800_000, ConstraintOutcome.PASS),
    )

    first = run_diagnostic_discovery(study, objectives=_objectives(), candidates=candidates)
    second = run_diagnostic_discovery(study, objectives=_objectives(), candidates=candidates)

    assert [item["candidate_id"] for item in first.items] == [
        item["candidate_id"] for item in second.items
    ]
    assert [item["composite_score_ppm"] for item in first.items] == [
        item["composite_score_ppm"] for item in second.items
    ]
