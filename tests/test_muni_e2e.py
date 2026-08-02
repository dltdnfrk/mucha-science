from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

from src.muni.handoff import DISCLAIMER
from src.objectives import PLATFORM_CONSTRAINT_IDS

SCRIPT = Path("scripts/muni_study_e2e.py")


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_muni_study_e2e_publishes_complete_disclaimer_bearing_proof(
    tmp_path: Path,
) -> None:
    output = tmp_path / "e2e-output"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(output)],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "MUNI E2E SUCCESS" in result.stdout

    expected = {
        "study-record.json",
        "collection-job-table.json",
        "candidate-sets.json",
        "review-records.json",
        "wet-lab-handoffs.json",
        "provenance-audit.json",
        "provenance-audit.md",
    }
    assert expected <= {path.name for path in output.iterdir()}

    [study] = _json(output / "study-record.json")["records"]
    assert study["target_crop"] == "synthetic-target-crop-a"
    assert study["target_pathogen"] == "synthetic-target-pathogen-x"

    job_table = _json(output / "collection-job-table.json")["records"]
    assert job_table["parallel"] is True
    statuses = {row["status"] for row in job_table["rows"]}
    assert {"SUCCEEDED", "SKIPPED"} <= statuses
    skipped = [row for row in job_table["rows"] if row["status"] == "SKIPPED"]
    assert skipped and "DEFERRED" in skipped[-1]["reason"]

    candidate_sets = _json(output / "candidate-sets.json")["records"]
    assert len(candidate_sets) == 2
    assert {item["kind"] for item in candidate_sets} == {
        "DIAGNOSTIC_DISCOVERY",
        "COMPOUND_SCREENING",
    }
    assert all(item["count"] > 0 for item in candidate_sets)

    reviews = _json(output / "review-records.json")["records"]
    assert len(reviews) == 2
    assert all(item["decision"] == "APPROVED" for item in reviews)

    handoffs = _json(output / "wet-lab-handoffs.json")["records"]
    assert len(handoffs) == 2
    for handoff in handoffs:
        assert handoff["disclaimer"] == DISCLAIMER
        assert len(handoff["artifact_paths"]) == 2
        for artifact_name in handoff["artifact_paths"]:
            artifact = Path(artifact_name)
            assert artifact.is_file()
            assert DISCLAIMER in artifact.read_text(encoding="utf-8")

    audit = _json(output / "provenance-audit.json")
    assert audit["disclaimer"] == DISCLAIMER
    assert len(audit["candidate_traces"]) == sum(
        item["count"] for item in candidate_sets
    )
    for trace in audit["candidate_traces"]:
        assert trace["study_identity"]["study_id"] == study["study_id"]
        assert trace["collection_trace"]
        for collected in trace["collection_trace"]:
            assert collected["collection_job_ref"]
            assert collected["source_ref"]
            assert collected["source_record_ref"]
            assert collected["digest"].startswith("sha256:")
            assert collected["execution_lineage"]["adapter_identity"]
            assert collected["execution_lineage"]["parameters"]
        assert trace["execution_lineage"]["tool_identity"]
        assert trace["execution_lineage"]["parameters"]
        assert "seed" in trace["execution_lineage"]

    assert {
        PLATFORM_CONSTRAINT_IDS["synthesizability"],
        PLATFORM_CONSTRAINT_IDS["crop_phytotoxicity"],
        PLATFORM_CONSTRAINT_IDS["soil_beneficial_microbe"],
        PLATFORM_CONSTRAINT_IDS["handler_exposure"],
    } <= set(audit["screening_constraint_ids"])

    for artifact in output.rglob("*.json"):
        assert DISCLAIMER in artifact.read_text(encoding="utf-8")
    for artifact in output.rglob("*.md"):
        assert DISCLAIMER in artifact.read_text(encoding="utf-8")


def test_workflow_entrypoints_are_invoked_in_separate_functions() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    entrypoints = {"run_diagnostic_discovery", "run_compound_screening"}
    calls_by_function: dict[str, set[str]] = {}
    call_statements: dict[str, set[int]] = {name: set() for name in entrypoints}

    for function in (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        direct_calls = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in entrypoints
        }
        calls_by_function[function.name] = direct_calls
        for statement in ast.walk(function):
            if not isinstance(statement, ast.stmt):
                continue
            names = {
                node.func.id
                for node in ast.walk(statement)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in entrypoints
            }
            for name in names:
                call_statements[name].add(id(statement))

    assert all(len(names) <= 1 for names in calls_by_function.values())
    assert calls_by_function["_run_diagnostic"] == {"run_diagnostic_discovery"}
    assert calls_by_function["_run_screening"] == {"run_compound_screening"}
    assert all(call_statements[name] for name in entrypoints)
    assert call_statements["run_diagnostic_discovery"].isdisjoint(
        call_statements["run_compound_screening"]
    )


def test_precollection_workflow_attempt_is_explicitly_refused(tmp_path: Path) -> None:
    output = tmp_path / "refused-output"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--out",
            str(output),
            "--skip-collection",
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "workflow gate refused before collection" in result.stderr
    assert "no collected data; run collection first" in result.stderr
    assert "Traceback" not in result.stderr
