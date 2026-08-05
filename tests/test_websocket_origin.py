from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Thread

import pytest
from websockets.exceptions import InvalidStatus
from websockets.protocol import State
from websockets.sync.client import connect
from websockets.typing import Origin

from src.muchanipo.web.websocket_server import NonLoopbackHostError, create_websocket_server
from src.pipeline.cycle_repository import CycleRepository


@contextmanager
def running_server(home: Path) -> Iterator[str]:
    server = create_websocket_server(
        repository=CycleRepository(home),
        host="127.0.0.1",
        port=0,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    port = server.socket.getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_server_rejects_untrusted_browser_origin(tmp_path: Path) -> None:
    # Given a live server that owns mutable scientific-cycle state
    with running_server(tmp_path / "home") as url:
        # When an unrelated website attempts a cross-site WebSocket handshake
        with pytest.raises(InvalidStatus) as raised:
            connect(url, origin=Origin("https://attacker.example"))

    # Then the handshake is rejected before any protocol action can execute
    assert raised.value.response.status_code == 403


def test_server_rejects_non_loopback_bind(tmp_path: Path) -> None:
    # Given a host that would expose mutable state beyond the local machine
    server = None
    try:
        # When the server factory is asked to bind every IPv4 interface
        with pytest.raises(NonLoopbackHostError):
            server = create_websocket_server(
                repository=CycleRepository(tmp_path / "home"),
                host="0.0.0.0",
                port=0,
            )
    finally:
        if server is not None:
            server.shutdown()


def test_server_accepts_installed_app_ephemeral_loopback_origin(tmp_path: Path) -> None:
    # Given the installed macOS app serves its UI from a random loopback port
    with running_server(tmp_path / "home") as url:
        # When that browser surface opens the pipeline WebSocket
        with connect(url, origin=Origin("http://127.0.0.1:65202")) as client:
            # Then the app-owned browser origin completes the handshake
            assert client.state is State.OPEN


@pytest.mark.parametrize("origin", [
    Origin("http://127.0.0.1:4173"),
    Origin("http://localhost:4173"),
    Origin("http://127.0.0.1:5173"),
    Origin("http://localhost:5173"),
])
def test_server_accepts_muchanipo_browser_origins(tmp_path: Path, origin: Origin) -> None:
    # Given a live server and a local web UI browser origin
    with running_server(tmp_path / "home") as url:
        # When the browser negotiates from one of the explicit application origins
        with connect(url, origin=origin) as client:
            # Then the application origin completes the WebSocket handshake
            assert client.state is State.OPEN
