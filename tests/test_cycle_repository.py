from __future__ import annotations

import base64
import json
import threading
import shutil

import pytest

from src.pipeline.cycle_repository import CycleRepository, IdempotencyConflict, RepositoryCorrupt, RevisionConflict
from src.pipeline.external_result_ingest import ImportQuota
from src.pipeline.scientific_contracts import GENESIS_HASH, canonical_json, deterministic_id, digest
from src.pipeline.scientific_cycle import CycleError


CREATOR = {"actor_kind": "human", "display_name": "Operator", "organization": None, "role": None,
           "assertion_source": "operator_entry", "verification_status": "operator_asserted_unverified",
           "authority_scope": {"kind": "none", "scope": None}, "external_reference": None}


def envelope(name: str, *, cycle_id: str | None, key: str, payload: dict[str, object],
             message_id: str = "request_00000000000000000000000000000000") -> dict[str, object]:
    return {"protocol": "muchanipo", "protocol_version": "ai-scientist.v1", "kind": "action",
            "name": name, "message_id": message_id, "cycle_id": cycle_id,
            "correlation_id": message_id, "causation_id": None, "sequence": 0, "revision": 0,
            "idempotency_key": key, "timestamp": "2026-07-19T00:00:00.000000Z",
            "payload": payload, "extensions": {}}


def start(key: str = "start-key") -> dict[str, object]:
    return envelope("cycle.start", cycle_id=None, key=key, payload={
        "creation_idempotency_key": key, "expected_revision": 0, "raw_question": "Question?",
        "contract_version": "ai-scientist.v1",
        "boundary": {"kind": "cognitive_only", "description": "local"}, "creator": CREATOR,
    })


def replay_events(repository: CycleRepository, cycle_id: str) -> list[dict[str, object]]:
    return repository.verified_replay(
        cycle_id,
        cursor={"cycle_id": cycle_id, "sequence": 0, "event_hash": GENESIS_HASH},
        max_events=128,
    )["events"]


def test_start_retry_returns_the_original_bytes_and_exactly_one_ledger_event(tmp_path):
    repository = CycleRepository(tmp_path)
    first = repository.start_cycle(start())
    cycle_id = json.loads(first)["cycle_id"]
    first_state = repository.load(cycle_id)
    assert repository.start_cycle(start()) == first
    retried_state = repository.load(cycle_id)
    assert retried_state["revision"] == retried_state["sequence"] == first_state["revision"] == 1
    assert len([event for event in replay_events(repository, cycle_id) if event["idempotency_key"] == "start-key"]) == 1
    with pytest.raises(RevisionConflict):
        repository.execute(envelope("cycle.abort", cycle_id=cycle_id, key="new", payload={
            "expected_revision": 0, "actor": CREATOR, "reason": "stop", "final_observation": "none",
        }))

def test_ledger_frames_do_not_embed_prior_replay_history(tmp_path):
    repository = CycleRepository(tmp_path)
    cycle_id = json.loads(repository.start_cycle(start()))["cycle_id"]
    repository.execute(envelope(
        "cycle.abort",
        cycle_id=cycle_id,
        key="abort-key",
        message_id="request_11111111111111111111111111111111",
        payload={
            "expected_revision": 1,
            "actor": CREATOR,
            "reason": "stop",
            "final_observation": "no physical work was executed",
        },
    ))

    lines = (tmp_path / "cycles" / cycle_id / "ledger.jsonl").read_bytes().splitlines()
    first_frame = json.loads(lines[0])
    second_frame = json.loads(lines[2])
    frozen = second_frame["event"]["extensions"]["frozen_action"]
    receipt = second_frame["event"]["payload"]["command_receipt"]
    response = json.loads(base64.b64decode(receipt["response_envelope_base64"], validate=True))

    assert set(frozen) == {"name", "payload"}
    assert "_events" not in json.dumps(second_frame)
    assert "events" not in response["payload"]
    assert first_frame["event"]["message_id"] not in json.dumps(second_frame)
    assert len(lines[2]) < len(lines[0]) * 3


