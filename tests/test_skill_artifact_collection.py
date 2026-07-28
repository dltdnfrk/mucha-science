from __future__ import annotations

import json
from pathlib import Path

from src.research import skill_artifacts


def _record() -> dict[str, str]:
    return {
        "schema": "mucha-science.skill-artifact.v1",
        "skill_name": "AlphaFold2",
        "skill_version": "2.3.2",
        "input_sha256": "a" * 64,
        "output_sha256": "b" * 64,
        "title": "Predicted structure confidence",
        "text": "The target structure has a high-confidence core around residues 20 to 80.",
        "source_url": "https://example.org/source-sequence",
    }


def test_run_scoped_skill_receipt_becomes_derived_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_id = "run-00000000-0000-4000-8000-000000000001"
    artifact_path = (
        tmp_path
        / "runs"
        / run_id
        / "generation-2"
        / "staging"
        / "skill-artifacts.jsonl"
    )
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    monkeypatch.setenv("MUCHANIPO_HOME", str(tmp_path))
    monkeypatch.setenv("MUCHANIPO_APP_RUN_ID", run_id)
    monkeypatch.setenv("MUCHANIPO_EXECUTION_GENERATION", "2")
    monkeypatch.setenv("MUCHANIPO_SKILL_ARTIFACTS_PATH", str(artifact_path))

    evidence = skill_artifacts.search("target structure confidence")

    assert len(evidence) == 1
    item = evidence[0]
    assert item.source_grade == "C"
    assert item.provenance["kind"] == "skill_artifact"
    assert item.provenance["skill_name"] == "AlphaFold2"
    assert item.provenance["input_sha256"] == "a" * 64
    assert item.provenance["output_sha256"] == "b" * 64


def test_skill_artifact_path_outside_owned_run_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    outside = tmp_path / "outside.jsonl"
    outside.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    monkeypatch.setenv("MUCHANIPO_HOME", str(tmp_path))
    monkeypatch.setenv(
        "MUCHANIPO_APP_RUN_ID",
        "run-00000000-0000-4000-8000-000000000001",
    )
    monkeypatch.setenv("MUCHANIPO_EXECUTION_GENERATION", "1")
    monkeypatch.setenv("MUCHANIPO_SKILL_ARTIFACTS_PATH", str(outside))

    assert skill_artifacts.search("structure") == []

def test_skill_artifact_without_reproducibility_hashes_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    record = _record()
    del record["output_sha256"]
    run_id = "run-00000000-0000-4000-8000-000000000001"
    artifact_path = (
        tmp_path
        / "runs"
        / run_id
        / "generation-1"
        / "staging"
        / "skill-artifacts.jsonl"
    )
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    monkeypatch.setenv("MUCHANIPO_HOME", str(tmp_path))
    monkeypatch.setenv("MUCHANIPO_APP_RUN_ID", run_id)
    monkeypatch.setenv("MUCHANIPO_EXECUTION_GENERATION", "1")
    monkeypatch.setenv("MUCHANIPO_SKILL_ARTIFACTS_PATH", str(artifact_path))

    assert skill_artifacts.search("structure") == []
