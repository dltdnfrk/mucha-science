"""Transport-agnostic ai-scientist.v1 dispatch extracted from ``server.scientific_serve``.

`ProtocolHandler` owns the per-connection state (negotiation, client/server
instance ids, request/ack ordinals, replay blocking) that used to live in the
stdio loop and turns one input JSONL line into zero or more output JSONL lines,
byte-identical to the lines the legacy loop wrote to stdout. Transports (the
stdin/stdout adapter in ``server.scientific_serve`` today, a web transport
later) only move bytes to and from the handler.

Corpus note: ``config/protocol/ai-scientist.v1/bytes/corpus.jsonl`` contains
invalid UTF-8 byte vectors and is exercisable only over the stdio adapter,
which reads raw bytes; it must never be replayed over WS text frames, which
are required to be valid UTF-8.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any

from ..events import SCIENTIFIC_PROTOCOL_VERSION
from src.pipeline.cycle_repository import CycleRepository
from src.pipeline.scientific_contracts import deterministic_id
from .protocol_dispatch import dispatch_protocol_line
from .scientific_config import _scientific_config


class ProtocolHandler:
    """Per-connection ai-scientist.v1 dispatch; transport-agnostic.

    Feed one input JSONL line to `handle_line`; it returns the output JSONL
    lines (without trailing newlines) in the exact order the legacy stdio
    loop emitted them, including snapshot lines emitted before the welcome
    response on a hello cursor mismatch. Typed repository errors become
    error envelopes; unexpected exceptions propagate to the caller unchanged.
    """

    def __init__(
        self,
        *,
        repository: CycleRepository,
        scientific_config: Mapping[str, Any] | None = None,
    ) -> None:
        self.repository = repository
        self.config = _scientific_config(scientific_config)
        self.negotiated = False
        self.client_instance_id: str | None = None
        self.request_ordinals: dict[str, int] = {}
        self.ack_ordinals: dict[str, int] = {}
        self.replay_blocked: set[str] = set()
        self.server_instance_id = deterministic_id(
            "server",
            {"implementation": "muchanipo", "protocol": SCIENTIFIC_PROTOCOL_VERSION},
        )

    def handle_line(self, line: str) -> list[str]:
        """Dispatch one input JSONL line; return emitted output JSONL lines."""
        stream = io.StringIO()
        self._dispatch(line, stream)
        # Not splitlines(): envelopes are serialized with ensure_ascii=False, so
        # payload strings may legally contain U+2028/U+2029 (and other unicode
        # line breaks splitlines() honors), which would tear one envelope into
        # invalid fragments. Every emitter terminates with exactly one "\n",
        # so splitting on "\n" and dropping the trailing empty piece is exact.
        value = stream.getvalue()
        return value.split("\n")[:-1] if value else []

    def _dispatch(self, line: str, stdout: io.StringIO) -> None:
        dispatch_protocol_line(self, line, stdout)
