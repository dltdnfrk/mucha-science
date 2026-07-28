"""Shared policy for local CLI-backed model providers.

Muchanipo is primarily a personal local app. Prefer installed CLIs for that
path, but never read provider OAuth/token files directly; auth stays owned by
the provider CLI.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
_UNTRUSTED_SOURCE_MARKERS = (
    "## untrusted source data",
    "<untrusted_source",
    "<untrusted-source",
)


@dataclass(frozen=True, slots=True)
class UnsafeCliPromptError(RuntimeError):
    detail: str

    def __str__(self) -> str:
        return self.detail


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUE_VALUES


def cli_requested(provider_flag: str) -> bool:
    return env_truthy(provider_flag) or env_truthy("MUCHANIPO_USE_CLI")


def prefer_cli_default() -> bool:
    raw = os.environ.get("MUCHANIPO_PREFER_CLI")
    if raw is None:
        return False
    return raw.strip().lower() not in FALSE_VALUES


def assert_cli_prompt_safe(prompt: str) -> None:
    normalized = prompt.casefold()
    if any(marker in normalized for marker in _UNTRUSTED_SOURCE_MARKERS):
        raise UnsafeCliPromptError(
            "untrusted source data cannot be sent to a repository-aware CLI",
        )


def writable_workdir(*, env_var: str, app_name: str = "muchanipo") -> str:
    explicit = os.environ.get(env_var)
    if explicit:
        Path(explicit).mkdir(parents=True, exist_ok=True)
        return explicit

    cwd = Path.cwd()
    if os.access(str(cwd), os.W_OK):
        return str(cwd)

    fallback = Path.home() / ".local" / "share" / app_name / "cli-workdir"
    fallback.mkdir(parents=True, exist_ok=True)
    return str(fallback)
