from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Protocol

from .pipeline_runtime import JsonObject, JsonValue, PipelineRequestError, PipelineRuntime


WEB_PROTOCOL = "mucha-science.web.v1"
HEARTBEAT_SECONDS = 15.0


class PipelineConnection(Protocol):
    def send(self, message: str) -> None: ...


def is_pipeline_message(message: str) -> bool:
    value = _parse_object(message)
    return value is not None and value.get("protocol") == WEB_PROTOCOL


def serve_pipeline_connection(
    connection: PipelineConnection,
    first_message: str,
    runtime: PipelineRuntime,
) -> None:
    try:
        message = _required_object(first_message)
        message_type = _required_text(message, "type")
        match message_type:
            case "run.start":
                receipt = runtime.launch(
                    run_id=_required_text(message, "run_id"),
                    topic=_required_text(message, "topic"),
                    pipeline=_required_text(message, "pipeline"),
                    depth=_required_text(message, "depth"),
                    environment=_string_mapping(message.get("environment")),
                )
                _send(connection, {
                    "protocol": WEB_PROTOCOL,
                    "type": "run.started",
                    "receipt": receipt,
                })
            case "run.subscribe":
                _stream_run(
                    connection,
                    runtime,
                    run_id=_required_text(message, "run_id"),
                    after_sequence=_required_integer(message, "after_sequence"),
                )
            case "run.action":
                run_id = _required_text(message, "run_id")
                generation = _required_integer(message, "generation")
                runtime.send_action(
                    run_id,
                    generation,
                    _json_mapping(message.get("action")),
                )
                _send(connection, {
                    "protocol": WEB_PROTOCOL,
                    "type": "run.action.accepted",
                    "run_id": run_id,
                    "generation": generation,
                })
            case "run.cancel":
                acknowledgement = runtime.cancel(
                    _required_text(message, "run_id"),
                    _required_integer(message, "generation"),
                )
                _send(connection, {
                    "protocol": WEB_PROTOCOL,
                    "type": "run.cancelled",
                    "acknowledgement": acknowledgement,
                })
            case "runtime.status":
                _send(connection, {
                    "protocol": WEB_PROTOCOL,
                    "type": "runtime.status",
                    "status": runtime.status(),
                })
            case unreachable:
                raise PipelineRequestError(
                    "unsupported_message",
                    f"unsupported web message type: {unreachable}",
                )
    except PipelineRequestError as exc:
        _send(connection, {
            "protocol": WEB_PROTOCOL,
            "type": "error",
            "error": {"code": exc.code, "message": exc.detail},
        })


def _stream_run(
    connection: PipelineConnection,
    runtime: PipelineRuntime,
    *,
    run_id: str,
    after_sequence: int,
) -> None:
    cursor = after_sequence
    while True:
        events, terminal = runtime.wait_for_events(run_id, cursor, HEARTBEAT_SECONDS)
        for event in events:
            _send(connection, event)
            sequence = event.get("sequence")
            if isinstance(sequence, int):
                cursor = sequence
        if terminal and not events:
            return
        if not events:
            _send(connection, {
                "protocol": WEB_PROTOCOL,
                "type": "transport.heartbeat",
                "run_id": run_id,
                "after_sequence": cursor,
            })


def _required_object(raw: str) -> JsonObject:
    value = _parse_object(raw)
    if value is None or value.get("protocol") != WEB_PROTOCOL:
        raise PipelineRequestError("invalid_message", "invalid web protocol message")
    return value


def _parse_object(raw: str) -> JsonObject | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return value


def _required_text(message: Mapping[str, JsonValue], key: str) -> str:
    value = message.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PipelineRequestError("invalid_message", f"{key} must be a non-empty string")
    return value


def _required_integer(message: Mapping[str, JsonValue], key: str) -> int:
    value = message.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PipelineRequestError("invalid_message", f"{key} must be an integer")
    return value


def _string_mapping(value: JsonValue) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PipelineRequestError("invalid_message", "environment must be an object")
    if not all(isinstance(item, str) for item in value.values()):
        raise PipelineRequestError("invalid_message", "environment values must be strings")
    return {key: item for key, item in value.items() if isinstance(item, str)}


def _json_mapping(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise PipelineRequestError("invalid_message", "action must be an object")
    return dict(value)


def _send(connection: PipelineConnection, payload: JsonObject) -> None:
    connection.send(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
