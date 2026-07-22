from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
import json
from typing import Protocol

from websockets.sync.server import Server, ServerConnection, serve

from src.pipeline.cycle_repository import CycleRepository

from .protocol_handler import ProtocolHandler
from .scientific_config import ScientificConfig, _load_scientific_config


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_MESSAGE_SIZE = 1_048_576
BINARY_CLOSE_CODE = 1003
BINARY_CLOSE_REASON = "binary frames are unsupported"


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
) -> Server:
    resolved_factory = handler_factory or ProtocolHandler

    def handle_connection(connection: ServerConnection) -> None:
        handler = resolved_factory(
            repository=repository,
            scientific_config=scientific_config,
        )
        serve_websocket_connection(connection, handler)

    return serve(
        handle_connection,
        host,
        port,
        max_size=MAX_MESSAGE_SIZE,
    )


def _port(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be in range 0..65535")
    return port


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="muchanipo-web",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=_port)
    parser.add_argument("--scientific-home", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    scientific_config = _load_scientific_config(args.scientific_home)
    repository = CycleRepository(args.scientific_home)
    with create_websocket_server(
        repository=repository,
        scientific_config=scientific_config,
        host=args.host,
        port=args.port,
    ) as server:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