def test_start_key_content_conflict(tmp_path):
    repository = CycleRepository(tmp_path)
    repository.start_cycle(start())
    changed = start(); changed["payload"]["raw_question"] = "Different?"  # type: ignore[index]
    with pytest.raises(IdempotencyConflict):
        repository.start_cycle(changed)


def test_trailing_frame_is_quarantined_and_snapshot_is_rebuilt(tmp_path):
    repository = CycleRepository(tmp_path)
    response = repository.start_cycle(start())
    cycle_id = json.loads(response)["cycle_id"]
    directory = tmp_path / "cycles" / cycle_id
    ledger = directory / "ledger.jsonl"
    original_ledger = ledger.read_bytes()
    tail = b'{"record_type":"event"'
    ledger.write_bytes(original_ledger + tail)
    (directory / "manifest.json").unlink()
    loaded = repository.load(cycle_id)
    quarantine = directory / "quarantine" / "ledger-tail.jsonl"
    manifest = json.loads((directory / "manifest.json").read_bytes())
    public = {key: value for key, value in loaded.items() if key not in {"_events", "_event_hash"}}
    assert loaded["cycle_id"] == cycle_id
    assert quarantine.read_bytes() == tail
    assert ledger.read_bytes() == original_ledger
    assert manifest["checkpoint"] == {"cycle_id": cycle_id, "sequence": loaded["sequence"], "event_hash": loaded["_event_hash"]}
    assert manifest["state"] == public
    assert manifest["state_hash"] == digest(public)
    checkpoint = manifest["checkpoint"]
    assert manifest["snapshot_id"] == deterministic_id("snapshot", checkpoint)
    assert manifest["snapshot_hash"] == digest(
        {"checkpoint": checkpoint, "state_hash": manifest["state_hash"], "state": public})

def test_load_waits_for_cycle_lock_before_repairing_an_inflight_tail(tmp_path):
    repository = CycleRepository(tmp_path)
    cycle_id = json.loads(repository.start_cycle(start()))["cycle_id"]
    ledger = tmp_path / "cycles" / cycle_id / "ledger.jsonl"
    original = ledger.read_bytes()
    ledger.write_bytes(original + b'{"record_type":"event"')
    started = threading.Event()
    completed = threading.Event()

    def reader() -> None:
        started.set()
        repository.load(cycle_id)
        completed.set()

    with repository._lock(tmp_path / "cycles" / cycle_id / ".lock"):
        thread = threading.Thread(target=reader)
        thread.start()
        assert started.wait(timeout=1)
        assert not completed.wait(timeout=0.05)
        assert ledger.read_bytes() == original + b'{"record_type":"event"'
    thread.join(timeout=1)
    assert completed.is_set()
    assert ledger.read_bytes() == original

def test_start_retry_holds_root_then_waits_for_cycle_lock_before_registry_repair(tmp_path):
    repository = CycleRepository(tmp_path)
    cycle_id = json.loads(repository.start_cycle(start()))["cycle_id"]
    snapshot = tmp_path / "cycles" / cycle_id / "manifest.json"
    snapshot.unlink()
    started = threading.Event()
    completed = threading.Event()

    def retry() -> None:
        started.set()
        repository.start_cycle(start())
        completed.set()

    with repository._lock(tmp_path / "cycles" / cycle_id / ".lock"):
        thread = threading.Thread(target=retry)
        thread.start()
        assert started.wait(timeout=1)
        assert not completed.wait(timeout=0.05)
        assert not snapshot.exists()
    thread.join(timeout=1)
    assert completed.is_set()
    assert snapshot.exists()


def test_unknown_cycle_read_probes_do_not_create_lock_directories(tmp_path):
    repository = CycleRepository(tmp_path)
    cycle_id = "cycle_00000000000000000000000000000000"
    for probe in (
        lambda: repository.load(cycle_id),
        lambda: repository.verified_replay(
            cycle_id,
            cursor={"cycle_id": cycle_id, "sequence": 0, "event_hash": GENESIS_HASH},
            max_events=128,
        ),
        lambda: repository.get_export(cycle_id, include_archive_bytes=False),
        lambda: repository.render_report(
            cycle_id,
            at_revision=0,
            format="markdown",
            include_status_overlay=False,
        ),
        lambda: repository.acknowledge(
            cycle_id,
            checkpoint={"cycle_id": cycle_id, "sequence": 0, "event_hash": GENESIS_HASH},
            state_hash="sha256:" + "0" * 64,
        ),
    ):
        with pytest.raises(FileNotFoundError):
            probe()
    assert not (tmp_path / "cycles" / cycle_id).exists()
