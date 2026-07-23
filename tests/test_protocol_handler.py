"""Phase 0: transport-agnostic ai-scientist.v1 ProtocolHandler contract tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.muchanipo.events import parse_scientific_action
from src.muchanipo.web import ProtocolHandler
from src.pipeline.cycle_repository import CycleRepository


FIXTURE_ROOT = Path(__file__).parents[1] / "config/protocol/ai-scientist.v1"

CLIENT_ID = "client_00000000000000000000000000000000"
GENESIS_HASH = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
NORMAL_CONFIG = {
    "enabled": True,
    "protocol_capability": True,
    "allow_new_cycles": True,
    "allow_external_result_import": False,
    "emergency_read_only": False,
}
CREATOR = {
    "actor_kind": "human", "display_name": "Operator", "organization": None, "role": None,
    "assertion_source": "operator_entry", "verification_status": "operator_asserted_unverified",
    "authority_scope": {"kind": "none", "scope": None}, "external_reference": None,
}


def action(name: str, *, payload: dict | None = None, cycle_id: str | None = None, key: str | None = None) -> str:
    resolved_payload = dict(payload or {})
    if name == "protocol.hello" and set(resolved_payload) == {"protocol_versions"}:
        key = key or "hello-1"
        resolved_payload = {
            "handshake_idempotency_key": key,
            "client_instance_id": CLIENT_ID,
            "supported_versions": resolved_payload["protocol_versions"],
            "capabilities": [],
            "projection": "scientific-cycle.v1",
            "cursors": [],
        }
    return json.dumps({
        "protocol": "muchanipo", "protocol_version": "ai-scientist.v1", "kind": "action", "name": name,
        "message_id": "message_00000000000000000000000000000000", "cycle_id": cycle_id,
        "correlation_id": "message_00000000000000000000000000000000", "causation_id": None, "sequence": 0, "revision": 0,
        "idempotency_key": key, "timestamp": "1970-01-01T00:00:00.000000Z",
        "payload": resolved_payload, "extensions": {},
    })


def start_payload(key: str = "create-1") -> dict:
    return {
        "creation_idempotency_key": key, "expected_revision": 0, "raw_question": "Question?",
        "contract_version": "ai-scientist.v1", "boundary": {"kind": "cognitive_only", "description": "local"},
        "creator": CREATOR,
    }


def make_handler(home: Path, config: dict | None = None) -> ProtocolHandler:
    return ProtocolHandler(
        repository=CycleRepository(home),
        scientific_config=NORMAL_CONFIG if config is None else config,
    )


def replay_payload(cycle_id: str, ordinal: int) -> dict:
    return {
        "client_instance_id": CLIENT_ID,
        "request_ordinal": ordinal,
        "cursor": {"cycle_id": cycle_id, "sequence": 0, "event_hash": GENESIS_HASH},
        "max_events": 128,
    }


@pytest.mark.parametrize("group", ["valid", "invalid"])
def test_corpus_replay_yields_only_protocol_invalid_envelopes(tmp_path: Path, group: str) -> None:
    """Corpus records are byte/schema conformance vectors, not session actions.

    Per the fixture contract (tools/build_protocol_fixtures.py) no corpus line
    is a complete, schema-valid ai-scientist.v1 action envelope, so replaying
    the corpus line-by-line must reproduce today's behavior exactly: one
    command.rejected.error envelope with stable_code protocol_invalid per line
    and no connection state change.
    """
    lines = (FIXTURE_ROOT / group / "corpus.jsonl").read_bytes().decode("utf-8").splitlines()
    assert lines
    handler = make_handler(tmp_path / "home")

    outputs = [handler.handle_line(line) for line in lines]

    for line, emitted in zip(lines, outputs):
        assert parse_scientific_action(line) is None
        assert len(emitted) == 1
        envelope = json.loads(emitted[0])
        assert envelope["protocol"] == "muchanipo"
        assert envelope["protocol_version"] == "ai-scientist.v1"
        assert envelope["kind"] == "error"
        assert envelope["name"] == "command.rejected.error"
        assert envelope["payload"]["stable_code"] == "protocol_invalid"
        assert envelope["payload"]["retryability"] == "never"
        assert envelope["payload"]["outcome"] == "not_committed"
        assert envelope["correlation_id"] is None
    assert not handler.negotiated
    assert handler.request_ordinals == {}
    assert handler.ack_ordinals == {}

    steady = make_handler(tmp_path / "home")
    replayed = [steady.handle_line(line) for line in lines]
    volatile = {"message_id", "timestamp"}

    def strip(text: str):
        return {key: value for key, value in json.loads(text).items() if key not in volatile}

    for first, second in zip(outputs, replayed):
        assert len(first) == len(second)
        for left, right in zip(first, second):
            assert strip(left) == strip(right)


def test_handler_instances_do_not_share_connection_state(tmp_path: Path) -> None:
    missing = "cycle_00000000000000000000000000000000"
    first = make_handler(tmp_path / "a")
    second = make_handler(tmp_path / "b")

    welcome = first.handle_line(action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}))
    assert json.loads(welcome[0])["name"] == "protocol.welcome.response"
    assert first.negotiated is True
    assert second.negotiated is False

    premature = second.handle_line(action("cycle.replay", cycle_id=missing, payload=replay_payload(missing, 1)))
    assert json.loads(premature[0])["payload"]["stable_code"] == "capability_required"

    second.handle_line(action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}))
    for handler in (first, second):
        emitted = handler.handle_line(action("cycle.replay", cycle_id=missing, payload=replay_payload(missing, 1)))
        # A shared ordinal table would reject the second handler's ordinal 1 as
        # stale (validation_failed); both must reach the repository instead.
        assert json.loads(emitted[0])["payload"]["stable_code"] == "not_found"
    assert first.request_ordinals == {CLIENT_ID: 1}
    assert second.request_ordinals == {CLIENT_ID: 1}
    assert first.request_ordinals is not second.request_ordinals

    stale = first.handle_line(action("cycle.replay", cycle_id=missing, payload=replay_payload(missing, 1)))
    assert json.loads(stale[0])["payload"]["stable_code"] == "validation_failed"
    fresh = second.handle_line(action("cycle.replay", cycle_id=missing, payload=replay_payload(missing, 2)))
    assert json.loads(fresh[0])["payload"]["stable_code"] == "not_found"
    assert first.replay_blocked is not second.replay_blocked


@pytest.mark.parametrize("error", [KeyError("repository bug"), TypeError("repository bug"), ValueError("repository bug")])
def test_handler_propagates_unexpected_repository_errors(error: Exception) -> None:
    class BrokenRepository:
        def state_snapshot(self, cycle_id: str) -> dict[str, object]:
            del cycle_id
            raise error

    handler = ProtocolHandler(repository=BrokenRepository(), scientific_config=NORMAL_CONFIG)
    cycle_id = "cycle_00000000000000000000000000000000"
    handler.handle_line(action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}))

    with pytest.raises(type(error), match="repository bug"):
        handler.handle_line(action("cycle.resume", cycle_id=cycle_id, payload={
            "client_instance_id": CLIENT_ID,
            "request_ordinal": 1,
            "cycle_id": cycle_id,
            "cursor": {"cycle_id": cycle_id, "sequence": 0, "event_hash": GENESIS_HASH},
            "projection": "full",
        }))


def test_handle_line_keeps_unicode_line_separators_inside_one_envelope() -> None:
    """Envelopes use ensure_ascii=False, so payload strings may contain U+2028/
    U+2029 (or NEL/FS/GS/RS). splitlines() would tear such an envelope into
    invalid JSONL fragments; only "\\n" terminates an envelope."""
    note = "line one\u2028line two\u2029line three\u0085end\u001c\u001d\u001e"
    response = json.dumps(
        {"kind": "response", "name": "command.accepted.response", "payload": {"note": note}},
        ensure_ascii=False,
    ).encode("utf-8")

    class Repository:
        def start_cycle(self, command: dict) -> bytes:
            del command
            return response

    handler = ProtocolHandler(repository=Repository(), scientific_config=NORMAL_CONFIG)
    handler.handle_line(action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}))

    emitted = handler.handle_line(action("cycle.start", payload=start_payload(), key="create-1"))

    assert len(emitted) == 1
    assert json.loads(emitted[0])["payload"]["note"] == note


def test_handler_drives_a_real_cycle_session(tmp_path: Path) -> None:
    handler = make_handler(tmp_path / "home")

    welcome = handler.handle_line(action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}))
    assert json.loads(welcome[0])["name"] == "protocol.welcome.response"

    accepted = handler.handle_line(action("cycle.start", payload=start_payload(), key="create-1"))
    accepted_envelope = json.loads(accepted[0])
    assert accepted_envelope["name"] == "command.accepted.response"
    cycle_id = accepted_envelope["cycle_id"]

    replayed = handler.handle_line(action("cycle.replay", cycle_id=cycle_id, payload=replay_payload(cycle_id, 1)))
    replay_envelope = json.loads(replayed[0])
    assert replay_envelope["name"] == "cycle.replay.response"
    assert replay_envelope["payload"]["cycle_id"] == cycle_id

    # The replay gate is per-connection handler state: a second replay of the
    # same cycle is rejected until the client acknowledges it.
    blocked = handler.handle_line(action("cycle.replay", cycle_id=cycle_id, payload=replay_payload(cycle_id, 2)))
    assert json.loads(blocked[0])["payload"]["stable_code"] == "ack_mismatch"


def test_hello_cursor_mismatch_emits_snapshot_before_welcome(tmp_path: Path) -> None:
    home = tmp_path / "home"
    seeder = make_handler(home)
    seeder.handle_line(action("protocol.hello", payload={"protocol_versions": ["ai-scientist.v1"]}))
    cycle_id = json.loads(seeder.handle_line(action("cycle.start", payload=start_payload(), key="create-1"))[0])["cycle_id"]

    handler = make_handler(home)
    hello = action("protocol.hello", key="hello-2", payload={
        "handshake_idempotency_key": "hello-2",
        "client_instance_id": CLIENT_ID,
        "supported_versions": ["ai-scientist.v1"],
        "capabilities": [],
        "projection": "scientific-cycle.v1",
        "cursors": [{"cycle_id": cycle_id, "sequence": 0, "event_hash": "sha256:" + "0" * 64}],
    })
    emitted = [json.loads(line) for line in handler.handle_line(hello)]

    assert [envelope["name"] for envelope in emitted] == ["cycle.snapshot", "protocol.welcome.response"]
    assert emitted[0]["kind"] == "snapshot"
    assert emitted[0]["payload"]["reason"] == "cursor_mismatch"
    assert emitted[0]["cycle_id"] == cycle_id
    assert emitted[1]["payload"]["accepted_cursors"] == []
