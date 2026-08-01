"""Registration, entry-point discovery, and version probing for tool adapters."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Mapping

from .adapter import ToolAdapter
from .contract import ToolIdentity


@dataclass(frozen=True)
class InvocationConfig:
    adapter_id: str
    contract_version: str
    adapter_build_sha256: str
    dependency_lock_sha256: str
    reproducibility_mode: str
    container_digest: str | None = None
    tolerance_profile_sha256: str | None = None


@dataclass(frozen=True)
class RegisteredAdapter:
    config: InvocationConfig
    adapter: ToolAdapter
    identity: ToolIdentity


class AdapterRegistry:
    """An explicit registry with optional standard Python entry-point discovery."""

    ENTRY_POINT_GROUP = "mucha_science.tool_adapters"

    def __init__(self) -> None:
        self._adapters: dict[str, tuple[InvocationConfig, ToolAdapter]] = {}
        self._probed: dict[str, RegisteredAdapter] = {}

    def register(self, config: InvocationConfig, adapter: ToolAdapter) -> None:
        if not config.adapter_id or config.adapter_id in self._adapters:
            raise ValueError(f"duplicate or empty adapter id: {config.adapter_id!r}")
        self._adapters[config.adapter_id] = (config, adapter)

    def discover(self, configs: Mapping[str, InvocationConfig]) -> tuple[str, ...]:
        """Load configured adapter factories from the frozen entry-point group."""
        discovered: list[str] = []
        selected = entry_points(group=self.ENTRY_POINT_GROUP)
        for point in sorted(selected, key=lambda item: item.name):
            if point.name not in configs:
                continue
            factory = point.load()
            self.register(configs[point.name], factory())
            discovered.append(point.name)
        return tuple(discovered)

    def probe(self, adapter_id: str) -> RegisteredAdapter:
        if adapter_id in self._probed:
            return self._probed[adapter_id]
        try:
            config, adapter = self._adapters[adapter_id]
        except KeyError as exc:
            raise KeyError(f"unknown adapter: {adapter_id}") from exc
        identity = adapter.probe_version()
        if not isinstance(identity, ToolIdentity):
            raise TypeError("adapter probe_version() must return ToolIdentity")
        registered = RegisteredAdapter(config, adapter, identity)
        self._probed[adapter_id] = registered
        return registered

    def probe_all(self) -> tuple[RegisteredAdapter, ...]:
        return tuple(self.probe(adapter_id) for adapter_id in sorted(self._adapters))
