"""Fail-closed admission of staged tool runs through the cycle repository writer."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping

from src.pipeline.external_result_ingest import ImportQuota, stage_external_result
from src.pipeline.scientific_contracts import (
    ContractError,
    byte_digest,
    canonical_json,
    decode_json_object,
)

from .contract import InvocationRecord, ToolContractError
from .registry import AdapterRegistry


_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")


class AdmissionError(ValueError):
    """A staged run could not be verified or atomically admitted."""


class VerificationError(AdmissionError):
    """A staged run violates the frozen tool-run admission contract."""


@dataclass(frozen=True)
class AdmissionQuota:
    """Strict limits applied before any staged bytes reach permanent storage."""

    max_outputs: int = 32
    max_manifest_bytes: int = 1024 * 1024
    max_output_bytes: int = 64 * 1024 * 1024
    max_total_output_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        values = (
            self.max_outputs,
            self.max_manifest_bytes,
            self.max_output_bytes,
            self.max_total_output_bytes,
        )
        if (any(not isinstance(value, int) or isinstance(value, bool) or value < 1
                for value in values)
                or self.max_total_output_bytes < self.max_output_bytes):
            raise AdmissionError("invalid admission quota")


@dataclass(frozen=True)
class VerifiedArtifact:
    path: Path
    manifest_sha256: str
    output_sha256s: tuple[str, ...]
    output_paths: tuple[Path, ...]
    invocation: InvocationRecord


@dataclass(frozen=True)
class AdmissionResult:
    admitted: bool
    artifact_path: str
    invocation: InvocationRecord | None
    repository_response: bytes | None
    reason: str | None = None


class Verifier:
    """Verify an untrusted staged-run directory without changing it."""

    def __init__(self, registry: AdapterRegistry, quota: AdmissionQuota = AdmissionQuota()) -> None:
        self._registry = registry
        self._quota = quota

    @staticmethod
    def _hash_regular_file(path: Path, limit: int) -> tuple[str, int]:
        if path.is_symlink() or not path.is_file():
            raise VerificationError("output must be a regular non-symlink file")
        size = path.stat().st_size
        if size > limit:
            raise VerificationError("output exceeds admission quota")
        digest = hashlib.sha256()
        copied = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                copied += len(chunk)
                if copied > limit:
                    raise VerificationError("output exceeds admission quota during verification")
                digest.update(chunk)
        if copied != size or path.stat().st_size != size:
            raise VerificationError("output changed during verification")
        return "sha256:" + digest.hexdigest(), size

    @staticmethod
    def _require_version(value: Any, field: str) -> None:
        if not isinstance(value, str) or not _VERSION.fullmatch(value):
            raise VerificationError(f"{field} is not a well-formed version string")

    def verify(self, staged_artifact_dir: str | Path) -> VerifiedArtifact:
        path = Path(staged_artifact_dir)
        manifest_path = path / "manifest.json"
        output_dir = path / "outputs"
        try:
            if path.is_symlink() or not path.is_dir():
                raise VerificationError("staged artifact must be a real directory")
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise VerificationError("manifest must be a regular non-symlink file")
            manifest_size = manifest_path.stat().st_size
            if manifest_size > self._quota.max_manifest_bytes:
                raise VerificationError("manifest exceeds admission quota")
            manifest_bytes = manifest_path.read_bytes()
            if len(manifest_bytes) != manifest_size:
                raise VerificationError("manifest changed during verification")
            try:
                manifest = decode_json_object(manifest_bytes)
                if canonical_json(manifest) != manifest_bytes:
                    raise VerificationError("manifest is not canonical JSON")
            except ContractError as exc:
                raise VerificationError("manifest schema is invalid") from exc
            if (set(manifest) != {"schema_version", "invocation", "outputs"}
                    or manifest.get("schema_version") != "mucha-science.tool-run.v1"
                    or not isinstance(manifest.get("invocation"), Mapping)
                    or not isinstance(manifest.get("outputs"), list)):
                raise VerificationError("manifest schema is invalid")
            try:
                invocation = InvocationRecord.from_dict(manifest["invocation"])
            except (KeyError, TypeError, ValueError, ToolContractError) as exc:
                raise VerificationError("invocation manifest schema is invalid") from exc
            outputs = manifest["outputs"]
            if (not outputs or len(outputs) > self._quota.max_outputs
                    or any(not isinstance(item, Mapping) or set(item) != {"sha256"}
                           for item in outputs)):
                raise VerificationError("output manifest schema or quota is invalid")
            output_sha256s = tuple(item["sha256"] for item in outputs)
            if len(output_sha256s) != 3:
                raise VerificationError("invoker output manifest schema is invalid")

            manifest_sha256 = byte_digest(manifest_bytes)
            if path.name != manifest_sha256.removeprefix("sha256:"):
                raise VerificationError("manifest digest does not match staged artifact identity")
            if output_dir.is_symlink() or not output_dir.is_dir():
                raise VerificationError("outputs must be a real directory")
            expected_names = {digest.removeprefix("sha256:") for digest in output_sha256s}
            if {item.name for item in output_dir.iterdir()} != expected_names:
                raise VerificationError("output store does not match manifest digests")

            output_paths: list[Path] = []
            total = 0
            for expected in output_sha256s:
                output_path = output_dir / expected.removeprefix("sha256:")
                actual, size = self._hash_regular_file(output_path, self._quota.max_output_bytes)
                if actual != expected:
                    raise VerificationError("output digest does not match actual bytes")
                total += size
                if total > self._quota.max_total_output_bytes:
                    raise VerificationError("outputs exceed total admission quota")
                output_paths.append(output_path)

            self._verify_invocation(invocation, tuple(output_paths))
            return VerifiedArtifact(
                path, manifest_sha256, output_sha256s, tuple(output_paths), invocation,
            )
        except VerificationError:
            raise
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise VerificationError("staged artifact is malformed or changed") from exc

    def _verify_invocation(self, invocation: InvocationRecord,
                           output_paths: tuple[Path, ...]) -> None:
        if invocation.invocation_id != invocation.content_hash:
            raise VerificationError("invocation identity digest is invalid")
        if byte_digest(canonical_json(invocation.full_parameters)) != invocation.parameter_sha256:
            raise VerificationError("parameter digest does not match invocation parameters")
        adapter = invocation.adapter
        tool = invocation.tool
        environment = invocation.environment
        if (set(adapter) != {"id", "contract_version", "build_sha256"}
                or set(tool) != {"name", "reported_version", "executable_sha256",
                                "container_digest", "dependency_lock_sha256"}
                or set(environment) != {"os_arch", "cpu", "gpu", "driver_runtime_versions",
                                        "environment_manifest_sha256"}):
            raise VerificationError("invocation nested schema is invalid")
        self._require_version(adapter["contract_version"], "adapter contract_version")
        self._require_version(tool["reported_version"], "tool reported_version")
        for field, value, nullable in (
            ("adapter build_sha256", adapter["build_sha256"], False),
            ("tool executable_sha256", tool["executable_sha256"], True),
            ("tool container_digest", tool["container_digest"], True),
            ("tool dependency_lock_sha256", tool["dependency_lock_sha256"], False),
        ):
            if not (nullable and value is None) and (
                    not isinstance(value, str) or not _DIGEST.fullmatch(value)):
                raise VerificationError(f"{field} is not a sha256 digest")
        if (not _TIMESTAMP.fullmatch(invocation.started_at)
                or not _TIMESTAMP.fullmatch(invocation.completed_at)):
            raise VerificationError("invocation timestamps are not canonical UTC timestamps")
        adapter_id = adapter.get("id")
        if not isinstance(adapter_id, str):
            raise VerificationError("adapter is not registered")
        try:
            registered = self._registry.probe(adapter_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise VerificationError("adapter is not registered") from exc
        config = registered.config
        expected_adapter = {
            "id": config.adapter_id,
            "contract_version": config.contract_version,
            "build_sha256": config.adapter_build_sha256,
        }
        if (adapter != expected_adapter
                or invocation.reproducibility_mode != config.reproducibility_mode
                or invocation.tolerance_profile_sha256 != config.tolerance_profile_sha256):
            raise VerificationError("registered adapter configuration is stale")
        if (tool["name"] != registered.identity.name
                or tool["reported_version"] != registered.identity.reported_version
                or tool["container_digest"] != config.container_digest
                or tool["dependency_lock_sha256"] != config.dependency_lock_sha256):
            raise VerificationError("registered tool identity is stale")
        limitation_hash = byte_digest(canonical_json(
            [item.to_dict() for item in registered.adapter.limitations()]
        ))
        if invocation.limitation_profile_sha256 != limitation_hash:
            raise VerificationError("limitation profile digest is stale")
        environment_base = {
            key: value for key, value in environment.items()
            if key != "environment_manifest_sha256"
        }
        if byte_digest(canonical_json(environment_base)) != environment["environment_manifest_sha256"]:
            raise VerificationError("environment manifest digest is invalid")
        stdout = output_paths[0].read_bytes()
        stderr = output_paths[1].read_bytes()
        canonical_output = output_paths[2].read_bytes()
        framed_raw = len(stdout).to_bytes(8, "big") + stdout + len(stderr).to_bytes(8, "big") + stderr
        if byte_digest(framed_raw) != invocation.raw_output_sha256:
            raise VerificationError("raw output digest is invalid")
        if byte_digest(canonical_output) != invocation.canonical_output_sha256:
            raise VerificationError("canonical output digest is invalid")


class Admission:
    """The only tools-ext component allowed to invoke the repository ledger writer."""

    def __init__(
        self,
        registry: AdapterRegistry,
        repository: Any,
        *,
        permanent_root: str | Path,
        quarantine_root: str | Path,
        quota: AdmissionQuota = AdmissionQuota(),
    ) -> None:
        self._verifier = Verifier(registry, quota)
        self._repository = repository
        self._permanent_root = Path(permanent_root)
        self._quarantine_root = Path(quarantine_root)
        self._quota = quota

    @staticmethod
    def _real_root(root: Path, name: str) -> None:
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise AdmissionError(f"{name} must be a real directory")

    def _quarantine(self, source: Path, reason: str) -> Path:
        self._real_root(self._quarantine_root, "quarantine root")
        stem = source.name or "unknown-artifact"
        destination = self._quarantine_root / stem
        ordinal = 1
        while destination.exists() or destination.is_symlink():
            destination = self._quarantine_root / f"{stem}.{ordinal}"
            ordinal += 1
        if source.exists() and source.is_dir() and not source.is_symlink():
            os.replace(source, destination)
        else:
            destination.mkdir()
            if source.exists() or source.is_symlink():
                os.replace(source, destination / "staged-artifact")
        # Do not create files inside an attacker-controlled rejected directory:
        # it may contain a same-named symlink. The structured result carries the reason.
        return destination

    @staticmethod
    def _same_artifact(first: VerifiedArtifact, second: VerifiedArtifact) -> bool:
        return (
            first.manifest_sha256 == second.manifest_sha256
            and first.output_sha256s == second.output_sha256s
            and first.invocation == second.invocation
        )

    def admit(self, staged_artifact_dir: str | Path,
              command: Mapping[str, Any]) -> AdmissionResult:
        source = Path(staged_artifact_dir)
        try:
            verified = self._verifier.verify(source)
        except Exception as exc:
            reason = str(exc) or type(exc).__name__
            quarantined = self._quarantine(source, reason)
            return AdmissionResult(False, str(quarantined), None, None, reason)

        permanent = self._permanent_root / verified.manifest_sha256.removeprefix("sha256:")
        moved_to_permanent = False
        duplicate_source = False
        try:
            self._real_root(self._permanent_root, "permanent root")
            if permanent.exists() or permanent.is_symlink():
                existing = self._verifier.verify(permanent)
                if not self._same_artifact(verified, existing):
                    raise AdmissionError("permanent artifact conflicts with staged content")
                duplicate_source = source != permanent
            else:
                os.replace(source, permanent)
                moved_to_permanent = True
            permanent_verified = self._verifier.verify(permanent)
            response = self._submit(permanent_verified, command)
            if duplicate_source and source.exists():
                shutil.rmtree(source)
            return AdmissionResult(
                True, str(permanent), permanent_verified.invocation, response, None,
            )
        except Exception as exc:
            reason = str(exc) or type(exc).__name__
            rejected_source = permanent if moved_to_permanent else source
            quarantined = self._quarantine(rejected_source, reason)
            return AdmissionResult(False, str(quarantined), verified.invocation, None, reason)

    def _submit(self, verified: VerifiedArtifact, command: Mapping[str, Any]) -> bytes:
        handoff_parent = self._permanent_root / ".ledger-handoff"
        self._real_root(handoff_parent, "ledger handoff root")
        handoff = Path(tempfile.mkdtemp(prefix="admission-", dir=handoff_parent))
        import_quota = ImportQuota(
            max_files=self._quota.max_outputs,
            max_file_bytes=self._quota.max_output_bytes,
            max_total_bytes=self._quota.max_total_output_bytes,
        )
        try:
            staged = stage_external_result(
                staged_files=verified.output_paths,
                approved_roots=(verified.path / "outputs",),
                staging_root=handoff,
                quota=import_quota,
            )
            try:
                mutable_command = decode_json_object(canonical_json(command))
                payload = mutable_command["payload"]
                if not isinstance(payload, dict):
                    raise AdmissionError("repository command payload must be an object")
                payload["execution_kind"] = "computational"
                payload["started_at"] = verified.invocation.started_at
                payload["completed_at"] = verified.invocation.completed_at
                payload["staged_blob_ids"] = list(staged["staged_blob_ids"])
                invocation_projection = verified.invocation.to_dict()
                # Protocol v1 reserves ``*_id`` values for 32-hex protocol IDs,
                # while tool invocation identities are SHA-256 digests. Preserve
                # the complete record under an unambiguous digest field so the
                # frozen repository ingress can validate it without weakening
                # either contract.
                invocation_projection["invocation_sha256"] = invocation_projection.pop("invocation_id")
                payload["result_manifest"] = {
                    "schema_version": "mucha-science.admitted-invocation.v1",
                    "invocation": invocation_projection,
                    "manifest_sha256": verified.manifest_sha256,
                    "output_sha256s": list(verified.output_sha256s),
                }
            except (ContractError, KeyError, TypeError, ValueError) as exc:
                raise AdmissionError("repository command is malformed") from exc
            return self._repository.submit_external_result(
                mutable_command, staging_root=handoff, quota=import_quota,
            )
        finally:
            shutil.rmtree(handoff, ignore_errors=True)
            try:
                handoff_parent.rmdir()
            except OSError:
                pass


__all__ = [
    "Admission", "AdmissionError", "AdmissionQuota", "AdmissionResult",
    "VerificationError", "VerifiedArtifact", "Verifier",
]
