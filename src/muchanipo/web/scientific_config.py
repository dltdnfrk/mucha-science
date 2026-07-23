from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeAlias

from ..events import SCIENTIFIC_ACTIONS


ScientificConfigValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | list["ScientificConfigValue"]
    | dict[str, "ScientificConfigValue"]
)
ScientificConfig: TypeAlias = Mapping[str, ScientificConfigValue]


class ScientificConfigError(RuntimeError):
    """A scientific configuration file exists but cannot be used."""


_SCIENTIFIC_BOOLEAN_POLICIES = (
    "enabled",
    "protocol_capability",
    "allow_new_cycles",
    "allow_external_result_import",
    "emergency_read_only",
)


def _canonical_import_root(root: str) -> Path:
    configured = Path(root)
    if not configured.is_absolute():
        raise ScientificConfigError("ai_scientist.approved_import_roots entries must be absolute paths")
    try:
        canonical = configured.resolve(strict=True)
    except OSError as exc:
        raise ScientificConfigError(
            f"ai_scientist.approved_import_roots entry is inaccessible: {root}"
        ) from exc
    if configured.is_symlink() or configured != canonical or not canonical.is_dir():
        raise ScientificConfigError(
            "ai_scientist.approved_import_roots entries must be canonical non-symlink directories"
        )
    return canonical


def _scientific_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    if config is None:
        source: Mapping[str, Any] = {}
    elif not isinstance(config, Mapping):
        raise ScientificConfigError("scientific config must be a JSON object")
    elif "ai_scientist" in config:
        nested = config["ai_scientist"]
        if not isinstance(nested, Mapping):
            raise ScientificConfigError("ai_scientist section must be a JSON object")
        source = nested
    else:
        source = config
    for name in _SCIENTIFIC_BOOLEAN_POLICIES:
        if name in source and type(source[name]) is not bool:
            raise ScientificConfigError(f"ai_scientist.{name} must be a boolean")
    roots = source.get("approved_import_roots", [])
    if not isinstance(roots, list) or not all(isinstance(root, str) and root for root in roots):
        raise ScientificConfigError("ai_scientist.approved_import_roots must be an array of paths")
    canonical_roots = [_canonical_import_root(root) for root in roots]
    values = {name: source.get(name, False) for name in _SCIENTIFIC_BOOLEAN_POLICIES}
    values["approved_import_roots"] = [str(root) for root in canonical_roots]
    for name, default in (("max_import_bytes", 256 * 1024 * 1024), ("max_import_files", 32)):
        value = source.get(name, default)
        if type(value) is not int or value < 1:
            raise ScientificConfigError(f"ai_scientist.{name} must be a positive integer")
        values[name] = value
    return values


def _approved_import_roots(config: Mapping[str, Any]) -> tuple[Path, ...]:
    approved: list[Path] = []
    for root in config["approved_import_roots"]:
        try:
            approved.append(_canonical_import_root(root))
        except ScientificConfigError:
            return ()
    return tuple(approved)


def _advertised_capabilities(config: Mapping[str, Any]) -> list[str]:
    capabilities = set(SCIENTIFIC_ACTIONS) - {"protocol.hello"}
    if not config["allow_external_result_import"] or not _approved_import_roots(config):
        capabilities.discard("result.submit")
    if config["emergency_read_only"]:
        capabilities -= {"cycle.start", "cycle.continue", "proposal.reject", "validation.adjudicate",
                         "cycle.abort", "export.create", "responsibility.disposition.supersede",
                         "result.submit"}
        capabilities -= {name for name in capabilities if name.startswith("responsibility.") and name.endswith(".disposition")}
    elif not config["allow_new_cycles"]:
        capabilities.discard("cycle.start")
    return sorted(capabilities)


def _load_scientific_config(scientific_home: str | Path | None = None) -> Mapping[str, Any]:
    candidates = []
    if scientific_home is not None:
        candidates.append(Path(scientific_home) / "config.json")
    candidates.append(Path(__file__).resolve().parents[3] / "config" / "config.json")
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ScientificConfigError(f"unable to read scientific config at {path}") from exc
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScientificConfigError(f"invalid JSON scientific config at {path}") from exc
        if not isinstance(value, Mapping):
            raise ScientificConfigError(f"scientific config at {path} must be a JSON object")
        return value
    return {}
