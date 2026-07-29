from __future__ import annotations

import json
from pathlib import Path
from queue import Queue
import signal
from socket import create_connection
import subprocess
from threading import Thread
from urllib.parse import urlsplit

import pytest
from websockets.sync.client import connect

from src.muchanipo.web.scientific_config import ScientificConfigValue


REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_EXECUTABLE = REPO_ROOT / "bin" / "muchanipo-web"
CLIENT_ID = "client_00000000000000000000000000000000"
GENESIS_HASH = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
CREATOR: dict[str, ScientificConfigValue] = {
    "actor_kind": "human",
    "display_name": "Operator",
    "organization": None,
    "role": None,
    "assertion_source": "operator_entry",
    "verification_status": "operator_asserted_unverified",
    "authority_scope": {"kind": "none", "scope": None},
    "external_reference": None,
}


def action(
    name: str,
    *,
    payload: dict[str, ScientificConfigValue],
    cycle_id: str | None = None,
    idempotency_key: str | None = None,
) -> str:
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
        "idempotency_key": idempotency_key,
        "timestamp": "1970-01-01T00:00:00.000000Z",
        "payload": payload,
        "extensions": {},
    })


def hello(key: str) -> str:
    return action(
        "protocol.hello",
        idempotency_key=key,
        payload={
            "handshake_idempotency_key": key,
            "client_instance_id": CLIENT_ID,
            "supported_versions": ["ai-scientist.v1"],
            "capabilities": [],
            "projection": "scientific-cycle.v1",
            "cursors": [],
        },
    )


def start_cycle() -> str:
    return action(
        "cycle.start",
        idempotency_key="create-1",
        payload={
            "creation_idempotency_key": "create-1",
            "expected_revision": 0,
            "raw_question": "Question?",
            "contract_version": "ai-scientist.v1",
            "boundary": {"kind": "cognitive_only", "description": "local"},
            "creator": CREATOR,
        },
    )


def resume_cycle(cycle_id: str) -> str:
    return action(
        "cycle.resume",
        cycle_id=cycle_id,
        payload={
            "client_instance_id": CLIENT_ID,
            "request_ordinal": 1,
            "cycle_id": cycle_id,
            "cursor": {"cycle_id": cycle_id, "sequence": 0, "event_hash": GENESIS_HASH},
            "projection": "full",
        },
    )


def scientific_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({
        "ai_scientist": {
            "enabled": True,
            "protocol_capability": True,
            "allow_new_cycles": True,
            "allow_external_result_import": False,
            "emergency_read_only": False,
        }
    }), encoding="utf-8")
    return home


def read_line(process: subprocess.Popen[str], timeout: float = 5) -> str:
    stdout = process.stdout
    assert stdout is not None
    lines: Queue[str] = Queue(maxsize=1)
    reader = Thread(target=lambda: lines.put(stdout.readline()), daemon=True)
    reader.start()
    return lines.get(timeout=timeout)


def stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=2)


