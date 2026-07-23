"""Deterministic event-only replay gate for GOALS final bundles (issue #44)."""
from __future__ import annotations

import json

import pytest

from src.council.parsers import RoundResult
from src.evidence.artifact import EvidenceRef
from src.hitl.plannotator_adapter import HITLResult
from src.hitl.plannotator_review_artifact import (
    PlannotatorReviewArtifactInput,
    build_plannotator_review_stage_artifact,
)
from src.muchanipo.events import normalize_goals_event
from src.pipeline.council_artifact import (
    LLMCouncilArtifactInput,
    build_llm_council_stage_artifact,
)
from src.pipeline.final_artifact import (
    FINAL_REPORT_BUNDLE_CONTRACT,
    FinalReportArtifactInput,
    build_final_report_stage_artifact,
    build_final_report_stage_event,
    final_report_payload_from_stage_artifact,
)
from src.pipeline.goals_artifacts import build_goals_stage_artifact
from src.pipeline.goals_replay import (
    GoalsReplayError,
    bundle_fingerprint,
    goals_replay_gate_report,
    parse_goals_event_stream,
    replay_final_bundle,
)


def _evidence_ref(ref_id="ev-1"):
    return EvidenceRef(
        id=ref_id,
        source_url=f"https://example.test/{ref_id}",
        source_title=f"Source {ref_id}",
        quote="A source-backed observation.",
        source_grade="A",
        provenance={"kind": "test"},
    )


def _persona_payload():
    return {
        "schema_version": 1,
        "artifact_id": "persona_generation",
        "contract": "persona_generation_stage_artifact.v1",
        "persona_pool_id": "personas:replay",
        "admitted_personas": [
            {"persona_id": "persona-1", "role": "operator", "evidence_refs_from_ontology": ["entity:1"]}
        ],
        "speaker_schedule": {"active_speakers": ["persona-1"]},
        "downstream_consumability": {
            "llm_council_ready": True,
            "reasons": [],
            "admitted_persona_count": 1,
        },
    }


def _council_artifact():
    return build_llm_council_stage_artifact(
        LLMCouncilArtifactInput(
            persona_artifact=_persona_payload(),
            rounds=[
                RoundResult(
                    layer_id="L1_market_sizing",
                    chapter_title="Market context",
                    key_claim="Council-backed final claim",
                    body_claims=["Follow-on claim"],
                    evidence_ref_ids=["ev-1"],
                    confidence_score=0.84,
                    framework="MECE",
                )
            ],
            evidence_refs=[_evidence_ref()],
            expected_layer_ids=["L1_market_sizing"],
            require_live=False,
        )
    )


def _review_artifact(gate_name):
    return build_plannotator_review_stage_artifact(
        PlannotatorReviewArtifactInput(
            gate_name=gate_name,
            result=HITLResult(
                status="approved",
                gate_id=f"{gate_name}-gate",
                path=f"plannotator://sessions/{gate_name}",
                synthetic=False,
                decision_provenance={
                    "mode": "plannotator_http",
                    "source": "test",
                    "synthetic": False,
                },
            ),
            mode="plannotator",
            target_artifact_refs=[f"state:{gate_name}"],
        )
    )


def _completed_upstream(stage_id):
    return build_goals_stage_artifact(
        stage_id,
        status="completed",
        outputs=[{"artifact_id": stage_id, "present": True}],
        gates=[{"gate_id": f"{stage_id}_gate", "status": "passed"}],
    )


def _artifact_input(tmp_path, **overrides):
    base = {
        "report_id": "brief-replay",
        "title": "Replay decision report",
        "report_markdown": "# Replay decision report\n\nSource-backed report body.\n",
        "output_dir": tmp_path,
        "upstream_artifacts": {
            "deep_research_max": _completed_upstream("deep_research_max"),
            "plannotator_review": [
                _review_artifact("plan"),
                _review_artifact("evidence"),
                _review_artifact("report"),
            ],
            "ontology_extraction": _completed_upstream("ontology_extraction"),
            "persona_generation": _completed_upstream("persona_generation"),
            "llm_council": _council_artifact(),
        },
        "evidence_refs": [_evidence_ref()],
        "open_gaps": ["Quantify pricing sensitivity."],
        "gates": {
            "plan": {"status": "approved", "gate_id": "plan-gate"},
            "evidence": {"status": "approved", "gate_id": "evidence-gate"},
            "report": {"status": "approved", "gate_id": "report-gate"},
        },
        "reference_runtime_artifacts": {
            "gbrain": {
                "gbrain_runtime": {"valid": True, "event_ledger": [{"id": "evt-1"}]},
                "content_hash": "abc123",
            }
        },
        "obsidian_write_path": str(tmp_path / "Replay decision report.md"),
        "obsidian_write_attempted": True,
    }
    base.update(overrides)
    return FinalReportArtifactInput(**base)


def _lifecycle_noise_events():
    return [
        normalize_goals_event({"event": "stage_started", "stage": "deep_research_max"}),
        normalize_goals_event(
            {"event": "stage_progress", "stage": "deep_research_max", "progress_percent": 60.0}
        ),
        normalize_goals_event({"event": "stage_completed", "stage": "deep_research_max"}),
        normalize_goals_event({"event": "stage_started", "stage": "llm_council"}),
        normalize_goals_event({"event": "stage_completed", "stage": "llm_council"}),
    ]


