from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading
from typing import Callable

import pytest

import src.muni.collection as collection_module
from src.muni.collection import (
    AdapterResult,
    collect_for_study,
    load_collected_data,
    load_collection_jobs,
)
from src.muni.study import create_study, save_study
from src.muni_contracts import CollectionJobStatus, Study


@dataclass
class SyntheticAdapter:
    source: str
    license_decision: str
    transport: Callable[[Study], AdapterResult]

    def __call__(self, study: Study) -> AdapterResult:
        return self.transport(study)


def _result(source: str) -> AdapterResult:
    return AdapterResult(f"{source}-record", f"{source}-payload".encode())


def test_three_adapters_collect_concurrently_and_record_transitions(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropA", "pathogenX", "purposeAlpha")
    save_study(study)

    entered = threading.Barrier(4)
    release = threading.Event()

    def synchronized(source: str) -> Callable[[Study], AdapterResult]:
        def transport(study_arg: Study) -> AdapterResult:
            assert study_arg is study
            entered.wait(timeout=2)
            assert release.wait(timeout=2)
            return _result(source)

        return transport

    adapters = [
        SyntheticAdapter(source, "ALLOWED", synchronized(source))
        for source in ("source-a", "source-b", "source-c")
    ]
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(collect_for_study, study, adapters, max_workers=3)
        entered.wait(timeout=2)
        release.set()
        jobs = future.result(timeout=2)

    assert [job.source_ref for job in jobs] == [adapter.source for adapter in adapters]
    assert all(job.status is CollectionJobStatus.SUCCEEDED for job in jobs)
    assert all(job.started_at and job.finished_at and job.result_ref for job in jobs)
    history = load_collection_jobs(study)
    for source in ("source-a", "source-b", "source-c"):
        assert [job.status for job in history if job.source_ref == source] == [
            CollectionJobStatus.PENDING,
            CollectionJobStatus.RUNNING,
            CollectionJobStatus.SUCCEEDED,
        ]


def test_concurrent_collection_calls_do_not_lose_persisted_records(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropA", "pathogenX", "purposeAlpha")
    initial_reads = threading.Barrier(2)
    adapters_entered = threading.Barrier(3)
    original_load = collection_module.load_collection_jobs

    def synchronized_load(study_arg: Study, root=None):
        records = original_load(study_arg, root=root)
        initial_reads.wait(timeout=2)
        return records

    monkeypatch.setattr(collection_module, "load_collection_jobs", synchronized_load)

    def adapter(source: str) -> SyntheticAdapter:
        def transport(_: Study) -> AdapterResult:
            adapters_entered.wait(timeout=2)
            return _result(source)

        return SyntheticAdapter(source, "ALLOWED", transport)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(collect_for_study, study, [adapter(source)])
            for source in ("request-a", "request-b")
        ]
        adapters_entered.wait(timeout=2)
        for future in futures:
            [job] = future.result(timeout=2)
            assert job.status is CollectionJobStatus.SUCCEEDED

    history = load_collection_jobs(study)
    assert {
        (job.source_ref, job.status)
        for job in history
    } == {
        (source, status)
        for source in ("request-a", "request-b")
        for status in (
            CollectionJobStatus.PENDING,
            CollectionJobStatus.RUNNING,
            CollectionJobStatus.SUCCEEDED,
        )
    }
    assert {item.source_record_ref for item in load_collected_data(study)} == {
        "request-a-record",
        "request-b-record",
    }


def test_deferred_source_without_allowed_decision_is_explicitly_skipped(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropA", "pathogenX", "purposeAlpha")
    calls: list[str] = []
    adapter = SyntheticAdapter(
        "chembl", "DENIED", lambda _: calls.append("transport") or _result("chembl")
    )

    [job] = collect_for_study(study, [adapter])

    assert job.status is CollectionJobStatus.SKIPPED
    assert job.started_at and job.finished_at
    assert job.result_ref is None
    assert job.reason and "DEFERRED" in job.reason and "DENIED" in job.reason
    assert calls == []


def test_deferred_source_with_allowed_decision_runs(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropB", "pathogenY", "purposeBeta")
    calls: list[str] = []
    adapter = SyntheticAdapter(
        "chembl", "ALLOWED", lambda _: calls.append("transport") or _result("chembl")
    )

    [job] = collect_for_study(study, [adapter])

    assert job.status is CollectionJobStatus.SUCCEEDED
    assert calls == ["transport"]


def test_one_raising_adapter_fails_without_cancelling_other_jobs(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropC", "pathogenZ", "purposeGamma")

    def malformed(_: Study) -> AdapterResult:
        raise ValueError("malformed adapter payload")

    adapters = [
        SyntheticAdapter("good-a", "ALLOWED", lambda _: _result("good-a")),
        SyntheticAdapter("bad", "ALLOWED", malformed),
        SyntheticAdapter("good-b", "ALLOWED", lambda _: _result("good-b")),
    ]

    jobs = collect_for_study(study, adapters, max_workers=3)

    by_source = {job.source_ref: job for job in jobs}
    assert by_source["good-a"].status is CollectionJobStatus.SUCCEEDED
    assert by_source["good-b"].status is CollectionJobStatus.SUCCEEDED
    assert by_source["bad"].status is CollectionJobStatus.FAILED
    assert by_source["bad"].reason == "ValueError: malformed adapter payload"
    assert by_source["bad"].finished_at


def test_collected_data_round_trips_from_the_study_store(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropD", "pathogenQ", "purposeDelta")
    save_study(study)

    [job] = collect_for_study(
        study,
        [SyntheticAdapter("source-a", "ALLOWED", lambda _: _result("source-a"))],
    )
    loaded = load_collected_data(study)

    assert len(loaded) == 1
    assert loaded[0].job_ref in {
        snapshot.job_id
        for snapshot in load_collection_jobs(study)
        if snapshot.status is CollectionJobStatus.RUNNING
    }
    assert loaded[0].source_record_ref == "source-a-record"
    assert loaded[0].digest.startswith("sha256:")
    assert job.result_ref == loaded[0].content_hash
    assert (tmp_path / "studies" / f"{study.study_id}.collected-data.json").is_file()


def test_only_injected_transport_is_called(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropE", "pathogenR", "purposeEpsilon")
    calls: list[tuple[str, str]] = []

    def injected(study_arg: Study) -> AdapterResult:
        calls.append((study_arg.target_crop, study_arg.target_pathogen))
        return _result("offline")

    jobs = collect_for_study(
        study, [SyntheticAdapter("offline", "ALLOWED", injected)], max_workers=1
    )

    assert calls == [("cropE", "pathogenR")]
    assert jobs[0].status is CollectionJobStatus.SUCCEEDED