def test_cycle_ids_and_malformed_mutations_fail_before_filesystem_mutation(tmp_path):
    repository = CycleRepository(tmp_path)
    for cycle_id in ("/tmp/cycle_00000000000000000000000000000000",
                     "../cycle_00000000000000000000000000000000",
                     "cycle_not-a-protocol-id"):
        with pytest.raises(CycleError):
            repository.load(cycle_id)
    malformed = start()
    malformed.pop("timestamp")
    with pytest.raises(CycleError, match="validated closed protocol envelope"):
        repository.start_cycle(malformed)
    assert not (tmp_path / "cycles").exists()


def test_cycle_directory_symlink_is_rejected_without_lock_mutation(tmp_path):
    repository = CycleRepository(tmp_path)
    cycle_id = "cycle_00000000000000000000000000000000"
    cycles = tmp_path / "cycles"
    cycles.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (cycles / cycle_id).symlink_to(target, target_is_directory=True)
    with pytest.raises(RepositoryCorrupt, match="non-symlink"):
        repository.load(cycle_id)
    assert not (target / ".lock").exists()
def test_rejected_external_result_removes_only_the_newly_created_batch(tmp_path, monkeypatch):
    repository = CycleRepository(tmp_path)
    cycle_id = json.loads(repository.start_cycle(start()))["cycle_id"]
    batch = tmp_path / "cycles" / cycle_id / "external_artifacts" / "external_artifacts_00000000000000000000000000000000"

    class FakeIngest:
        def __init__(self, *args, **kwargs):
            self.created = False

        def ingest_staged(self, **kwargs):
            batch.mkdir(parents=True)
            self.created = True
            return {"result": {}, "artifact_refs": (), "artifact_batch": {"path": str(batch)}}

        def cleanup_created_batch(self, verified):
            if self.created:
                shutil.rmtree(batch)

    monkeypatch.setattr("src.pipeline.cycle_repository.ExternalResultIngest", FakeIngest)
    monkeypatch.setattr(
        "src.pipeline.cycle_repository.resolve_staged_blob_ids",
        lambda **kwargs: (tmp_path / "staged-results" / "result.bin",),
    )
    monkeypatch.setattr(repository, "_verify_external_result_receipt", lambda *args: None)
    monkeypatch.setattr(repository.reducer, "apply_verified_result",
                        lambda *args: (_ for _ in ()).throw(CycleError("gate rejected")))
    reference = {
        "reference_type": "lab_log", "issuer": "External Lab", "title": "Completed run",
        "uri_or_identifier": "lab-log-1", "content_hash": "sha256:" + "b" * 64,
        "assertion_source": "external_reference",
        "verification_status": "external_reference_unverified",
        "authority_scope": {"kind": "none", "scope": None},
    }
    command = envelope("result.submit", cycle_id=cycle_id, key="import-key", payload={
        "expected_revision": 1,
        "proposal_id": "proposal_00000000000000000000000000000000",
        "proposal_hash": "sha256:" + "a" * 64,
        "supersedes_result_id": None,
        "execution_kind": "physical",
        "accountable_party": CREATOR,
        "performers": [{"kind": "organization", "name": "External Lab", "version": None, "external_reference": reference}],
        "started_at": "2026-01-01T00:00:00.000000Z",
        "completed_at": "2026-01-01T00:01:00.000000Z",
        "external_references": [reference],
        "staged_blob_ids": ["external_blob_00000000000000000000000000000000"],
        "result_manifest": {"summary": "completed externally"},
        "deviations": [],
    })
    with pytest.raises(CycleError, match="gate rejected"):
        repository.submit_external_result(
            command,
            staging_root=tmp_path / "staged-results",
            quota=ImportQuota(),
        )
    assert not batch.exists()




