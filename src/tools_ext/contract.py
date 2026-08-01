"""Frozen, canonical contracts for external computational tool invocations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping

from src.pipeline.scientific_contracts import byte_digest, canonical_json

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
_SEED_HANDLING = frozenset({"HONORED", "NOT_SUPPORTED", "IGNORED", "UNKNOWN"})
_REPRODUCIBILITY = frozenset({"CANONICAL_EXACT", "TOLERANCE"})


class ToolContractError(ValueError):
    """Raised when an external-tool contract violates its closed schema."""


def _require_digest(value: str | None, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ToolContractError(f"{field} must be a sha256 digest")


def _exact(value: Mapping[str, Any], fields: set[str], kind: str) -> None:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ToolContractError(f"{kind} fields are frozen")


def _canonical_copy(value: Any) -> Any:
    """Copy through canonical JSON so mutable caller containers cannot alias records."""
    import json

    try:
        return json.loads(canonical_json(value))
    except (TypeError, ValueError) as exc:
        raise ToolContractError("value is not canonical JSON") from exc


@dataclass(frozen=True)
class ToolIdentity:
    name: str
    reported_version: str
    binary_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or not isinstance(self.reported_version, str) or not self.reported_version:
            raise ToolContractError("tool identity requires name and reported version")
        _require_digest(self.binary_sha256, "binary_sha256")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolIdentity":
        _exact(value, {"name", "reported_version", "binary_sha256"}, "ToolIdentity")
        return cls(value["name"], value["reported_version"], value["binary_sha256"])

    @property
    def content_hash(self) -> str:
        return byte_digest(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class ToolLimitation:
    code: str
    description: str
    applies_when: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code or not isinstance(self.description, str) or not self.description:
            raise ToolContractError("tool limitation requires code and description")
        object.__setattr__(self, "applies_when", _canonical_copy(self.applies_when))

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "description": self.description, "applies_when": _canonical_copy(self.applies_when)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolLimitation":
        _exact(value, {"code", "description", "applies_when"}, "ToolLimitation")
        return cls(value["code"], value["description"], value["applies_when"])

    @property
    def content_hash(self) -> str:
        return byte_digest(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class InvocationRecord:
    invocation_id: str
    adapter: Mapping[str, Any]
    tool: Mapping[str, Any]
    environment: Mapping[str, Any]
    full_parameters: Mapping[str, Any]
    parameter_sha256: str
    requested_seed: int
    seed_handling: str
    input_manifest_sha256: str
    source_snapshot_ids: tuple[str, ...]
    raw_output_sha256: str
    canonical_output_sha256: str
    limitation_profile_sha256: str
    reproducibility_mode: str
    tolerance_profile_sha256: str | None
    status: str
    started_at: str
    completed_at: str

    def __post_init__(self) -> None:
        for field in ("adapter", "tool", "environment", "full_parameters"):
            object.__setattr__(self, field, _canonical_copy(getattr(self, field)))
        object.__setattr__(self, "source_snapshot_ids", tuple(self.source_snapshot_ids))
        if not isinstance(self.requested_seed, int) or isinstance(self.requested_seed, bool) or not 0 <= self.requested_seed <= 2**64 - 1:
            raise ToolContractError("requested_seed must be uint64")
        if self.seed_handling not in _SEED_HANDLING or self.reproducibility_mode not in _REPRODUCIBILITY or self.status not in _STATUSES:
            raise ToolContractError("invalid invocation enum value")
        if not all(isinstance(item, str) and item for item in self.source_snapshot_ids):
            raise ToolContractError("source snapshot IDs must be nonempty strings")
        for field in ("invocation_id", "parameter_sha256", "input_manifest_sha256", "raw_output_sha256", "canonical_output_sha256", "limitation_profile_sha256"):
            _require_digest(getattr(self, field), field)
        _require_digest(self.tolerance_profile_sha256, "tolerance_profile_sha256", nullable=True)
        if self.reproducibility_mode == "TOLERANCE" and self.tolerance_profile_sha256 is None:
            raise ToolContractError("TOLERANCE mode requires a tolerance profile")
        if not isinstance(self.started_at, str) or not isinstance(self.completed_at, str) or self.started_at > self.completed_at:
            raise ToolContractError("invocation timestamps are invalid")
        canonical_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "adapter": _canonical_copy(self.adapter),
            "tool": _canonical_copy(self.tool),
            "environment": _canonical_copy(self.environment),
            "full_parameters": _canonical_copy(self.full_parameters),
            "parameter_sha256": self.parameter_sha256,
            "requested_seed": self.requested_seed,
            "seed_handling": self.seed_handling,
            "input_manifest_sha256": self.input_manifest_sha256,
            "source_snapshot_ids": list(self.source_snapshot_ids),
            "raw_output_sha256": self.raw_output_sha256,
            "canonical_output_sha256": self.canonical_output_sha256,
            "limitation_profile_sha256": self.limitation_profile_sha256,
            "reproducibility_mode": self.reproducibility_mode,
            "tolerance_profile_sha256": self.tolerance_profile_sha256,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvocationRecord":
        fields = {
            "invocation_id", "adapter", "tool", "environment", "full_parameters",
            "parameter_sha256", "requested_seed", "seed_handling", "input_manifest_sha256",
            "source_snapshot_ids", "raw_output_sha256", "canonical_output_sha256",
            "limitation_profile_sha256", "reproducibility_mode", "tolerance_profile_sha256",
            "status", "started_at", "completed_at",
        }
        _exact(value, fields, "InvocationRecord")
        if not isinstance(value["source_snapshot_ids"], (list, tuple)):
            raise ToolContractError("source_snapshot_ids must be an array")
        return cls(**{**dict(value), "source_snapshot_ids": tuple(value["source_snapshot_ids"])})

    def identity_payload(self) -> dict[str, Any]:
        value = self.to_dict()
        for field in ("invocation_id", "started_at", "completed_at"):
            value.pop(field)
        return value

    @property
    def content_hash(self) -> str:
        return byte_digest(canonical_json(self.identity_payload()))


@dataclass(frozen=True)
class StagedRunArtifact:
    artifact_id: str
    manifest_sha256: str
    output_sha256s: tuple[str, ...]
    staging_path: str

    def __post_init__(self) -> None:
        _require_digest(self.artifact_id, "artifact_id")
        _require_digest(self.manifest_sha256, "manifest_sha256")
        if self.artifact_id != self.manifest_sha256:
            raise ToolContractError("staged artifact ID must equal its manifest digest")
        object.__setattr__(self, "output_sha256s", tuple(self.output_sha256s))
        for value in self.output_sha256s:
            _require_digest(value, "output_sha256")
        if not isinstance(self.staging_path, str) or not self.staging_path:
            raise ToolContractError("staging_path is required")

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "manifest_sha256": self.manifest_sha256,
                "output_sha256s": list(self.output_sha256s), "staging_path": self.staging_path}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StagedRunArtifact":
        _exact(value, {"artifact_id", "manifest_sha256", "output_sha256s", "staging_path"}, "StagedRunArtifact")
        if not isinstance(value["output_sha256s"], (list, tuple)):
            raise ToolContractError("output_sha256s must be an array")
        return cls(value["artifact_id"], value["manifest_sha256"], tuple(value["output_sha256s"]), value["staging_path"])

    @property
    def content_hash(self) -> str:
        return self.artifact_id
