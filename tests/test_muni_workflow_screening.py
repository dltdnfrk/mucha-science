from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from src.muni import PersistenceIntegrityError
from src.muni.collection import AdapterResult, collect_for_study
from src.muni.study import create_study
from src.muni.workflows.screening import (
    ScreeningWorkflowError,
    load_screening_workflow_records,
    run_compound_screening,
)
from src.muni_contracts import WorkflowKind, WorkflowStatus
from src.objectives import ObjectiveValidationError, PLATFORM_CONSTRAINT_IDS
from src.platform_contracts import Constraint


def _collected_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path / "store"))
    study = create_study("synthetic-host-alpha", "synthetic-agent-omega", "synthetic-study")

    class Adapter:
        source = "synthetic-source"
        license_decision = "ALLOWED"

        def __call__(self, _study):
            return AdapterResult("synthetic-record", b"synthetic-collected-payload")

    collect_for_study(study, [Adapter()])
    return study


def _candidate(
    candidate_id: str,
    score: int,
    *,
    synthesizable: bool = True,
    safety: bool = True,
) -> dict[str, object]:
    risk = "0.05" if safety else "0.50"
    return {
        "id": candidate_id,
        "structure_like": f"SYNSTRUCT::{candidate_id}",
        "synthetic": True,
        "synthesizable": synthesizable,
        "objective_utilities_ppm": {
            "inhibition_kill": score,
            "non_target_avoidance": score,
            "stability": score,
            "surface_adhesion_persistence": score,
            "detectability": score,
        },
        "constraint_metrics": {
            "metric.synthesizability_probability": "0.90" if synthesizable else "0.10",
            "metric.crop_phytotoxicity_risk": risk,
            "metric.soil_beneficial_microbe_risk": risk,
            "metric.handler_exposure_risk": risk,
        },
    }


def _pack(tmp_path: Path, candidates: list[dict[str, object]]) -> Path:
    directory = tmp_path / "synthetic-candidate-pack"
    directory.mkdir()
    payload = {
        "schema_version": "synthetic-screening-candidates.v1",
        "synthetic": True,
        "candidates": candidates,
    }
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    (directory / "candidates.json").write_bytes(raw)
    manifest = {
        "name": "synthetic-screening-library",
        "semver": "1.0.0",
        "schema_version": "1",
        "title": "Synthetic screening candidate library",
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


def test_screening_returns_multiple_compounds_and_preserves_dispositions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    source = _pack(
        tmp_path,
        [
            _candidate("synthetic-compound-high", 900_000),
            _candidate("synthetic-compound-mid", 700_000),
            _candidate("synthetic-compound-low", 400_000),
            _candidate("synthetic-compound-unsynth", 990_000, synthesizable=False),
        ],
    )

    candidate_set = run_compound_screening(
        study,
        purpose="fungicide/control agent",
        candidate_source=source,
    )

    assert candidate_set.kind is WorkflowKind.COMPOUND_SCREENING
    assert candidate_set.count >= 2
    assert [item["candidate_id"] for item in candidate_set.items[:2]] == [
        "synthetic-compound-high",
        "synthetic-compound-mid",
    ]
    records = load_screening_workflow_records(study)
    assert [record.run.status for record in records] == [
        WorkflowStatus.PENDING,
        WorkflowStatus.RUNNING,
        WorkflowStatus.SUCCEEDED,
    ]
    final = records[-1]
    assert final.run.kind is WorkflowKind.COMPOUND_SCREENING
    assert [item["candidate_id"] for item in final.excluded] == [
        "synthetic-compound-unsynth"
    ]
    assert final.abstained == ()
    assert candidate_set.workflow_ref == final.run.run_id


def test_coating_purpose_injects_all_environmental_safety_constraints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    source = _pack(
        tmp_path,
        [_candidate("synthetic-compound-a", 800_000), _candidate("synthetic-compound-b", 700_000)],
    )

    run_compound_screening(study, purpose="crop coating agent", candidate_source=source)

    ids = {item["constraint_id"] for item in load_screening_workflow_records(study)[-1].resolved_constraints}
    assert {
        PLATFORM_CONSTRAINT_IDS["crop_phytotoxicity"],
        PLATFORM_CONSTRAINT_IDS["soil_beneficial_microbe"],
        PLATFORM_CONSTRAINT_IDS["handler_exposure"],
    } <= ids


def test_platform_safety_constraint_cannot_be_removed_or_weakened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    source = _pack(tmp_path, [_candidate("synthetic-compound-a", 800_000)])

    with pytest.raises(ObjectiveValidationError, match="cannot be removed"):
        run_compound_screening(
            study,
            purpose="crop coating agent",
            candidate_source=source,
            removed_constraint_ids=(PLATFORM_CONSTRAINT_IDS["handler_exposure"],),
        )

    weaker = Constraint.from_content(
        {
            "constraint_id": "synthetic-user-weaker-handler-limit",
            "owner": "USER",
            "metric_ref": "metric.handler_exposure_risk",
            "operator": "LTE",
            "threshold": {"value": "0.40", "unit": "probability"},
            "policy_ref": None,
        }
    )
    with pytest.raises(ObjectiveValidationError, match="at least as strict"):
        run_compound_screening(
            study,
            purpose="crop coating agent",
            candidate_source=source,
            user_constraints=(weaker,),
        )


def test_non_synthesizable_candidate_is_excluded_with_policy_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    source = _pack(
        tmp_path,
        [
            _candidate("synthetic-compound-a", 800_000),
            _candidate("synthetic-compound-b", 700_000),
            _candidate("synthetic-compound-unsynth", 999_000, synthesizable=False),
        ],
    )

    run_compound_screening(study, purpose="molecular-diagnostic reagent", candidate_source=source)

    [excluded] = load_screening_workflow_records(study)[-1].excluded
    assert excluded["candidate_id"] == "synthetic-compound-unsynth"
    assert excluded["reasons"] == [
        f'HARD_CONSTRAINT_FAILED:{PLATFORM_CONSTRAINT_IDS["synthesizability"]}'
    ]


def test_refuses_missing_data_or_candidate_source_before_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path / "store"))
    study = create_study("synthetic-host-beta", "synthetic-agent-sigma", "synthetic-study")
    source = _pack(tmp_path, [_candidate("synthetic-compound-a", 800_000)])

    with pytest.raises(ScreeningWorkflowError, match="no collected data"):
        run_compound_screening(study, purpose="fungicide/control agent", candidate_source=source)
    with pytest.raises(ScreeningWorkflowError, match="candidate source"):
        run_compound_screening(study, purpose="fungicide/control agent", candidate_source=None)
    assert load_screening_workflow_records(study) == ()


def test_loader_reports_non_object_record_with_path_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    root = tmp_path / "store"
    path = root / "studies" / f"{study.study_id}.screening-workflow-runs.json"
    path.write_text(json.dumps([{"invalid": True}, None]), encoding="utf-8")

    with pytest.raises(
        PersistenceIntegrityError,
        match=rf"{study.study_id}.*index 1",
    ):
        load_screening_workflow_records(study)


def test_screening_module_has_no_diagnostic_dependency() -> None:
    module_path = Path("src/muni/workflows/screening.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
    assert not any("diagnostic" in name for name in imported)
