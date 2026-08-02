from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from src.muni.collection import AdapterResult, collect_for_study
from src.muni.study import create_study
from src.muni.workflows.diagnostic import (
    load_diagnostic_workflow_records,
    run_diagnostic_discovery,
)
from src.muni.workflows.screening import (
    ScreeningWorkflowError,
    load_screening_workflow_records,
    run_compound_screening,
)
from src.muni_contracts import CandidateSet, WorkflowKind, WorkflowStatus

_WORKFLOW_DIRECTORY = Path(__file__).parents[1] / "src" / "muni" / "workflows"


def _collected_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path / "store"))
    study = create_study(
        "synthetic-host-independent",
        "synthetic-agent-independent",
        "synthetic-independence-study",
    )

    class Adapter:
        source = "synthetic-independent-source"
        license_decision = "ALLOWED"

        def __call__(self, _study):
            return AdapterResult(
                "synthetic-independent-record", b"synthetic-independent-payload"
            )

    collect_for_study(study, [Adapter()])
    return study


def _candidate(candidate_id: str, score: int) -> dict[str, object]:
    return {
        "id": candidate_id,
        "structure_like": f"SYNSTRUCT::{candidate_id}",
        "synthetic": True,
        "synthesizable": True,
        "objective_utilities_ppm": {
            "target_binding_activity": score,
            "detectability": score,
            "stability": score,
        },
        "constraint_metrics": {
            "metric.synthesizability_probability": "0.90",
            "metric.crop_phytotoxicity_risk": "0.05",
            "metric.soil_beneficial_microbe_risk": "0.05",
            "metric.handler_exposure_risk": "0.05",
        },
    }


def _candidate_pack(tmp_path: Path) -> Path:
    directory = tmp_path / "synthetic-independent-candidate-pack"
    directory.mkdir()
    payload = {
        "schema_version": "synthetic-screening-candidates.v1",
        "synthetic": True,
        "candidates": [
            _candidate("synthetic-candidate-alpha", 900_000),
            _candidate("synthetic-candidate-beta", 700_000),
        ],
    }
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    (directory / "candidates.json").write_bytes(raw)
    manifest = {
        "name": "synthetic-independent-library",
        "semver": "1.0.0",
        "schema_version": "1",
        "title": "Synthetic workflow-independence candidate library",
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


def _imported_modules(module_path: Path) -> set[str]:
    """Return imported module targets, including names in from-imports."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            if base:
                imported.add(base)
            imported.update(
                f"{base}.{alias.name}" if base else alias.name for alias in node.names
            )
    return imported


def test_diagnostic_completes_without_screening_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)

    candidate_set = run_diagnostic_discovery(study)

    assert isinstance(candidate_set, CandidateSet)
    assert candidate_set.kind is WorkflowKind.DIAGNOSTIC_DISCOVERY
    assert candidate_set.count > 0
    assert load_diagnostic_workflow_records(study)[-1].run.status is WorkflowStatus.SUCCEEDED
    assert load_screening_workflow_records(study) == ()


def test_screening_completes_without_diagnostic_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)
    source = _candidate_pack(tmp_path)

    candidate_set = run_compound_screening(
        study,
        purpose="contained-lab reagent",
        candidate_source=source,
    )

    assert isinstance(candidate_set, CandidateSet)
    assert candidate_set.kind is WorkflowKind.COMPOUND_SCREENING
    assert candidate_set.count == 2
    assert load_screening_workflow_records(study)[-1].run.status is WorkflowStatus.SUCCEEDED
    assert load_diagnostic_workflow_records(study) == ()


def test_screening_refusal_does_not_block_diagnostic_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = _collected_study(tmp_path, monkeypatch)

    with pytest.raises(ScreeningWorkflowError, match="candidate source"):
        run_compound_screening(
            study,
            purpose="contained-lab reagent",
            candidate_source=None,
        )

    assert load_screening_workflow_records(study) == ()
    candidate_set = run_diagnostic_discovery(study)
    assert candidate_set.kind is WorkflowKind.DIAGNOSTIC_DISCOVERY
    assert load_diagnostic_workflow_records(study)[-1].run.status is WorkflowStatus.SUCCEEDED
    assert load_screening_workflow_records(study) == ()


def test_public_contracts_require_no_sibling_workflow_output() -> None:
    cases = (
        (run_diagnostic_discovery, {"screening", "compound"}),
        (run_compound_screening, {"diagnostic", "discovery"}),
    )
    for entrypoint, sibling_terms in cases:
        signature = inspect.signature(entrypoint)
        required = {
            name: parameter
            for name, parameter in signature.parameters.items()
            if parameter.default is inspect.Parameter.empty
        }
        for name, parameter in required.items():
            contract = f"{name} {parameter.annotation}".replace("_", "").lower()
            assert "candidateset" not in contract
            assert "workflowrun" not in contract
            assert not any(term in contract for term in sibling_terms)


def test_workflow_modules_have_no_mutual_imports() -> None:
    diagnostic_imports = _imported_modules(_WORKFLOW_DIRECTORY / "diagnostic.py")
    screening_imports = _imported_modules(_WORKFLOW_DIRECTORY / "screening.py")

    assert "src.muni.workflows.screening" not in diagnostic_imports
    assert "src.muni.workflows.diagnostic" not in screening_imports
