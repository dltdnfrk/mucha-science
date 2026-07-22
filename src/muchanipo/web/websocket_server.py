from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from ipaddress import ip_address
import json
from socket import socket as Socket
from threading import Lock
from typing import Protocol

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve
from websockets.typing import Origin

from src.pipeline.cycle_repository import CycleRepository

from .protocol_handler import ProtocolHandler
from .scientific_config import ScientificConfig, _load_scientific_config


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_MESSAGE_SIZE = 1_048_576
BINARY_CLOSE_CODE = 1003
BINARY_CLOSE_REASON = "binary frames are unsupported"
ALLOWED_ORIGINS: tuple[Origin | None, ...] = (
    None,
    Origin("http://127.0.0.1:1420"),
    Origin("http://localhost:1420"),
    Origin("http://tauri.localhost"),
    Origin("https://tauri.localhost"),
    Origin("tauri://localhost"),
)


@dataclass(frozen=True, slots=True)
class NonLoopbackHostError(ValueError):
    host: str

    def __str__(self) -> str:
        return f"host must be a loopback address or localhost: {self.host}"


class _Connection(Protocol):
    def __iter__(self) -> Iterator[str | bytes]: ...
    def send(self, message: str) -> None: ...
    def close(self, code: int, reason: str) -> None: ...


class _MessageHandler(Protocol):
    def handle_line(self, line: str) -> list[str]: ...


class _HandlerFactory(Protocol):
    def __call__(
        self,
        *,
        repository: CycleRepository,
        scientific_config: ScientificConfig | None,
    ) -> _MessageHandler: ...


class WebSocketServer:
    def __init__(
        self,
        *,
        repository: CycleRepository,
        scientific_config: ScientificConfig | None,
        host: str,
        port: int,
        handler_factory: _HandlerFactory,
    ) -> None:
        self._repository = repository
        self._scientific_config = scientific_config
        self._handler_factory = handler_factory
        self._connections: set[ServerConnection] = set()
        self._connection_lock = Lock()
        self._shutting_down = False
        self._server = serve(
            self._handle_connection,
            host,
            port,
            max_size=MAX_MESSAGE_SIZE,
            origins=ALLOWED_ORIGINS,
        )

    @property
    def socket(self) -> Socket:
        return self._server.socket

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        with self._connection_lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            connections = tuple(self._connections)
        self._server.shutdown()
        for connection in connections:
            connection.close_socket()

    def _handle_connection(self, connection: ServerConnection) -> None:
        with self._connection_lock:
            if self._shutting_down:
                connection.close_socket()
                return
            self._connections.add(connection)
        try:
            handler = self._handler_factory(
                repository=self._repository,
                scientific_config=self._scientific_config,
            )
            serve_websocket_connection(connection, handler)
        except ConnectionClosed:
            with self._connection_lock:
                if not self._shutting_down:
                    raise
        finally:
            with self._connection_lock:
                self._connections.discard(connection)


def serve_websocket_connection(
    connection: _Connection,
    handler: _MessageHandler,
) -> None:
    for message in connection:
        if isinstance(message, bytes):
            connection.close(BINARY_CLOSE_CODE, BINARY_CLOSE_REASON)
            return
        for response in handler.handle_line(message):
            connection.send(response)


def create_websocket_server(
    *,
    repository: CycleRepository,
    scientific_config: ScientificConfig | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    handler_factory: _HandlerFactory | None = None,
) -> WebSocketServer:
    _require_loopback_host(host)
    resolved_factory = handler_factory or ProtocolHandler
    return WebSocketServer(
        repository=repository,
        scientific_config=scientific_config,
        host=host,
        port=port,
        handler_factory=resolved_factory,
    )


def _port(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be in range 0..65535")
    return port


def _require_loopback_host(host: str) -> str:
    if host == "localhost":
        return host
    try:
        address = ip_address(host)
    except ValueError:
        raise NonLoopbackHostError(host) from None
    if not address.is_loopback:
        raise NonLoopbackHostError(host)
    return host


def _host(value: str) -> str:
    try:
        return _require_loopback_host(value)
    except NonLoopbackHostError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="muchanipo-web",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST, type=_host)
    parser.add_argument("--port", default=DEFAULT_PORT, type=_port)
    parser.add_argument("--scientific-home", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    scientific_config = _load_scientific_config(args.scientific_home)
    repository = CycleRepository(args.scientific_home)
    server = create_websocket_server(
        repository=repository,
        scientific_config=scientific_config,
        host=args.host,
        port=args.port,
    )
    try:
        actual_port = server.socket.getsockname()[1]
        readiness = {
            "event": "muchanipo_web.ready",
            "host": args.host,
            "port": actual_port,
            "url": f"ws://{args.host}:{actual_port}",
        }
        print(json.dumps(readiness, separators=(",", ":")), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 130
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
