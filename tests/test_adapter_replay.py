from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.pipeline.scientific_contracts import byte_digest, canonical_json
from src.tools_ext.adapters.mock_scorer import (
    MockScorerAdapter,
    mock_scorer_config,
    mock_scorer_inputs,
    mock_scorer_request,
)
from src.tools_ext.contract import InvocationRecord
from src.tools_ext.invoker import ToolInvoker
from src.tools_ext.registry import AdapterRegistry
from src.tools_ext.replay import (
    Comparator,
    ReplayCapsule,
    ReplayError,
    R2ConformanceRunner,
    ToleranceProfile,
)


def invoke_scorer(tmp_path: Path, *, seed: int = 17, parameters: dict[str, object] | None = None):
    params = parameters or {
        "candidate": "MKTAYIAKQRQISFVKSHFSRQ",
        "target": "MKTAYIAKQRTISFVKSHFSRQ",
    }
    registry = AdapterRegistry()
    registry.register(mock_scorer_config(), MockScorerAdapter())
    registered = registry.probe("reference.mock_scorer")
    return ToolInvoker(tmp_path).invoke(
        registered,
        mock_scorer_request(params, seed),
        full_parameters=params,
        requested_seed=seed,
        seed_handling="HONORED",
        inputs=mock_scorer_inputs(params),
        source_snapshot_ids=("fixture-sequences-v1",),
    )


def test_identical_replay_is_r1_hash_match_and_r2_pass(tmp_path: Path) -> None:
    original = invoke_scorer(tmp_path / "original")

    replay = ReplayCapsule(original.record).execute(tmp_path / "replay")

    assert replay.r1.passed
    assert replay.r1.expected_sha256 == original.record.canonical_output_sha256
    assert replay.r1.actual_sha256 == original.record.canonical_output_sha256
    assert replay.invocation.record.raw_output_sha256 == original.record.raw_output_sha256
    assert R2ConformanceRunner().evaluate(
        original.record, canonical_json(replay.invocation.parsed.canonical_output)
    ).passed


def test_changed_seed_is_detected_as_an_exact_replay_mismatch(tmp_path: Path) -> None:
    original = invoke_scorer(tmp_path / "original")
    changed_seed = replace(original.record, requested_seed=18)

    replay = ReplayCapsule(changed_seed).execute(tmp_path / "replay")

    assert not replay.r1.passed
    assert replay.r1.expected_sha256 == original.record.canonical_output_sha256
    assert replay.r1.actual_sha256 != replay.r1.expected_sha256
    assert "canonical output hash mismatch" in replay.r1.failures


def test_one_byte_canonical_output_corruption_fails_r2_with_both_hashes(tmp_path: Path) -> None:
    original = invoke_scorer(tmp_path / "original")
    pristine = canonical_json(original.parsed.canonical_output)
    corrupted = pristine[:-2] + (b"0" if pristine[-2:-1] != b"0" else b"1") + pristine[-1:]

    report = R2ConformanceRunner().evaluate(original.record, corrupted)

    assert not report.passed
    assert report.expected_sha256 == original.record.canonical_output_sha256
    assert report.actual_sha256 == byte_digest(corrupted)
    assert report.expected_sha256 in report.failures[0]
    assert report.actual_sha256 in report.failures[0]


def test_tolerance_numeric_difference_passes_but_disposition_flip_fails() -> None:
    profile = ToleranceProfile(
        profile_id="mock-score-tolerance",
        version="1",
        comparators=(Comparator("score", "ABS_ERROR", "0.01"),),
        decision_invariants=(
            "same_constraint_disposition",
            "same_abstention_disposition",
        ),
    )
    expected = {
        "score": "0.500",
        "constraint_disposition": "PASS",
        "abstention_disposition": "RANKED",
    }
    within_tolerance = {**expected, "score": "0.506"}
    flipped = {**within_tolerance, "constraint_disposition": "FAIL"}
    runner = R2ConformanceRunner(profile)

    assert runner.compare(expected, within_tolerance).passed
    report = runner.compare(expected, flipped)
    assert not report.passed
    assert "same_constraint_disposition" in report.failures


def test_all_declared_tolerance_comparators() -> None:
    profile = ToleranceProfile(
        profile_id="all-comparators",
        version="1",
        comparators=(
            Comparator("absolute", "ABS_ERROR", "0.1"),
            Comparator("relative", "REL_ERROR", "0.05"),
            Comparator("ranking", "RANK_CORRELATION", "0.8"),
            Comparator("leaders", "TOP_K_OVERLAP", "0.5", top_k=2),
        ),
        decision_invariants=(),
    )
    expected = {
        "absolute": "1.0",
        "relative": "100",
        "ranking": ["a", "b", "c", "d"],
        "leaders": ["a", "b", "c"],
    }
    actual = {
        "absolute": "1.09",
        "relative": "104",
        "ranking": ["a", "b", "d", "c"],
        "leaders": ["a", "x", "b"],
    }

    assert R2ConformanceRunner(profile).compare(expected, actual).passed


def test_r1_capsule_uses_the_frozen_record_recipe_not_mutated_live_parameters(tmp_path: Path) -> None:
    parameters: dict[str, object] = {"candidate": "AAAA", "target": "AAAT"}
    original = invoke_scorer(tmp_path / "original", parameters=parameters)
    parameters["candidate"] = "TAMPERED AFTER INVOCATION"

    replay = ReplayCapsule(InvocationRecord.from_dict(original.record.to_dict())).execute(
        tmp_path / "replay"
    )

    assert replay.r1.passed


def test_corrupted_record_fails_cleanly_before_subprocess_execution(tmp_path: Path) -> None:
    original = invoke_scorer(tmp_path / "original")
    corrupted = replace(original.record, parameter_sha256="sha256:" + "0" * 64)

    with pytest.raises(ReplayError, match="parameter_sha256 does not match"):
        ReplayCapsule(corrupted).execute(tmp_path / "replay")
