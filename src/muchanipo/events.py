"""JSON-line event protocol used by `python3 -m muchanipo serve`.

The Swift native shell consumes one JSON object per stdout line and writes
user actions to stdin in the same format. Event field layout matches
_assignments/ASSIGNMENT_C33_native_app.md.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, IO

from src.pipeline.goals_stages import (
    PUBLIC_GOALS_STAGE_IDS,
    normalize_public_stage,
)
from src.pipeline.scientific_contracts import (
    ContractError,
    decode_json_object,
    validate_protocol_action,
)


KNOWN_EVENTS = frozenset(
    {
        "phase_change",
        "run_started",
        "pipeline_heartbeat",
        "stage_started",
        "stage_progress",
        "stage_blocked",
        "stage_completed",
        "stage_failed",
        "deep_interview_progress",
        "deep_interview_artifacts",
        "interview_ontology_delta",
        "interview_question",
        "hitl_gate",
        "research_progress",
        "council_round_start",
        "council_turn",
        "council_persona_token",
        "council_round_done",
        "report_chunk",
        "done",
        "warning",
        "error",
    }
)

KNOWN_ACTIONS = frozenset(
    {
        "interview_answer",
        "approve_designdoc",
        "hitl_decision",
        "abort",
    }
)
SCIENTIFIC_PROTOCOL = "muchanipo"
SCIENTIFIC_PROTOCOL_VERSION = "ai-scientist.v1"

SCIENTIFIC_ACTIONS = frozenset(
    {
        "protocol.hello",
        "cycle.start",
        "cycle.replay",
        "cycle.resume",
        "cycle.continue",
        "responsibility.question_selection.disposition",
        "responsibility.safety_ethics_review.disposition",
        "responsibility.execution_accountability.disposition",
        "responsibility.exception_interpretation.disposition",
        "responsibility.novelty_value_judgment.disposition",
        "responsibility.final_accountability.disposition",
        "responsibility.disposition.supersede",
        "proposal.reject",
        "result.submit",
        "validation.adjudicate",
        "cycle.abort",
        "export.create",
        "export.get",
        "report.render",
        "cycle.ack",
    }
)

NORMALIZED_STAGE_EVENTS = frozenset(
    {
        "stage_started",
        "stage_progress",
        "stage_blocked",
        "stage_completed",
        "stage_failed",
    }
)

LEGACY_SUBEVENT_STAGE_HINTS: dict[str, str] = {
    "deep_interview_progress": "deep_interview",
    "deep_interview_artifacts": "deep_interview",
    "interview_ontology_delta": "ontology_extraction",
    "interview_question": "deep_interview",
    "hitl_gate": "plannotator_review",
    "research_progress": "deep_research_max",
    "council_round_start": "llm_council",
    "council_turn": "llm_council",
    "council_persona_token": "llm_council",
    "council_round_done": "llm_council",
    "report_chunk": "final_report_html_yaml",
}

_EVENT_STATUS_MAP: dict[str, str] = {
    "stage_started": "in_progress",
    "stage_progress": "in_progress",
    "stage_blocked": "blocked",
    "stage_completed": "completed",
    "stage_failed": "failed",
}


@dataclass(frozen=True)
class Event:
    """One outbound stdout event."""

    event: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        # Legacy research events are permissive by design: the full pipeline
        # emits stage/report telemetry beyond the stub-era KNOWN_EVENTS set
        # (e.g. final_report), and clients preserve unknown legacy events.
        # Strict fail-closed validation applies only to ai-scientist.v1
        # envelopes via validate_protocol_action.
        if not isinstance(self.event, str) or not self.event:
            raise ValueError(f"invalid legacy event name: {self.event!r}")
        return json.dumps({"event": self.event, **self.fields}, ensure_ascii=False)


@dataclass(frozen=True)
class Action:
    """One inbound stdin action from the Swift shell."""

    action: str
    fields: dict[str, Any] = field(default_factory=dict)

class _FrozenDict(dict[str, Any]):
    """A JSON-serializable mapping that cannot be mutated after construction."""

    def __init__(self, value: Mapping[str, Any]) -> None:
        dict.__init__(self, ((key, _freeze_value(item)) for key, item in value.items()))

    @staticmethod
    def _immutable(*_: object, **__: object) -> None:
        raise TypeError("scientific envelope content is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict(value)
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return deepcopy(value)
def _copy_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _copy_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_copy_value(item) for item in value]
    if isinstance(value, frozenset):
        return [_copy_value(item) for item in value]
    return deepcopy(value)




def _frame_message_id(envelope: "ScientificEnvelope") -> str:
    content = {
        "kind": envelope.kind,
        "name": envelope.name,
        "payload": envelope.payload,
        "cycle_id": envelope.cycle_id,
        "correlation_id": envelope.correlation_id,
        "causation_id": envelope.causation_id,
        "sequence": envelope.sequence,
        "revision": envelope.revision,
        "idempotency_key": envelope.idempotency_key,
        "timestamp": envelope.timestamp,
        "extensions": envelope.extensions,
    }
    return f"message_{sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()[:32]}"


@dataclass(frozen=True)
class ScientificEnvelope:
    """Negotiated AI-scientist protocol frame; separate from legacy flat events."""

    kind: str
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    message_id: str | None = None
    cycle_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    sequence: int = 0
    revision: int = 0
    idempotency_key: str | None = None
    timestamp: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping) or not isinstance(self.extensions, Mapping):
            raise ValueError("scientific envelope payload and extensions must be objects")
        object.__setattr__(self, "payload", _FrozenDict(self.payload))
        object.__setattr__(self, "extensions", _FrozenDict(self.extensions))
        object.__setattr__(
            self,
            "timestamp",
            self.timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )
        object.__setattr__(self, "message_id", self.message_id or _frame_message_id(self))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": SCIENTIFIC_PROTOCOL,
            "protocol_version": SCIENTIFIC_PROTOCOL_VERSION,
            "kind": self.kind,
            "name": self.name,
            "message_id": self.message_id,
            "cycle_id": self.cycle_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "sequence": self.sequence,
            "revision": self.revision,
            "idempotency_key": self.idempotency_key,
            "timestamp": self.timestamp,
            "payload": _copy_value(self.payload),
            "extensions": _copy_value(self.extensions),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def emit_scientific(envelope: ScientificEnvelope, *, stream: IO[str] | None = None) -> None:
    """Emit one negotiated protocol envelope without changing legacy event layout."""
    out = stream if stream is not None else sys.stdout
    out.write(envelope.to_json())
    out.write("\n")
    out.flush()


def parse_scientific_action(line: str) -> ScientificEnvelope | None:
    """Parse only complete, frozen AI-scientist v1 action envelopes."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = decode_json_object(line)
        if not isinstance(obj, dict):
            return None
        validate_protocol_action(obj)
    except ContractError:
        return None
    return ScientificEnvelope(
        kind="action", name=obj["name"], payload=dict(obj["payload"]),
        message_id=obj["message_id"], cycle_id=obj["cycle_id"],
        correlation_id=obj["correlation_id"], causation_id=obj["causation_id"],
        sequence=obj["sequence"], revision=obj["revision"],
        idempotency_key=obj["idempotency_key"], timestamp=obj["timestamp"],
        extensions=dict(obj["extensions"]),
    )

