from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.pipeline.scientific_contracts import byte_digest, canonical_json
from src.tools_ext.adapter import ParsedResult
from src.tools_ext.contract import InvocationRecord, StagedRunArtifact, ToolIdentity, ToolLimitation
from src.tools_ext.invoker import InvocationConfig, ToolInvoker
from src.tools_ext.registry import AdapterRegistry


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def executable_digest(path: str) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


class EchoAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def probe_version(self) -> ToolIdentity:
        executable = "/bin/sh" if self.fail else "/bin/echo"
        return ToolIdentity("shell-echo", "system", executable_digest(executable))

    def limitations(self) -> tuple[ToolLimitation, ...]:
        return (ToolLimitation("text-only", "Emits UTF-8 text only", {"format": "text"}),)

    def build_command(self, request: Mapping[str, Any]) -> list[str]:
        if self.fail:
            return ["/bin/sh", "-c", "printf failure >&2; exit 7"]
        return ["/bin/echo", str(request["message"])]

    def parse_output(self, raw: bytes) -> ParsedResult:
        return ParsedResult({"text": raw.decode("utf-8").rstrip("\n")})


def config() -> InvocationConfig:
    return InvocationConfig(
        adapter_id="test.echo",
        contract_version="tools-ext.v1",
        adapter_build_sha256=SHA_A,
        dependency_lock_sha256=SHA_B,
        reproducibility_mode="CANONICAL_EXACT",
    )


def invoke(tmp_path: Path, adapter: EchoAdapter, *, message: str = "hello"):
    registry = AdapterRegistry()
    registry.register(config(), adapter)
    registered = registry.probe("test.echo")
    return ToolInvoker(tmp_path).invoke(
        registered,
        {"message": message},
        full_parameters={"encoding": "utf-8"},
        requested_seed=42,
        seed_handling="NOT_SUPPORTED",
        inputs={"request.txt": message.encode()},
        source_snapshot_ids=("source_snapshot_01",),
    )


def without_timing(record: InvocationRecord) -> dict[str, Any]:
    value = record.to_dict()
    for field in ("started_at", "completed_at"):
        value.pop(field)
    return value


def test_contract_dataclasses_round_trip_and_hash_stability(tmp_path: Path):
    identity = ToolIdentity("echo", "1", SHA_A)
    limitation = ToolLimitation("small-input", "Only small input", {"max_bytes": 10})
    artifact = StagedRunArtifact(SHA_B, SHA_B, (SHA_A,), str(tmp_path))

    assert ToolIdentity.from_dict(identity.to_dict()) == identity
    assert ToolLimitation.from_dict(limitation.to_dict()) == limitation
    assert StagedRunArtifact.from_dict(artifact.to_dict()) == artifact
    assert identity.content_hash == byte_digest(canonical_json(identity.to_dict()))
    assert limitation.content_hash == byte_digest(canonical_json(limitation.to_dict()))
    assert canonical_json(identity.to_dict()) == canonical_json(ToolIdentity.from_dict(identity.to_dict()).to_dict())


def test_real_echo_adapter_end_to_end_produces_complete_record_and_staging(tmp_path: Path):
    result = invoke(tmp_path, EchoAdapter())
    record = result.record

    assert result.parsed == ParsedResult({"text": "hello"})
    assert record.status == "SUCCEEDED"
    assert record.tool == {
        "name": "shell-echo",
        "reported_version": "system",
        "executable_sha256": executable_digest("/bin/echo"),
        "container_digest": None,
        "dependency_lock_sha256": SHA_B,
    }
    assert set(record.environment) == {
        "os_arch", "cpu", "gpu", "driver_runtime_versions", "environment_manifest_sha256"
    }
    assert record.requested_seed == 42
    assert record.seed_handling == "NOT_SUPPORTED"
    assert record.parameter_sha256 == byte_digest(canonical_json({"encoding": "utf-8"}))
    assert record.input_manifest_sha256.startswith("sha256:")
    assert record.raw_output_sha256.startswith("sha256:")
    assert record.canonical_output_sha256 == byte_digest(canonical_json({"text": "hello"}))
    assert record.invocation_id == record.content_hash
    assert result.artifact.artifact_id == result.artifact.manifest_sha256

    staged = Path(result.artifact.staging_path)
    manifest_bytes = (staged / "manifest.json").read_bytes()
    assert byte_digest(manifest_bytes) == result.artifact.artifact_id
    manifest = json.loads(manifest_bytes)
    assert manifest["invocation"] == record.to_dict()
    assert all(set(output) == {"sha256"} for output in manifest["outputs"])
    for output in manifest["outputs"]:
        blob = staged / "outputs" / output["sha256"].removeprefix("sha256:")
        assert byte_digest(blob.read_bytes()) == output["sha256"]


def test_nonzero_exit_is_failed_without_exception_and_is_staged(tmp_path: Path):
    result = invoke(tmp_path, EchoAdapter(fail=True))

    assert result.record.status == "FAILED"
    assert result.parsed is None
    assert result.record.raw_output_sha256.startswith("sha256:")
    assert result.record.canonical_output_sha256.startswith("sha256:")
    assert (Path(result.artifact.staging_path) / "manifest.json").is_file()


def test_limitation_profile_snapshot_is_hashed_into_record(tmp_path: Path):
    adapter = EchoAdapter()
    expected = byte_digest(canonical_json([item.to_dict() for item in adapter.limitations()]))

    assert invoke(tmp_path, adapter).record.limitation_profile_sha256 == expected


def test_same_inputs_parameters_and_seed_have_identical_record_modulo_timestamps(tmp_path: Path):
    first = invoke(tmp_path / "one", EchoAdapter())
    second = invoke(tmp_path / "two", EchoAdapter())

    assert without_timing(first.record) == without_timing(second.record)
    assert first.record.started_at <= first.record.completed_at
    assert second.record.started_at <= second.record.completed_at
    assert InvocationRecord.from_dict(first.record.to_dict()) == first.record
