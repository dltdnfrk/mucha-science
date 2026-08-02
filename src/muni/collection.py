"""Parallel, transport-injected data collection for MUNI studies."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Iterable, Mapping, Protocol, runtime_checkable

from src.muni._store import append_json_records, read_json_array
from src.muni.study import _root, save_study
from src.muni_contracts import CollectedData, CollectionJob, CollectionJobStatus, Study
from src.platform_contracts import canonical_json
from src.source_adapters import SourcePolicyError, activation_verdict

_DEFAULT_MAX_WORKERS = 8


@dataclass(frozen=True)
class AdapterResult:
    """A source record identifier and the exact bytes collected for it."""

    source_record_ref: str
    payload: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.source_record_ref, str) or not self.source_record_ref:
            raise ValueError("source_record_ref must be a nonempty string")
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be bytes")


@runtime_checkable
class CollectionAdapter(Protocol):
    """Runtime shape accepted by :func:`collect_for_study`."""

    source: str
    license_decision: str

    def __call__(self, study: Study) -> AdapterResult: ...


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _paths(study: Study, root: str | Path | None = None) -> tuple[Path, Path]:
    registry_root = _root(root)
    base = registry_root / "studies" / study.study_id
    return (
        base.with_name(f"{study.study_id}.collection-jobs.json"),
        base.with_name(f"{study.study_id}.collected-data.json"),
    )


def load_collection_jobs(
    study: Study, root: str | Path | None = None
) -> tuple[CollectionJob, ...]:
    """Load the persisted lifecycle snapshots for a study in transition order."""
    jobs_path, _ = _paths(study, root)
    return tuple(
        CollectionJob.from_payload(item)  # type: ignore[arg-type]
        for item in read_json_array(jobs_path, require_objects=True)
    )


def load_collected_data(
    study: Study, root: str | Path | None = None
) -> tuple[CollectedData, ...]:
    """Load collected-data metadata persisted beside a study."""
    _, data_path = _paths(study, root)
    return tuple(
        CollectedData.from_payload(item)  # type: ignore[arg-type]
        for item in read_json_array(data_path, require_objects=True)
    )


def _job(
    study: Study,
    source: str,
    status: CollectionJobStatus,
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    result_ref: str | None = None,
    reason: str | None = None,
) -> CollectionJob:
    return CollectionJob(
        job_id="",
        study_ref=study.study_id,
        source_ref=source,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        result_ref=result_ref,
        reason=reason,
    )


def _source(adapter: object) -> str:
    source = getattr(adapter, "source", getattr(adapter, "source_ref", None))
    if not isinstance(source, str) or not source:
        raise ValueError("each adapter must declare a nonempty source or source_ref")
    return source


def _invoke(adapter: object, study: Study) -> object:
    if callable(adapter):
        return adapter(study)
    collect = getattr(adapter, "collect", None)
    if callable(collect):
        return collect(study)
    raise TypeError("adapter must be callable or expose collect(study)")


def _collected(result: object, running_job: CollectionJob, source: str) -> CollectedData:
    if isinstance(result, AdapterResult):
        source_record_ref = result.source_record_ref
        digest = "sha256:" + hashlib.sha256(result.payload).hexdigest()
    elif isinstance(result, CollectedData):
        source_record_ref = result.source_record_ref
        digest = result.digest
    elif isinstance(result, Mapping):
        source_record_ref = result.get("source_record_ref")
        supplied_digest = result.get("digest")
        if supplied_digest is not None:
            digest = supplied_digest
        elif "payload" in result:
            payload = result["payload"]
            raw = payload if isinstance(payload, bytes) else canonical_json(payload)
            digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        else:
            raise ValueError("adapter result needs digest or payload")
    elif isinstance(result, tuple) and len(result) == 2:
        source_record_ref, payload = result
        raw = payload if isinstance(payload, bytes) else canonical_json(payload)
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    elif isinstance(result, bytes):
        source_record_ref = source
        digest = "sha256:" + hashlib.sha256(result).hexdigest()
    else:
        raise TypeError(
            "adapter must return AdapterResult, CollectedData, a result mapping, "
            "a (source_record_ref, payload) tuple, or bytes"
        )
    return CollectedData(
        job_ref=running_job.job_id,
        source_record_ref=source_record_ref,  # type: ignore[arg-type]
        digest=digest,  # type: ignore[arg-type]
    )


def collect_for_study(
    study: Study,
    adapters: Iterable[object],
    *,
    max_workers: int = _DEFAULT_MAX_WORKERS,
) -> list[CollectionJob]:
    """Run one license-gated collection job per adapter concurrently.

    Adapters receive the immutable Study and provide their own transport. Their
    lifecycle snapshots and CollectedData metadata are persisted beside the
    Study. A source failure is represented by a FAILED job and does not cancel
    other sources.
    """
    if not isinstance(study, Study):
        raise TypeError("study must be a Study")
    if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")

    registered = list(adapters)
    sources = [_source(adapter) for adapter in registered]
    study_path = save_study(study)
    jobs_path = study_path.with_name(f"{study.study_id}.collection-jobs.json")
    data_path = study_path.with_name(f"{study.study_id}.collected-data.json")
    pending = [_job(study, source, CollectionJobStatus.PENDING) for source in sources]
    append_json_records(
        jobs_path, *(job.to_payload() for job in pending), require_objects=True
    )

    finals: list[CollectionJob | None] = [None] * len(registered)

    def run(index: int, adapter: object, source: str) -> None:
        started_at = _timestamp()
        running = _job(
            study, source, CollectionJobStatus.RUNNING, started_at=started_at
        )
        append_json_records(jobs_path, running.to_payload(), require_objects=True)

        decision = getattr(adapter, "license_decision", "UNKNOWN")
        try:
            activation_verdict(source, license_decision=decision)
        except SourcePolicyError as exc:
            final = _job(
                study,
                source,
                CollectionJobStatus.SKIPPED,
                started_at=started_at,
                finished_at=_timestamp(),
                reason=str(exc),
            )
        else:
            try:
                result = _invoke(adapter, study)
                data = _collected(result, running, source)
                final = _job(
                    study,
                    source,
                    CollectionJobStatus.SUCCEEDED,
                    started_at=started_at,
                    finished_at=_timestamp(),
                    result_ref=data.content_hash,
                )
            except Exception as exc:
                message = str(exc)
                reason = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
                final = _job(
                    study,
                    source,
                    CollectionJobStatus.FAILED,
                    started_at=started_at,
                    finished_at=_timestamp(),
                    reason=reason,
                )
            else:
                append_json_records(data_path, data.to_payload(), require_objects=True)

        append_json_records(jobs_path, final.to_payload(), require_objects=True)
        finals[index] = final

    if registered:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(registered))) as executor:
            futures = [
                executor.submit(run, index, adapter, source)
                for index, (adapter, source) in enumerate(zip(registered, sources))
            ]
            for future in futures:
                future.result()

    return [job for job in finals if job is not None]


__all__ = [
    "AdapterResult",
    "CollectionAdapter",
    "collect_for_study",
    "load_collected_data",
    "load_collection_jobs",
]
