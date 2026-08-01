"""Pure adapter interface: command construction and output interpretation only."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from src.pipeline.scientific_contracts import canonical_json

from .contract import ToolIdentity, ToolLimitation


@dataclass(frozen=True)
class ParsedResult:
    """A tool's canonical, JSON-serializable output projection."""

    canonical_output: Any

    def __post_init__(self) -> None:
        canonical_json(self.canonical_output)


class ToolAdapter(Protocol):
    """Adapters are pure descriptions and parsers; invocation belongs elsewhere."""

    def probe_version(self) -> ToolIdentity: ...

    def limitations(self) -> tuple[ToolLimitation, ...]: ...

    def build_command(self, request: Mapping[str, Any]) -> list[str]: ...

    def parse_output(self, raw: bytes) -> ParsedResult: ...