def test_snapshot_failure_preserves_committed_response_for_exact_retry(tmp_path):
    repository = CycleRepository(tmp_path)
    cycle_id = json.loads(repository.start_cycle(start()))["cycle_id"]
    command = envelope("cycle.abort", cycle_id=cycle_id, key="abort-key",
                       message_id="request_11111111111111111111111111111111", payload={
                           "expected_revision": 1, "actor": CREATOR, "reason": "stop",
                           "final_observation": "none",
                       })
    original_write_snapshot = repository._write_snapshot
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("snapshot storage unavailable")
        return original_write_snapshot(*args, **kwargs)

    repository._write_snapshot = fail_once  # type: ignore[method-assign]
    response = repository.execute(command)
    assert repository.snapshot_repair_needed(cycle_id)
    repository._write_snapshot = original_write_snapshot  # type: ignore[method-assign]
    assert repository.execute(command) == response
    repaired_state = repository.load(cycle_id)
    receipt = repository._receipt(repaired_state, "abort-key")
    assert receipt is not None
    assert base64.b64decode(receipt["response_envelope_base64"]) == response
    assert len([event for event in replay_events(repository, cycle_id) if event["idempotency_key"] == "abort-key"]) == 1
    response_envelope = json.loads(response)
    assert response_envelope["message_id"] == deterministic_id("response", {"cycle_id": cycle_id, "sequence": 2})
    assert response_envelope["timestamp"] == command["timestamp"]
    assert response_envelope["sequence"] == response_envelope["revision"] == repaired_state["sequence"] == repaired_state["revision"] == 2
    assert not repository.snapshot_repair_needed(cycle_id)
def test_invalid_creation_registries_fail_closed(tmp_path):
    mutations = {
        "malformed": (lambda record: b"{", "invalid creation registry"),
        "noncanonical": (lambda record: json.dumps(record, indent=2).encode(), "invalid creation registry"),
        "wrong-schema": (lambda record: canonical_json(record | {"registry_schema": "wrong"}), "invalid creation registry"),
        "wrong-key": (lambda record: canonical_json(record | {"creation_idempotency_key": "other-key"}), "creation registry key mismatch"),
        "wrong-cycle": (lambda record: canonical_json(record | {
            "cycle_id": deterministic_id("cycle", {
                "normalized_question": "Different question?",
                "creation_idempotency_key": record["creation_idempotency_key"],
            })}), "creation registry cycle mismatch"),
        "wrong-digest": (lambda record: canonical_json(record | {
            "response_bytes_digest": "sha256:" + "0" * 64}), "creation registry does not match genesis receipt"),
        "wrong-receipt": (lambda record: canonical_json(record | {
            "receipt_id": deterministic_id("receipt", {
                "cycle_id": record["cycle_id"],
                "key": "other-key",
                "command_digest": record["command_digest"],
            })}), "creation registry does not match genesis receipt"),
    }
    for name, (mutate, reason) in mutations.items():
        home = tmp_path / name
        repository = CycleRepository(home)
        response = repository.start_cycle(start())
        registry = next((home / "cycles" / "registry").glob("*.json"))
        record = json.loads(registry.read_bytes())
        registry.write_bytes(mutate(record))
        with pytest.raises(RepositoryCorrupt, match=reason):
            repository.start_cycle(start())
        assert json.loads(response)["cycle_id"] == repository.load(json.loads(response)["cycle_id"])["cycle_id"]
def test_creation_receipt_rejects_noncanonical_base64_with_original_digest(tmp_path):
    repository = CycleRepository(tmp_path)
    repository.start_cycle(start())
    registry = next((tmp_path / "cycles" / "registry").glob("*.json"))
    receipt = json.loads(registry.read_bytes())
    encoded = receipt["response_envelope_base64"]
    noncanonical = encoded[:1] + "%" + encoded[1:]
    assert base64.b64decode(noncanonical) == base64.b64decode(encoded)
    with pytest.raises(RepositoryCorrupt, match="invalid command receipt"):
        repository._receipt_response(receipt | {"response_envelope_base64": noncanonical})


