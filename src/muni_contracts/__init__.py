"""Immutable contracts for target-agnostic MUNI dry-lab studies.

Wire bytes, hashes, and identifiers use the platform's canonical contract
utilities.  This package models descriptions and handoffs only; it performs no
wet-lab work.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import re
from types import MappingProxyType
from typing import ClassVar, Mapping, Self

from src.platform_contracts import (
    ContractError,
    canonical_json,
    decode_json_object,
    deterministic_id,
    digest,
)

_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class CollectionJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class WorkflowKind(StrEnum):
    DIAGNOSTIC_DISCOVERY = "DIAGNOSTIC_DISCOVERY"
    COMPOUND_SCREENING = "COMPOUND_SCREENING"


class WorkflowStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_MORE = "NEEDS_MORE"


ALL_ENUM_TYPES = (CollectionJobStatus, WorkflowKind, WorkflowStatus, ReviewDecision)


def _plain(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and isinstance(value, _Contract):
        return value.to_content()
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _exact(value: object, name: str, expected: set[str]) -> Mapping[str, object]:
    if (
        not isinstance(value, Mapping)
        or any(not isinstance(key, str) for key in value)
        or set(value) != expected
    ):
        raise ContractError(f"{name} fields are frozen")
    canonical_json(value)
    return value


def _string(value: object, name: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value:
        suffix = " or null" if nullable else ""
        raise ContractError(f"{name} must be a nonempty string{suffix}")
    return value


def _timestamp(value: object, name: str, *, nullable: bool = False) -> str | None:
    text = _string(value, name, nullable=nullable)
    if text is not None and not _TIMESTAMP.fullmatch(text):
        raise ContractError(f"{name} must be a canonical UTC timestamp")
    return text


def _digest(value: object, name: str) -> str:
    text = _string(value, name)
    if text is None or not _DIGEST.fullmatch(text):
        raise ContractError(f"{name} must be a sha256 digest")
    return text


def _enum(enum_type: type[StrEnum], value: object, name: str) -> StrEnum:
    if not isinstance(value, str):
        raise ContractError(f"{name} must be a {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ContractError(f"unknown {enum_type.__name__}: {value}") from exc


def _array(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{name} must be an array")
    result = tuple(value)
    canonical_json(result)
    return result


def _strings(value: object, name: str) -> tuple[str, ...]:
    result = _array(value, name)
    if any(not isinstance(item, str) or not item for item in result):
        raise ContractError(f"{name} must contain nonempty strings")
    return tuple(item for item in result if isinstance(item, str))


class _Contract:
    ID_FIELD: ClassVar[str | None] = None
    ID_KIND: ClassVar[str | None] = None

    def _finish_init(self) -> None:
        for field in fields(self):
            if field.name != self.ID_FIELD:
                object.__setattr__(self, field.name, _freeze(getattr(self, field.name)))
        if self.ID_FIELD is not None and self.ID_KIND is not None:
            object.__setattr__(
                self,
                self.ID_FIELD,
                deterministic_id(self.ID_KIND, {"content_hash": self.content_hash}),
            )

    def to_content(self) -> dict[str, object]:
        return {
            field.name: _plain(getattr(self, field.name))
            for field in fields(self)
            if field.name != self.ID_FIELD
        }

    @property
    def content_hash(self) -> str:
        return digest(self.to_content())

    @property
    def record_id(self) -> str | None:
        return getattr(self, self.ID_FIELD) if self.ID_FIELD is not None else None

    def to_payload(self) -> dict[str, object]:
        content = self.to_content()
        if self.ID_FIELD is None:
            return content
        return {self.ID_FIELD: self.record_id, **content}

    def to_json(self) -> bytes:
        return canonical_json(self.to_payload())

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Self:
        if not isinstance(payload, Mapping):
            raise ContractError(f"{cls.__name__} payload must be an object")
        if cls.ID_FIELD is None:
            return cls.from_content(payload)
        expected = {field.name for field in fields(cls)}
        material = dict(_exact(payload, cls.__name__, expected))
        supplied_id = material.pop(cls.ID_FIELD)
        record = cls.from_content(material)
        if supplied_id != record.record_id:
            raise ContractError(f"{cls.ID_FIELD} does not match canonical content")
        return record

    @classmethod
    def from_json(cls, raw: str | bytes) -> Self:
        value = decode_json_object(raw)
        if not isinstance(value, Mapping):
            raise ContractError(f"{cls.__name__} JSON must be an object")
        return cls.from_payload(value)

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        raise NotImplementedError


@dataclass(frozen=True)
class Study(_Contract):
    ID_FIELD: ClassVar[str] = "study_id"
    ID_KIND: ClassVar[str] = "muni_study"

    study_id: str
    target_crop: str
    target_pathogen: str
    purpose: str
    created_at: str
    pack_ref: str | None

    def __post_init__(self) -> None:
        _string(self.target_crop, "target_crop")
        _string(self.target_pathogen, "target_pathogen")
        _string(self.purpose, "purpose")
        _timestamp(self.created_at, "created_at")
        _string(self.pack_ref, "pack_ref", nullable=True)
        self._finish_init()

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _exact(content, cls.__name__, {"target_crop", "target_pathogen", "purpose", "created_at", "pack_ref"})
        return cls("", value["target_crop"], value["target_pathogen"], value["purpose"], value["created_at"], value["pack_ref"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class TargetSelection(_Contract):
    target_crop: str
    target_pathogen: str
    selected_by: str
    note: str

    def __post_init__(self) -> None:
        _string(self.target_crop, "target_crop")
        _string(self.target_pathogen, "target_pathogen")
        _string(self.selected_by, "selected_by")
        _string(self.note, "note")
        self._finish_init()

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _exact(content, cls.__name__, {"target_crop", "target_pathogen", "selected_by", "note"})
        return cls(value["target_crop"], value["target_pathogen"], value["selected_by"], value["note"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class CollectionJob(_Contract):
    ID_FIELD: ClassVar[str] = "job_id"
    ID_KIND: ClassVar[str] = "muni_collection_job"

    job_id: str
    study_ref: str
    source_ref: str
    status: CollectionJobStatus
    started_at: str | None
    finished_at: str | None
    result_ref: str | None
    reason: str | None

    def __post_init__(self) -> None:
        _string(self.study_ref, "study_ref")
        _string(self.source_ref, "source_ref")
        object.__setattr__(self, "status", _enum(CollectionJobStatus, self.status, "status"))
        _timestamp(self.started_at, "started_at", nullable=True)
        _timestamp(self.finished_at, "finished_at", nullable=True)
        _string(self.result_ref, "result_ref", nullable=True)
        _string(self.reason, "reason", nullable=True)
        self._finish_init()

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"study_ref", "source_ref", "status", "started_at", "finished_at", "result_ref", "reason"}
        value = _exact(content, cls.__name__, names)
        return cls("", value["study_ref"], value["source_ref"], value["status"], value["started_at"], value["finished_at"], value["result_ref"], value["reason"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class CollectedData(_Contract):
    job_ref: str
    source_record_ref: str
    digest: str

    def __post_init__(self) -> None:
        _string(self.job_ref, "job_ref")
        _string(self.source_record_ref, "source_record_ref")
        _digest(self.digest, "digest")
        self._finish_init()

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _exact(content, cls.__name__, {"job_ref", "source_record_ref", "digest"})
        return cls(value["job_ref"], value["source_record_ref"], value["digest"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class WorkflowRun(_Contract):
    ID_FIELD: ClassVar[str] = "run_id"
    ID_KIND: ClassVar[str] = "muni_workflow_run"

    run_id: str
    study_ref: str
    kind: WorkflowKind
    status: WorkflowStatus
    started_at: str
    finished_at: str | None

    def __post_init__(self) -> None:
        _string(self.study_ref, "study_ref")
        object.__setattr__(self, "kind", _enum(WorkflowKind, self.kind, "kind"))
        object.__setattr__(self, "status", _enum(WorkflowStatus, self.status, "status"))
        _timestamp(self.started_at, "started_at")
        _timestamp(self.finished_at, "finished_at", nullable=True)
        self._finish_init()

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _exact(content, cls.__name__, {"study_ref", "kind", "status", "started_at", "finished_at"})
        return cls("", value["study_ref"], value["kind"], value["status"], value["started_at"], value["finished_at"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class CandidateSet(_Contract):
    ID_FIELD: ClassVar[str] = "set_id"
    ID_KIND: ClassVar[str] = "muni_candidate_set"

    set_id: str
    workflow_ref: str
    kind: WorkflowKind
    items: tuple[object, ...]
    count: int

    def __post_init__(self) -> None:
        _string(self.workflow_ref, "workflow_ref")
        object.__setattr__(self, "kind", _enum(WorkflowKind, self.kind, "kind"))
        object.__setattr__(self, "items", _array(self.items, "items"))
        if not isinstance(self.count, int) or isinstance(self.count, bool) or self.count < 0:
            raise ContractError("count must be a nonnegative integer")
        if self.count != len(self.items):
            raise ContractError("count must equal the number of items")
        self._finish_init()

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _exact(content, cls.__name__, {"workflow_ref", "kind", "items", "count"})
        return cls("", value["workflow_ref"], value["kind"], value["items"], value["count"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class ReviewRecord(_Contract):
    ID_FIELD: ClassVar[str] = "review_id"
    ID_KIND: ClassVar[str] = "muni_review"

    review_id: str
    candidate_set_ref: str
    reviewer: str
    decision: ReviewDecision
    note: str
    decided_at: str

    def __post_init__(self) -> None:
        _string(self.candidate_set_ref, "candidate_set_ref")
        _string(self.reviewer, "reviewer")
        object.__setattr__(self, "decision", _enum(ReviewDecision, self.decision, "decision"))
        _string(self.note, "note")
        _timestamp(self.decided_at, "decided_at")
        self._finish_init()

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        names = {"candidate_set_ref", "reviewer", "decision", "note", "decided_at"}
        value = _exact(content, cls.__name__, names)
        return cls("", value["candidate_set_ref"], value["reviewer"], value["decision"], value["note"], value["decided_at"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class WetLabHandoff(_Contract):
    ID_FIELD: ClassVar[str] = "handoff_id"
    ID_KIND: ClassVar[str] = "muni_wet_lab_handoff"

    handoff_id: str
    review_ref: str
    artifact_paths: tuple[str, ...]
    disclaimer: str

    def __post_init__(self) -> None:
        _string(self.review_ref, "review_ref")
        object.__setattr__(self, "artifact_paths", _strings(self.artifact_paths, "artifact_paths"))
        _string(self.disclaimer, "disclaimer")
        self._finish_init()

    @classmethod
    def from_content(cls, content: Mapping[str, object]) -> Self:
        value = _exact(content, cls.__name__, {"review_ref", "artifact_paths", "disclaimer"})
        return cls("", value["review_ref"], value["artifact_paths"], value["disclaimer"])  # type: ignore[arg-type]


__all__ = [
    "ALL_ENUM_TYPES",
    "CandidateSet",
    "CollectedData",
    "CollectionJob",
    "CollectionJobStatus",
    "ContractError",
    "ReviewDecision",
    "ReviewRecord",
    "Study",
    "TargetSelection",
    "WetLabHandoff",
    "WorkflowKind",
    "WorkflowRun",
    "WorkflowStatus",
]
