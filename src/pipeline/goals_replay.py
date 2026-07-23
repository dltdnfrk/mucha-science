"""Deterministic event-only replay of the GOALS final report bundle.

Verification gate for issue #44: a persisted GOALS event stream must be able to
reconstruct the final report bundle without reading transient runtime state,
artifact files, or in-memory objects. The final-report lifecycle event carries
the complete ``final_bundle`` payload (see ``final_report_event_metadata``), so
replay is a pure projection over the saved events.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .final_artifact import FINAL_REPORT_BUNDLE_CONTRACT, FINAL_REPORT_STAGE_ID

GOALS_REPLAY_GATE_CONTRACT = "goals_event_replay_gate.v1"

_FINAL_EVENT_NAMES = ("stage_completed", "stage_blocked")

REPLAY_ERROR_CODES: tuple[str, ...] = (
    "replay_event_stream_corrupt",
    "replay_no_final_report_event",
    "replay_bundle_missing",
    "replay_bundle_contract_mismatch",
)


class GoalsReplayError(ValueError):
    """Replay failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def parse_goals_event_stream(text: str) -> list[dict[str, Any]]:
    """Parse a persisted ``events.jsonl`` payload into event dicts.

    Blank lines are skipped; any non-JSON or non-object line fails the whole
    stream, because a silently dropped event could hide the final bundle.
    """
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GoalsReplayError(
                "replay_event_stream_corrupt", f"line {line_number} is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise GoalsReplayError(
                "replay_event_stream_corrupt", f"line {line_number} is not a JSON object"
            )
        events.append(payload)
    return events


def replay_final_bundle(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Reconstruct the final report bundle from persisted events alone.

    Pure function of the event sequence: identical inputs always produce an
    identical (sorted-key normalized) bundle. The last final-report lifecycle
    event wins, mirroring append-only at-least-once event semantics where a
    blocked final report may later be superseded by a completed one.
    """
    bundle: dict[str, Any] | None = None
    saw_final_stage_event = False
    for event in events:
        if not isinstance(event, Mapping):
            continue
        stage = str(event.get("stage_id") or event.get("stage") or "")
        if stage != FINAL_REPORT_STAGE_ID:
            continue
        if str(event.get("event") or "") not in _FINAL_EVENT_NAMES:
            continue
        saw_final_stage_event = True
        metadata = event.get("metadata")
        candidate = metadata.get("final_bundle") if isinstance(metadata, Mapping) else None
        if candidate is None:
            # Events captured before normalization carry projected fields at top level.
            candidate = event.get("final_bundle")
        if isinstance(candidate, Mapping):
            bundle = _normalized_copy(candidate)

    if bundle is None:
        if saw_final_stage_event:
            raise GoalsReplayError(
                "replay_bundle_missing",
                "final-report lifecycle event carries no final_bundle metadata",
            )
        raise GoalsReplayError(
            "replay_no_final_report_event",
            "event stream contains no final-report lifecycle event",
        )

    contract = str(bundle.get("contract") or "")
    if contract != FINAL_REPORT_BUNDLE_CONTRACT:
        raise GoalsReplayError(
            "replay_bundle_contract_mismatch",
            f"expected {FINAL_REPORT_BUNDLE_CONTRACT}, got {contract or 'none'}",
        )
    return bundle


def bundle_fingerprint(bundle: Mapping[str, Any]) -> str:
    """Canonical serialization used to compare produced vs replayed bundles."""
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True)


def goals_replay_gate_report() -> dict[str, Any]:
    """Machine-readable description of the event-only replay gate."""
    return {
        "schema_version": 1,
        "contract": GOALS_REPLAY_GATE_CONTRACT,
        "issue": "https://github.com/dltdnfrk/mucha-science/issues/44",
        "replay_input": "persisted GOALS events only (events.jsonl)",
        "replay_source_rule": (
            "The final report bundle is reconstructed exclusively from persisted "
            "final-report lifecycle events. Replay never reads runtime state, "
            "artifact files, or transient in-memory objects."
        ),
        "determinism_rule": (
            "Replay is a pure function of the event sequence: identical inputs "
            "produce byte-identical sorted-JSON bundles across repeated runs."
        ),
        "supersession_rule": (
            "The last final-report lifecycle event wins, so a blocked final "
            "report superseded by a completed rerun replays to the completed bundle."
        ),
        "bundle_contract": FINAL_REPORT_BUNDLE_CONTRACT,
        "error_codes": list(REPLAY_ERROR_CODES),
        "verified_by": "tests/test_goals_event_replay.py",
    }


def _normalized_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    # JSON round trip: deep copy + rejection of non-serializable payloads in one step,
    # so the replayed bundle is exactly what a consumer of the saved stream would see.
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