def test_corrupt_snapshots_rebuild_from_ledger_without_revision_change(tmp_path):
    corruptions = {
        "malformed": lambda snapshot: b"{",
        "noncanonical": lambda snapshot: json.dumps(snapshot, indent=2).encode(),
        "hash-invalid": lambda snapshot: canonical_json(snapshot | {"snapshot_hash": "sha256:" + "0" * 64}),
    }
    for name, corrupt in corruptions.items():
        home = tmp_path / name
        repository = CycleRepository(home)
        response = repository.start_cycle(start())
        cycle_id = json.loads(response)["cycle_id"]
        directory = home / "cycles" / cycle_id
        ledger = directory / "ledger.jsonl"
        original_ledger = ledger.read_bytes()
        original_revision = repository.load(cycle_id)["revision"]
        snapshot = directory / "manifest.json"
        snapshot.write_bytes(corrupt(json.loads(snapshot.read_bytes())))
        rebuilt = repository.load(cycle_id)
        assert rebuilt["revision"] == original_revision
        assert ledger.read_bytes() == original_ledger
        repaired = snapshot.read_bytes()
        public = {key: value for key, value in rebuilt.items() if key not in {"_events", "_event_hash"}}
        checkpoint = {"cycle_id": cycle_id, "sequence": rebuilt["sequence"], "event_hash": rebuilt["_event_hash"]}
        repaired_snapshot = json.loads(repaired)
        assert repaired != corrupt(json.loads(repaired)) if name == "hash-invalid" else repaired == canonical_json(repaired_snapshot)
        assert repaired_snapshot["snapshot_id"] == deterministic_id("snapshot", checkpoint)
        assert repaired_snapshot["checkpoint"] == checkpoint
        assert repaired_snapshot["state"] == public
        assert repaired_snapshot["state_hash"] == digest(public)
        assert repaired_snapshot["snapshot_hash"] == digest(
            {"checkpoint": checkpoint, "state_hash": repaired_snapshot["state_hash"], "state": public})
        assert repository.load(cycle_id)["revision"] == original_revision

def test_accepted_mutation_responses_carry_server_derived_export_gate(tmp_path):
    repository = CycleRepository(tmp_path)
    cycle_id = json.loads(repository.start_cycle(start()))["cycle_id"]
    response = json.loads(repository.execute(envelope("cycle.abort", cycle_id=cycle_id, key="abort-key", payload={
        "expected_revision": 1, "actor": CREATOR, "reason": "stop", "final_observation": "none",
    })))
    assert response["name"] == "command.accepted.response"
    assert response["payload"]["result"]["gates"] == {"export_ready": False}

def test_committed_interim_report_replays_and_renders(tmp_path):
    repository = CycleRepository(tmp_path)
    cycle_id = json.loads(repository.start_cycle(start()))["cycle_id"]
    response = json.loads(repository.execute(envelope("cycle.continue", cycle_id=cycle_id, key="interim-key", payload={
        "expected_revision": 1,
        "operation": "write.interim",
        "stage_input": {
            "kind": "write.interim",
            "accountable_party": CREATOR,
            "performers": [{"kind": "human", "name": "Operator", "version": None, "external_reference": None}],
            "execution_kind": "cognitive",
            "automation_mode": "manual",
            "boundary": {"kind": "cognitive_only", "description": "cognitive only"},
            "started_at": "2026-07-20T00:00:00.000000Z",
            "completed_at": "2026-07-20T00:00:01.000000Z",
            "source_revision": 1,
            "source_artifact_ids": [],
            "claim_ids": [],
            "result_ids": [],
            "analysis_artifact_ids": [],
            "limitations": ["No committed evidence yet."],
        },
    })))
    assert response["name"] == "command.accepted.response"
    # Regression: revision-bound reducer facts must replay identically after commit.
    assert repository.load(cycle_id)["revision"] == 2
    # Regression: an interim body is renderable before any final body exists.
    rendered = repository.render_report(cycle_id, at_revision=2, format="markdown", include_status_overlay=True)
    assert isinstance(rendered["body_utf8_or_json"], str) and rendered["body_utf8_or_json"]
    assert rendered["body_hash"].startswith("sha256:")
    assert rendered["status_overlay"]["revision"] == 2
