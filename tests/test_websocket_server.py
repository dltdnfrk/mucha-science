from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from threading import Thread
from collections.abc import Iterator

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.sync.client import connect

from src.pipeline.cycle_repository import CycleRepository
from src.muchanipo.web.scientific_config import ScientificConfig, ScientificConfigValue


CLIENT_ID = "client_00000000000000000000000000000000"
GENESIS_HASH = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
NORMAL_CONFIG = {
    "enabled": True,
    "protocol_capability": True,
    "allow_new_cycles": True,
    "allow_external_result_import": False,
    "emergency_read_only": False,
}


def action(name: str, *, payload: dict[str, ScientificConfigValue], cycle_id: str | None = None) -> str:
    return json.dumps({
        "protocol": "muchanipo",
        "protocol_version": "ai-scientist.v1",
        "kind": "action",
        "name": name,
        "message_id": "message_00000000000000000000000000000000",
        "cycle_id": cycle_id,
        "correlation_id": "message_00000000000000000000000000000000",
        "causation_id": None,
        "sequence": 0,
        "revision": 0,
        "idempotency_key": "request-1" if name == "protocol.hello" else None,
        "timestamp": "1970-01-01T00:00:00.000000Z",
        "payload": payload,
        "extensions": {},
    })


def hello() -> str:
    return action("protocol.hello", payload={
        "handshake_idempotency_key": "request-1",
        "client_instance_id": CLIENT_ID,
        "supported_versions": ["ai-scientist.v1"],
        "capabilities": [],
        "projection": "scientific-cycle.v1",
        "cursors": [],
    })


def replay(cycle_id: str, ordinal: int) -> str:
    return action("cycle.replay", cycle_id=cycle_id, payload={
        "client_instance_id": CLIENT_ID,
        "request_ordinal": ordinal,
        "cursor": {"cycle_id": cycle_id, "sequence": 0, "event_hash": GENESIS_HASH},
        "max_events": 128,
    })


class FakeConnection:
    def __init__(self, messages: list[str | bytes]) -> None:
        self.messages = messages
        self.sent: list[str] = []
        self.closed: tuple[int, str] | None = None

    def __iter__(self) -> Iterator[str | bytes]:
        return iter(self.messages)

    def send(self, message: str) -> None:
        self.sent.append(message)

    def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


class FakeHandler:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.received: list[str] = []

    def handle_line(self, line: str) -> list[str]:
        self.received.append(line)
        return self.outputs


def test_websocket_transport_module_is_available() -> None:
    # Given an installed MuchaNipo Python package
    module_name = "src.muchanipo.web.websocket_server"

    # When the dedicated WebSocket transport is resolved
    specification = importlib.util.find_spec(module_name)

    # Then the production transport module is available to the CLI entrypoint
    assert specification is not None


def test_text_message_maps_to_ordered_text_frames_without_newlines() -> None:
    # Given one complete text message and a handler that emits two JSON records
    module = importlib.import_module("src.muchanipo.web.websocket_server")
    connection = FakeConnection(["input-record"])
    handler = FakeHandler(["first", "second"])

    # When the connection adapter serves that message
    module.serve_websocket_connection(connection, handler)

    # Then it passes the message unchanged and preserves output frame order
    assert handler.received == ["input-record"]
    assert connection.sent == ["first", "second"]
    assert connection.closed is None


def test_binary_message_closes_with_unsupported_data() -> None:
    # Given a binary message followed by text that must never be dispatched
    module = importlib.import_module("src.muchanipo.web.websocket_server")
    connection = FakeConnection([b"binary", "ignored"])
    handler = FakeHandler(["unexpected"])

    # When the connection adapter receives the binary message
    module.serve_websocket_connection(connection, handler)

    # Then it closes with the stable unsupported-data code and stops dispatch
    assert connection.closed == (1003, "binary frames are unsupported")
    assert handler.received == []
    assert connection.sent == []


