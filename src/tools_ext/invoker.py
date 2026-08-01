"""The sole subprocess boundary for external computational tool adapters."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any, Mapping

from src.pipeline.scientific_contracts import byte_digest, canonical_json

from .adapter import ParsedResult
from .contract import InvocationRecord, StagedRunArtifact, ToolContractError
from .registry import InvocationConfig, RegisteredAdapter
from .staging import stage_run


@dataclass(frozen=True)
class InvocationResult:
    record: InvocationRecord
    artifact: StagedRunArtifact
    parsed: ParsedResult | None


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _file_digest(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError:
        return None


def _resolve_executable(command: list[str]) -> tuple[str | None, str | None]:
    if not command or not isinstance(command[0], str) or not command[0]:
        return None, None
    resolved = shutil.which(command[0])
    return resolved, _file_digest(resolved) if resolved is not None else None


def _environment() -> dict[str, Any]:
    system = platform.system().lower() or "unknown"
    machine = platform.machine().lower() or "unknown"
    cpu = platform.processor().strip() or machine
    gpu = None
    # These variables are stable, explicit runtime declarations when GPU runtimes expose them.
    if os.environ.get("CUDA_VISIBLE_DEVICES") not in (None, "", "-1"):
        gpu = f"cuda:{os.environ['CUDA_VISIBLE_DEVICES']}"
    versions = {"python": platform.python_version()}
    base = {
        "os_arch": f"{system}/{machine}",
        "cpu": cpu,
        "gpu": gpu,
        "driver_runtime_versions": versions,
    }
    return {**base, "environment_manifest_sha256": byte_digest(canonical_json(base))}


def _raw_bytes(stdout: bytes, stderr: bytes) -> bytes:
    """Unambiguously frame raw streams while preserving their exact bytes."""
    return len(stdout).to_bytes(8, "big") + stdout + len(stderr).to_bytes(8, "big") + stderr


class ToolInvoker:
    """Execute a probed adapter, record provenance, and stage every outcome."""

    def __init__(self, staging_root: str | Path, *, timeout_seconds: float | None = None) -> None:
        self._staging_root = Path(staging_root)
        self._timeout_seconds = timeout_seconds

    def invoke(
        self,
        registered: RegisteredAdapter,
        request: Mapping[str, Any],
        *,
        full_parameters: Mapping[str, Any],
        requested_seed: int,
        seed_handling: str,
        inputs: Mapping[str, bytes],
        source_snapshot_ids: tuple[str, ...] = (),
    ) -> InvocationResult:
        if not isinstance(request, Mapping) or not isinstance(full_parameters, Mapping):
            raise ToolContractError("request and full_parameters must be canonical objects")
        canonical_json(request)
        canonical_json(full_parameters)
        if (not isinstance(inputs, Mapping) or any(
                not isinstance(name, str) or not name or not isinstance(raw, bytes)
                for name, raw in inputs.items())):
            raise ToolContractError("inputs must map nonempty names to bytes")

        config = registered.config
        adapter = registered.adapter
        limitations = adapter.limitations()
        limitation_profile = [item.to_dict() for item in limitations]
        limitation_hash = byte_digest(canonical_json(limitation_profile))
        input_manifest = [
            {"name": name, "byte_size": len(inputs[name]), "sha256": byte_digest(inputs[name])}
            for name in sorted(inputs)
        ]
        input_hash = byte_digest(canonical_json(input_manifest))
        parameter_hash = byte_digest(canonical_json(full_parameters))

        started_at = _timestamp()
        stdout = b""
        stderr = b""
        returncode: int | None = None
        status = "FAILED"
        parsed: ParsedResult | None = None
        command: list[str] = []
        try:
            command = adapter.build_command(request)
            if (not isinstance(command, list) or not command
                    or any(not isinstance(part, str) or not part for part in command)):
                raise ValueError("adapter produced an invalid command")
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self._timeout_seconds,
            )
            stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
            if returncode == 0:
                parsed = adapter.parse_output(stdout)
                if not isinstance(parsed, ParsedResult):
                    raise TypeError("adapter parse_output() must return ParsedResult")
                status = "SUCCEEDED"
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            status = "CANCELLED"
        except (OSError, TypeError, ValueError, ToolContractError) as exc:
            stderr = stderr + (f"{type(exc).__name__}: {exc}").encode("utf-8", errors="replace")
            status = "FAILED"
            parsed = None
        completed_at = _timestamp()

        _, executable_hash = _resolve_executable(command)
        canonical_value: Any
        if status == "SUCCEEDED" and parsed is not None:
            canonical_value = parsed.canonical_output
        else:
            canonical_value = {
                "returncode": returncode,
                "stderr_sha256": byte_digest(stderr),
                "status": status,
            }
        canonical_bytes = canonical_json(canonical_value)
        raw_framed = _raw_bytes(stdout, stderr)
        tool = {
            "name": registered.identity.name,
            "reported_version": registered.identity.reported_version,
            "executable_sha256": executable_hash,
            "container_digest": config.container_digest,
            "dependency_lock_sha256": config.dependency_lock_sha256,
        }
        adapter_info = {
            "id": config.adapter_id,
            "contract_version": config.contract_version,
            "build_sha256": config.adapter_build_sha256,
        }
        provisional = InvocationRecord(
            invocation_id="sha256:" + "0" * 64,
            adapter=adapter_info,
            tool=tool,
            environment=_environment(),
            full_parameters=full_parameters,
            parameter_sha256=parameter_hash,
            requested_seed=requested_seed,
            seed_handling=seed_handling,
            input_manifest_sha256=input_hash,
            source_snapshot_ids=source_snapshot_ids,
            raw_output_sha256=byte_digest(raw_framed),
            canonical_output_sha256=byte_digest(canonical_bytes),
            limitation_profile_sha256=limitation_hash,
            reproducibility_mode=config.reproducibility_mode,
            tolerance_profile_sha256=config.tolerance_profile_sha256,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
        )
        record = replace(provisional, invocation_id=provisional.content_hash)
        artifact = stage_run(self._staging_root, record, (stdout, stderr, canonical_bytes))
        return InvocationResult(record, artifact, parsed)


__all__ = ["InvocationConfig", "InvocationResult", "ToolInvoker"]