def emit(event: str, *, stream: IO[str] | None = None, **fields: Any) -> None:
    """Write a single JSON-line event and flush so Swift sees it immediately."""
    out = stream if stream is not None else sys.stdout
    out.write(Event(event, fields).to_json())
    out.write("\n")
    out.flush()


def _event_metadata(payload: Mapping[str, Any], *, exclude: set[str]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), Mapping) else {}
    for key, value in payload.items():
        if key not in exclude and key != "metadata":
            metadata[key] = value
    return metadata


def normalize_goals_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize runtime events into the public GOALS stage event contract.

    Canonical events keep their stage event name and accept canonical ids. Legacy
    runtime stages are mapped to canonical public ids and retained in metadata.
    Legacy subevents become ``stage_progress`` with the old event name in
    ``metadata.subactivity``.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("event payload must be a mapping")
    event_name = str(payload.get("event") or "")
    if not event_name:
        raise KeyError("event payload requires event")

    stage_hint = payload.get("stage_id") or payload.get("stage") or LEGACY_SUBEVENT_STAGE_HINTS.get(event_name)
    if stage_hint is None:
        raise KeyError("GOALS event requires stage, stage_id, or known legacy subevent")
    stage_key = str(stage_hint)
    stage_id = normalize_public_stage(stage_key)

    if event_name in NORMALIZED_STAGE_EVENTS:
        normalized_event = event_name
        exclude = {"event", "stage", "stage_id"}
        metadata = _event_metadata(payload, exclude=exclude)
        if stage_key != stage_id:
            metadata.setdefault("legacy_stage", stage_key)
    else:
        normalized_event = "stage_progress"
        exclude = {"event", "stage", "stage_id"}
        metadata = _event_metadata(payload, exclude=exclude)
        metadata.setdefault("subactivity", event_name)
        if stage_key != stage_id and stage_key not in PUBLIC_GOALS_STAGE_IDS:
            metadata.setdefault("legacy_stage", stage_key)

    return {
        "event": normalized_event,
        "stage": stage_id,
        "stage_id": stage_id,
        "status": _EVENT_STATUS_MAP.get(normalized_event, "in_progress"),
        "metadata": metadata,
    }


def goals_event_contract_report() -> dict[str, Any]:
    """Return the stable normalized GOALS event contract for JSON consumers."""
    return {
        "schema_version": 1,
        "contract": "goals_normalized_events",
        "stage_ids": list(PUBLIC_GOALS_STAGE_IDS),
        "events": list(sorted(NORMALIZED_STAGE_EVENTS)),
        "event_status_map": dict(_EVENT_STATUS_MAP),
        "required_fields": ["event", "stage", "stage_id", "status", "metadata"],
        "legacy_subevent_stage_hints": dict(LEGACY_SUBEVENT_STAGE_HINTS),
        "compatibility": (
            "stage_started/stage_progress/stage_blocked/stage_completed/"
            "stage_failed carry canonical public GOALS stage ids. Legacy runtime "
            "subevents are projected as stage_progress and preserved in "
            "metadata.subactivity."
        ),
    }


def parse_action(line: str) -> Action | None:
    """Parse one stdin line into an Action, or None on blank/invalid input."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or set(obj) == set() or "action" not in obj:
        return None
    name = obj.pop("action")
    if not isinstance(name, str) or name not in KNOWN_ACTIONS:
        return None
    return Action(action=name, fields=obj)
