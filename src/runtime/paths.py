"""Shared runtime path resolution for MuchaNipo scripts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional


ENV_VAULT_PATH = "MUCHANIPO_VAULT_PATH"
ENV_MUCHANIPO_HOME = "MUCHANIPO_HOME"
DEFAULT_MUCHANIPO_HOME = Path.home() / ".muchanipo"
DEFAULT_VAULT_PATH = Path.home() / "Documents" / "Hyunjun"
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "config.json"
RUBRIC_PATH = REPO_ROOT / "config" / "rubric.json"


def get_repo_root() -> Path:
    return REPO_ROOT


def _confined_child_path(base: Path, parts: tuple[str, ...]) -> Path:
    root = base.resolve()
    for part in parts:
        child = Path(part)
        if child.is_absolute() or ".." in child.parts:
            raise ValueError(f"path child must not be absolute or traverse parents: {part!r}")

    path = root.joinpath(*parts).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("path child escapes its configured root") from exc
    return path


def get_muchanipo_home(*parts: str, create: bool = False) -> Path:
    """Return the CWD-independent Muchanipo data root plus child parts."""
    raw = os.environ.get(ENV_MUCHANIPO_HOME)
    base = Path(os.path.expanduser(os.path.expandvars(raw))) if raw else DEFAULT_MUCHANIPO_HOME
    path = _confined_child_path(base, parts)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path



def get_config_path() -> Path:
    return CONFIG_PATH


def get_rubric_path() -> Path:
    return RUBRIC_PATH


def get_vault_path(*parts: str, create: bool = False) -> Path:
    """Return the configured Obsidian vault root plus optional child parts."""
    raw = os.environ.get(ENV_VAULT_PATH)
    base = Path(os.path.expandvars(os.path.expanduser(raw))) if raw else DEFAULT_VAULT_PATH
    path = _confined_child_path(base, parts)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_vault_path_setting(value: Optional[str], *, create: bool = False) -> Path:
    """Resolve config vault paths containing ${MUCHANIPO_VAULT_PATH}.

    Empty values and unresolved env placeholders fall back to the configured
    vault root so JSON config can stay portable across machines.
    """
    if not value:
        return get_vault_path(create=create)

    expanded = os.path.expanduser(os.path.expandvars(value))
    placeholder = f"${{{ENV_VAULT_PATH}}}"
    if ENV_VAULT_PATH not in os.environ and placeholder in value:
        suffix = value.split(placeholder, 1)[1].lstrip("/\\")
        return get_vault_path(*Path(suffix).parts, create=create)

    path = Path(expanded)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def rubric_score_max(rubric: Mapping[str, Any]) -> int:
    """Return the max score for axes that actively count toward total."""
    axes = rubric.get("axes")
    if isinstance(axes, Mapping):
        total = 0
        for cfg in axes.values():
            if not isinstance(cfg, Mapping):
                total += 10
                continue
            if cfg.get("active_for_score") is False:
                continue
            if float(cfg.get("weight", 1.0) or 0.0) <= 0.0:
                continue
            total += int(cfg.get("max", 10))
        return total
    if isinstance(axes, list):
        return len(axes) * 10
    return 100
