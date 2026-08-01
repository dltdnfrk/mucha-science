from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.evidence_ladder import (
    EvidenceLadderError,
    derive_auto_calibration_eligibility,
    validate_pairing,
)
from src.platform_contracts import AssayObservation, Measurement, Prediction

DISCLAIMER = "synthetic data — plumbing proof, no performance claim"


def _load(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    assert isinstance(value, dict)
    return value


def _run(repo_root: Path, out_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "m1_loop.py"),
            "--pack",
            str(repo_root / "packs" / "synthetic-m1"),
            "--out",
            str(out_dir),
            *extra,
        ],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_m1_loop_writes_ranked_admitted_and_validated_artifacts(
    repo_root: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "m1"
    completed = _run(repo_root, out_dir)

    assert completed.returncode == 0, completed.stderr
    ranking = _load(out_dir / "ranked_results.json")
    prediction_artifact = _load(out_dir / "prediction.json")
    observation_artifact = _load(out_dir / "assay_observation.json")
    measurement_artifact = _load(out_dir / "measurement.json")
    provenance = _load(out_dir / "provenance_audit.json")

    assert prediction_artifact["artifact_kind"] == "Prediction"
    assert observation_artifact["artifact_kind"] == "AssayObservation"
    assert measurement_artifact["artifact_kind"] == "Measurement"
    assert all(
        artifact["disclaimer"] == DISCLAIMER
        for artifact in (
            ranking,
            prediction_artifact,
            observation_artifact,
            measurement_artifact,
            provenance,
        )
    )
    excluded_ids = {item["candidate_id"] for item in ranking["excluded"]}
    assert {"synthetic-candidate-03", "synthetic-candidate-06"} <= excluded_ids
    assert ranking["abstained"] == []

    prediction = Prediction.from_payload(prediction_artifact["record"])
    observation = AssayObservation.from_payload(observation_artifact["record"])
    measurement = Measurement.from_payload(measurement_artifact["record"])
    unit = prediction.estimand["unit"]
    validated = validate_pairing(
        measurement,
        prediction,
        observation,
        convertible_units={(unit, unit)},
    )
    assert measurement.pairing_design.value == "PROSPECTIVE_LOCKED"
    assert derive_auto_calibration_eligibility(validated).eligible
    assert measurement_artifact["pairing_validation"] == {
        "design": "PROSPECTIVE_LOCKED",
        "passed": True,
        "auto_calibration_eligible": True,
    }

    ledger_lines = (out_dir / "invocation_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    traces = provenance["screening"]["score_traces"]
    assert len(ledger_lines) == len(ranking["ranked"]) + len(ranking["excluded"])
    assert len(traces) == len(ledger_lines)
    assert all(json.loads(line)["payload"]["disclaimer"] == DISCLAIMER for line in ledger_lines)
    assert all(
        trace["tool"]["reported_version"]
        and trace["parameters"]
        and isinstance(trace["seed"], int)
        and trace["pack_identity"]["manifest_sha256"].startswith("sha256:")
        for trace in traces
    )


def test_backdated_observation_is_rejected_by_pairing_validator(
    repo_root: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "valid"
    completed = _run(repo_root, out_dir)
    assert completed.returncode == 0, completed.stderr

    prediction = Prediction.from_payload(_load(out_dir / "prediction.json")["record"])
    original = AssayObservation.from_payload(_load(out_dir / "assay_observation.json")["record"])
    observation_content = original.to_content()
    observation_content["assay_started_at"] = prediction.issued_at
    doctored = AssayObservation.from_content(observation_content)
    measurement_content = Measurement.from_payload(
        _load(out_dir / "measurement.json")["record"]
    ).to_content()
    measurement_content["observation_id"] = doctored.observation_id
    measurement = Measurement.from_content(measurement_content)
    unit = prediction.estimand["unit"]

    with pytest.raises(EvidenceLadderError, match="locked no later than assay start"):
        validate_pairing(
            measurement,
            prediction,
            doctored,
            convertible_units={(unit, unit)},
        )


def test_backdated_debug_flag_exits_nonzero_with_clear_gate_error(
    repo_root: Path, tmp_path: Path
) -> None:
    completed = _run(
        repo_root,
        tmp_path / "backdated",
        "--inject-backdated-observation",
    )

    assert completed.returncode != 0
    assert "PROSPECTIVE_LOCKED pairing rejected" in completed.stderr
    assert "locked no later than assay start" in completed.stderr
    assert not (tmp_path / "backdated").exists()