def test_real_server_hello_and_connection_state_are_isolated(tmp_path: Path) -> None:
    # Given one live server with one shared repository
    module = importlib.import_module("src.muchanipo.web.websocket_server")
    repository = CycleRepository(tmp_path / "home")
    server = module.create_websocket_server(
        repository=repository,
        scientific_config=NORMAL_CONFIG,
        host="127.0.0.1",
        port=0,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    port = server.socket.getsockname()[1]
    missing = "cycle_00000000000000000000000000000000"

    try:
        # When two clients negotiate and independently use request ordinal one
        with connect(f"ws://127.0.0.1:{port}") as first, connect(f"ws://127.0.0.1:{port}") as second:
            first.send(hello())
            second.send(hello())
            first_welcome = json.loads(first.recv())
            second_welcome = json.loads(second.recv())
            first.send(replay(missing, 1))
            second.send(replay(missing, 1))
            first_error = json.loads(first.recv())
            second_error = json.loads(second.recv())
    finally:
        server.shutdown()
        thread.join(timeout=2)

    # Then both receive text responses and neither connection sees stale state
    assert first_welcome["name"] == "protocol.welcome.response"
    assert second_welcome["name"] == "protocol.welcome.response"
    assert first_error["payload"]["stable_code"] == "not_found"
    assert second_error["payload"]["stable_code"] == "not_found"
    assert not thread.is_alive()


def test_server_builds_one_handler_per_connection_with_shared_repository(tmp_path: Path) -> None:
    # Given a server factory instrumented with a handler factory
    module = importlib.import_module("src.muchanipo.web.websocket_server")
    repository = CycleRepository(tmp_path / "home")
    repositories: list[CycleRepository] = []
    handlers: list[FakeHandler] = []

    def handler_factory(
        *,
        repository: CycleRepository,
        scientific_config: ScientificConfig | None,
    ) -> FakeHandler:
        del scientific_config
        repositories.append(repository)
        handler = FakeHandler([f"response-{len(handlers) + 1}"])
        handlers.append(handler)
        return handler

    server = module.create_websocket_server(
        repository=repository,
        scientific_config=NORMAL_CONFIG,
        host="127.0.0.1",
        port=0,
        handler_factory=handler_factory,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    port = server.socket.getsockname()[1]

    try:
        # When two clients each send one message
        with connect(f"ws://127.0.0.1:{port}") as first:
            first.send("first")
            assert first.recv() == "response-1"
        with connect(f"ws://127.0.0.1:{port}") as second:
            second.send("second")
            assert second.recv() == "response-2"
    finally:
        server.shutdown()
        thread.join(timeout=2)

    # Then their handlers differ while the repository object is identical
    assert len(handlers) == 2
    assert handlers[0] is not handlers[1]
    assert repositories == [repository, repository]
    assert repositories[0] is repository
    assert repositories[1] is repository


def test_malformed_text_keeps_connection_open(tmp_path: Path) -> None:
    # Given a live negotiated-protocol server
    module = importlib.import_module("src.muchanipo.web.websocket_server")
    server = module.create_websocket_server(
        repository=CycleRepository(tmp_path / "home"),
        scientific_config=NORMAL_CONFIG,
        host="127.0.0.1",
        port=0,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    port = server.socket.getsockname()[1]

    try:
        # When malformed text is followed by a valid hello on the same socket
        with connect(f"ws://127.0.0.1:{port}") as client:
            client.send("{")
            malformed = json.loads(client.recv())
            client.send(hello())
            welcome = json.loads(client.recv())
    finally:
        server.shutdown()
        thread.join(timeout=2)

    # Then the malformed record is rejected without closing the connection
    assert malformed["payload"]["stable_code"] == "protocol_invalid"
    assert welcome["name"] == "protocol.welcome.response"
    assert not thread.is_alive()


def test_real_binary_message_closes_with_unsupported_data(tmp_path: Path) -> None:
    # Given a live text-only WebSocket server
    module = importlib.import_module("src.muchanipo.web.websocket_server")
    server = module.create_websocket_server(
        repository=CycleRepository(tmp_path / "home"),
        scientific_config=NORMAL_CONFIG,
        host="127.0.0.1",
        port=0,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    port = server.socket.getsockname()[1]

    try:
        # When a real client sends a binary application message
        with connect(f"ws://127.0.0.1:{port}") as client:
            client.send(b"binary")
            with pytest.raises(ConnectionClosedError) as raised:
                client.recv()
    finally:
        server.shutdown()
        thread.join(timeout=2)

    # Then the peer observes the exact unsupported-data close contract
    assert raised.value.rcvd is not None
    assert raised.value.rcvd.code == 1003
    assert raised.value.rcvd.reason == "binary frames are unsupported"
    assert not thread.is_alive()


def test_oversized_message_closes_with_message_too_big(tmp_path: Path) -> None:
    # Given a live server with the explicit one-megabyte inbound limit
    module = importlib.import_module("src.muchanipo.web.websocket_server")
    server = module.create_websocket_server(
        repository=CycleRepository(tmp_path / "home"),
        scientific_config=NORMAL_CONFIG,
        host="127.0.0.1",
        port=0,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    port = server.socket.getsockname()[1]

    try:
        # When a client sends one byte more than the configured limit
        with connect(f"ws://127.0.0.1:{port}") as client:
            client.send("x" * (module.MAX_MESSAGE_SIZE + 1))
            with pytest.raises(ConnectionClosedError) as raised:
                client.recv()
    finally:
        server.shutdown()
        thread.join(timeout=2)

    # Then the transport reports RFC 6455 message-too-big and shuts down cleanly
    assert raised.value.rcvd is not None
    assert raised.value.rcvd.code == 1009
    assert not thread.is_alive()
