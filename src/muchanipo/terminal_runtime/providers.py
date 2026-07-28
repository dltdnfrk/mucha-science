from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, IO, Protocol

from .contracts import JSON_SCHEMA_VERSION


class ProviderResponse(Protocol):
    text: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class UnsupportedProviderProbeError(Exception):
    provider: str

    def __str__(self) -> str:
        return f"unsupported provider probe {self.provider!r}"


def resolve_cli_path(name: str, env_var: str) -> str | None:
    explicit = os.environ.get(env_var)
    if explicit:
        return explicit
    if name == "codex":
        candidates = ("/opt/homebrew/bin/codex", "/usr/local/bin/codex", shutil.which("codex"))
        return next(
            (candidate for candidate in candidates if candidate and Path(candidate).exists()),
            None,
        )
    return shutil.which(name)


def first_error_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:160]
    return ""


def cli_statuses(
    *,
    path_resolver: Callable[[str, str], str | None] = resolve_cli_path,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    specs = [
        ("claude", "CLAUDE_BIN", ["--version"]),
        ("codex", "CODEX_BIN", ["--version"]),
        ("gemini", "GEMINI_BIN", ["--version"]),
        ("kimi", "KIMI_BIN", ["--version"]),
        ("opencode", "OPENCODE_BIN", ["--version"]),
    ]
    statuses: list[dict[str, Any]] = []
    for name, env_var, version_args in specs:
        path = path_resolver(name, env_var)
        record: dict[str, Any] = {
            "name": name,
            "installed": bool(path),
            "path": path,
            "version": None,
            "error": None,
        }
        if path:
            try:
                process = run_command(
                    [path, *version_args],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                output = (process.stdout or process.stderr or "").strip()
                if process.returncode == 0:
                    record["version"] = output.splitlines()[0] if output else "installed"
                else:
                    record["error"] = first_error_line(output) or f"exit {process.returncode}"
            except (OSError, subprocess.SubprocessError) as exc:
                record["error"] = first_error_line(str(exc))
        statuses.append(record)
    return statuses


def cli_prompt_probes(
    records: list[dict[str, Any]] | None = None,
    *,
    timeout_sec: int | None = None,
    status_loader: Callable[[], list[dict[str, Any]]] = cli_statuses,
    probe_caller: Callable[..., ProviderResponse] | None = None,
) -> list[dict[str, Any]]:
    timeout = timeout_sec or int(os.environ.get("MUCHANIPO_PROVIDER_PROBE_TIMEOUT_SEC", "90"))
    provider_records = list(records if records is not None else status_loader())
    caller = probe_caller or call_provider_probe

    def probe_one(item: dict[str, Any]) -> dict[str, Any]:
        name = str(item.get("name") or "")
        path = item.get("path")
        record: dict[str, Any] = {
            "name": name,
            "installed": bool(item.get("installed")),
            "prompt_ok": False,
            "json_ok": False,
            "latency_ms": None,
            "provider": None,
            "model": None,
            "error": None,
        }
        if not path:
            record["error"] = "not installed"
            return record
        prompt = (
            'Return exactly this JSON and nothing else: '
            f'{{"ok":true,"provider":"{name}","probe":"muchanipo"}}'
        )
        started = time.monotonic()
        try:
            result = caller(name=name, path=str(path), prompt=prompt, timeout=timeout)
            record["latency_ms"] = round((time.monotonic() - started) * 1000)
            record["prompt_ok"] = bool(str(result.text or "").strip())
            record["provider"] = result.provider
            record["model"] = result.model
            payload = extract_json_object(result.text)
            record["json_ok"] = bool(payload and payload.get("ok") is True)
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - provider boundary reports host CLI failures.
            record["latency_ms"] = round((time.monotonic() - started) * 1000)
            record["error"] = first_error_line(str(exc)) or type(exc).__name__
        return record

    probes: list[dict[str, Any] | None] = [None] * len(provider_records)
    max_workers = max(1, min(5, len(provider_records)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(probe_one, item): index
            for index, item in enumerate(provider_records)
        }
        for future in as_completed(futures):
            probes[futures[future]] = future.result()
    return [item for item in probes if item is not None]


def render_cli_status(
    *,
    stdout: IO[str] | None = None,
    probe: bool = False,
    status_loader: Callable[[], list[dict[str, Any]]] = cli_statuses,
    prompt_loader: Callable[..., list[dict[str, Any]]] = cli_prompt_probes,
) -> list[dict[str, Any]]:
    out = stdout or sys.stdout
    statuses = status_loader()
    out.write("\nCLI status\n----------\n")
    for item in statuses:
        marker = "OK" if item["installed"] else "--"
        detail = item.get("version")
        if not detail and item["installed"] and item.get("error"):
            detail = f"installed; version probe failed: {item['error']}"
        out.write(f"[{marker}] {item['name']:<8} {detail or 'not found'}\n")
        out.write(f"     {item.get('path') or '-'}\n")
    if probe:
        out.write("\nPrompt probes\n")
        for item in prompt_loader(statuses):
            marker = "OK" if item.get("prompt_ok") and item.get("json_ok") else "WARN"
            detail = (
                f"prompt={item.get('prompt_ok')} json={item.get('json_ok')}"
                f" latency={item.get('latency_ms')}ms"
            )
            if item.get("error"):
                detail += f" error={item['error']}"
            out.write(f"[{marker}] {item['name']:<8} {detail}\n")
    out.write("\n")
    out.flush()
    return statuses


def status_report(
    *,
    probe: bool = False,
    status_loader: Callable[[], list[dict[str, Any]]] = cli_statuses,
    prompt_loader: Callable[..., list[dict[str, Any]]] = cli_prompt_probes,
) -> dict[str, Any]:
    providers = status_loader()
    report: dict[str, Any] = {
        "schema_version": JSON_SCHEMA_VERSION,
        "command": "muchanipo status",
        "providers": providers,
        "probe_requested": bool(probe),
    }
    if probe:
        report["prompt_probes"] = prompt_loader(providers)
    return report


def call_provider_probe(
    *,
    name: str,
    path: str,
    prompt: str,
    timeout: int,
) -> ProviderResponse:
    if name == "claude":
        from src.execution.providers.anthropic import AnthropicProvider

        return AnthropicProvider(offline=False, use_cli=True, claude_bin=path).call(
            "eval", prompt, timeout=timeout, allow_fallback=False
        )
    if name == "codex":
        from src.execution.providers.codex import CodexProvider

        return CodexProvider(offline=False, use_cli=True, codex_bin=path).call(
            "eval", prompt, timeout=timeout
        )
    if name == "gemini":
        from src.execution.providers.gemini import GeminiProvider

        return GeminiProvider(offline=False, use_cli=True, gemini_bin=path).call(
            "eval", prompt, timeout=timeout, search_grounding=False
        )
    if name == "kimi":
        from src.execution.providers.kimi import KimiProvider

        return KimiProvider(offline=False, use_cli=True, kimi_bin=path).call(
            "eval", prompt, timeout=timeout
        )
    if name == "opencode":
        from src.execution.providers.opencode import OpenCodeProvider

        return OpenCodeProvider(offline=False, use_cli=True, opencode_bin=path).call(
            "eval", prompt, timeout=timeout
        )
    raise UnsupportedProviderProbeError(name)


def extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None