def test_installed_cli_readiness_and_reconnect_persistence(tmp_path: Path) -> None:
    # Given an installed CLI serving a temporary scientific home on port zero
    home = scientific_home(tmp_path)
    process = subprocess.Popen(
        [str(WEB_EXECUTABLE), "--host", "127.0.0.1", "--port", "0", "--scientific-home", str(home)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # When one connection starts a cycle and a fresh connection resumes it
        readiness = json.loads(read_line(process))
        with connect(readiness["url"]) as first:
            first.send(hello("hello-1"))
            assert json.loads(first.recv())["name"] == "protocol.welcome.response"
            first.send(start_cycle())
            started = json.loads(first.recv())
            cycle_id = started["cycle_id"]
        with connect(readiness["url"]) as second:
            second.send(hello("hello-2"))
            assert json.loads(second.recv())["name"] == "protocol.welcome.response"
            second.send(resume_cycle(cycle_id))
            resumed = json.loads(second.recv())
    finally:
        _, stderr = stop_process(process)

    # Then readiness is connectable, durable state survives reconnect, and SIGINT is clean
    assert readiness == {
        "event": "muchanipo_web.ready",
        "host": "127.0.0.1",
        "port": readiness["port"],
        "url": f"ws://127.0.0.1:{readiness['port']}",
    }
    assert readiness["port"] > 0
    assert resumed["name"] == "cycle.resume.response"
    assert resumed["cycle_id"] == cycle_id
    assert process.returncode == 130, stderr


def test_sigint_closes_active_connection_and_exits_130(tmp_path: Path) -> None:
    # Given an installed CLI with one negotiated client still connected
    home = scientific_home(tmp_path)
    process = subprocess.Popen(
        [str(WEB_EXECUTABLE), "--host", "127.0.0.1", "--port", "0", "--scientific-home", str(home)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        readiness = json.loads(read_line(process))
        with connect(readiness["url"]) as client:
            client.send(hello("hello-active"))
            assert json.loads(client.recv())["name"] == "protocol.welcome.response"

            # When the process receives SIGINT before the client disconnects
            process.send_signal(signal.SIGINT)
            try:
                stdout, stderr = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)
                pytest.fail("muchanipo-web did not exit while a client remained connected")
    finally:
        if process.poll() is None:
            stop_process(process)

    # Then shutdown closes the active connection and preserves the CLI exit contract
    assert process.returncode == 130
    assert stdout == ""
    assert stderr == ""


def test_sigint_closes_pending_handshake_and_exits_130(tmp_path: Path) -> None:
    # Given an installed CLI with a TCP client stalled mid-WebSocket handshake
    home = scientific_home(tmp_path)
    process = subprocess.Popen(
        [str(WEB_EXECUTABLE), "--host", "127.0.0.1", "--port", "0", "--scientific-home", str(home)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pending = None

    try:
        readiness = json.loads(read_line(process))
        parsed_url = urlsplit(readiness["url"])
        assert parsed_url.hostname is not None
        assert parsed_url.port is not None
        pending = create_connection((parsed_url.hostname, parsed_url.port), timeout=2)
        pending.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n")

        # A completed second handshake proves the accept loop handled the pending socket.
        with connect(readiness["url"]):
            pass

        # When the process receives SIGINT before the first handshake completes
        process.send_signal(signal.SIGINT)
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=2)
            pytest.fail("muchanipo-web did not exit while a handshake remained pending")
    finally:
        if pending is not None:
            pending.close()
        if process.poll() is None:
            stop_process(process)

    # Then shutdown closes the pending socket and preserves the CLI exit contract
    assert process.returncode == 130
    assert stdout == ""
    assert stderr == ""


@pytest.mark.parametrize("port", [-1, 65536])
def test_cli_rejects_invalid_ports_before_readiness(port: int) -> None:
    # Given a port outside the valid TCP range
    command = [str(WEB_EXECUTABLE), "--port", str(port)]

    # When the installed CLI parses its arguments
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=False)

    # Then argparse rejects it before a readiness record is emitted
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "0..65535" in completed.stderr


def test_cli_rejects_non_loopback_host_before_readiness() -> None:
    # Given a bind address that would expose the local sidecar to the network
    command = [str(WEB_EXECUTABLE), "--host", "0.0.0.0", "--port", "0"]

    # When the installed CLI parses its arguments
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=False)

    # Then argparse rejects it before exposing a listener or readiness record
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "loopback" in completed.stderr


def test_cli_rejects_invalid_config_before_readiness(tmp_path: Path) -> None:
    # Given a scientific home with malformed JSON configuration
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text("{", encoding="utf-8")

    # When the installed CLI starts
    completed = subprocess.run(
        [str(WEB_EXECUTABLE), "--port", "0", "--scientific-home", str(home)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    # Then it fails before exposing a listener or readiness record
    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "invalid JSON scientific config" in completed.stderr