def _event_stream_text(events):
    return "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"


def test_replayed_bundle_matches_produced_bundle_through_jsonl_round_trip(tmp_path):
    """End-to-end: saved events alone reconstruct the exact produced bundle."""
    artifact_input = _artifact_input(tmp_path)
    produced_bundle = final_report_payload_from_stage_artifact(
        build_final_report_stage_artifact(_artifact_input(tmp_path / "produced"))
    )["bundle"]
    final_event = build_final_report_stage_event(artifact_input)
    events = [*_lifecycle_noise_events(), final_event]

    # Persist -> parse -> replay: no runtime state crosses the JSONL boundary.
    replayed = replay_final_bundle(parse_goals_event_stream(_event_stream_text(events)))

    assert replayed["contract"] == FINAL_REPORT_BUNDLE_CONTRACT
    assert replayed["verdict"] == "PASS"
    assert bundle_fingerprint(replayed) == bundle_fingerprint(produced_bundle)


def test_replay_is_deterministic_across_repeated_runs(tmp_path):
    final_event = build_final_report_stage_event(_artifact_input(tmp_path))
    text = _event_stream_text([*_lifecycle_noise_events(), final_event])

    first = replay_final_bundle(parse_goals_event_stream(text))
    second = replay_final_bundle(parse_goals_event_stream(text))

    assert bundle_fingerprint(first) == bundle_fingerprint(second)


def test_blocked_final_report_replays_with_blockers(tmp_path):
    blocked_input = _artifact_input(
        tmp_path,
        gates={
            "plan": {"status": "approved", "gate_id": "plan-gate"},
            "evidence": {"status": "approved", "gate_id": "evidence-gate"},
            "report": {"status": "pending", "gate_id": "report-gate"},
        },
    )
    final_event = build_final_report_stage_event(blocked_input)
    assert final_event["event"] == "stage_blocked"

    replayed = replay_final_bundle([final_event])

    assert replayed["verdict"] == "BLOCKED"
    assert any(
        blocker.get("code") == "blocked_final_gate_pending" for blocker in replayed["blockers"]
    )


def test_last_final_report_event_supersedes_earlier_blocked_event(tmp_path):
    blocked_event = build_final_report_stage_event(
        _artifact_input(
            tmp_path / "blocked",
            gates={
                "plan": {"status": "approved", "gate_id": "plan-gate"},
                "evidence": {"status": "approved", "gate_id": "evidence-gate"},
                "report": {"status": "pending", "gate_id": "report-gate"},
            },
        )
    )
    completed_event = build_final_report_stage_event(_artifact_input(tmp_path / "completed"))

    replayed = replay_final_bundle([blocked_event, completed_event])

    assert replayed["verdict"] == "PASS"


def test_replay_failure_codes_are_stable(tmp_path):
    with pytest.raises(GoalsReplayError) as no_final:
        replay_final_bundle(_lifecycle_noise_events())
    assert no_final.value.code == "replay_no_final_report_event"

    stripped = build_final_report_stage_event(_artifact_input(tmp_path))
    stripped_metadata = dict(stripped["metadata"])
    stripped_metadata.pop("final_bundle", None)
    stripped = {**stripped, "metadata": stripped_metadata}
    with pytest.raises(GoalsReplayError) as missing:
        replay_final_bundle([stripped])
    assert missing.value.code == "replay_bundle_missing"

    wrong_contract = build_final_report_stage_event(_artifact_input(tmp_path / "wrong"))
    wrong_metadata = dict(wrong_contract["metadata"])
    wrong_metadata["final_bundle"] = {**wrong_metadata["final_bundle"], "contract": "other.v1"}
    wrong_contract = {**wrong_contract, "metadata": wrong_metadata}
    with pytest.raises(GoalsReplayError) as mismatch:
        replay_final_bundle([wrong_contract])
    assert mismatch.value.code == "replay_bundle_contract_mismatch"

    with pytest.raises(GoalsReplayError) as corrupt:
        parse_goals_event_stream('{"event": "stage_started"}\nnot-json\n')
    assert corrupt.value.code == "replay_event_stream_corrupt"


def test_final_report_event_is_self_sufficient(tmp_path):
    """The persisted event embeds the complete bundle, field for field."""
    artifact = build_final_report_stage_artifact(_artifact_input(tmp_path))
    produced_bundle = final_report_payload_from_stage_artifact(artifact)["bundle"]
    event = build_final_report_stage_event(_artifact_input(tmp_path / "event"))

    embedded = event["metadata"]["final_bundle"]
    assert bundle_fingerprint(embedded) == bundle_fingerprint(produced_bundle)


def test_gate_report_names_rules_codes_and_evidence():
    report = goals_replay_gate_report()

    assert report["contract"] == "goals_event_replay_gate.v1"
    assert report["bundle_contract"] == FINAL_REPORT_BUNDLE_CONTRACT
    assert set(report["error_codes"]) == {
        "replay_event_stream_corrupt",
        "replay_no_final_report_event",
        "replay_bundle_missing",
        "replay_bundle_contract_mismatch",
    }
    assert report["verified_by"] == "tests/test_goals_event_replay.py"
