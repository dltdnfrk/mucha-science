from __future__ import annotations

import json
from pathlib import Path
import shutil

from src.pipeline.scientific_contracts import GENESIS_HASH, canonical_json
from src.pipeline.cycle_repository import CycleRepository
from src.tools_ext.adapters.mock_scorer import (
    MockScorerAdapter,
    mock_scorer_config,
    mock_scorer_inputs,
    mock_scorer_request,
)
from src.tools_ext.admission import Admission, AdmissionQuota
from src.tools_ext.invoker import ToolInvoker
from src.tools_ext.registry import AdapterRegistry


CREATOR = {
    "actor_kind": "human", "display_name": "Operator", "organization": None,
    "role": None, "assertion_source": "operator_entry",
    "verification_status": "operator_asserted_unverified",
    "authority_scope": {"kind": "none", "scope": None}, "external_reference": None,
}
REFERENCE = {
    "reference_type": "lab_log", "issuer": "Mucha Science", "title": "Adapter run",
    "uri_or_identifier": "adapter-run-1", "content_hash": "sha256:" + "b" * 64,
    "assertion_source": "external_reference",
    "verification_status": "external_reference_unverified",
    "authority_scope": {"kind": "none", "scope": None},
}


def envelope(name: str, cycle_id: str | None, key: str, revision: int,
             payload: dict[str, object]) -> dict[str, object]:
    return {
        "protocol": "muchanipo", "protocol_version": "ai-scientist.v1",
        "kind": "action", "name": name,
        "message_id": "request_00000000000000000000000000000000",
        "cycle_id": cycle_id,
        "correlation_id": "request_00000000000000000000000000000000",
        "causation_id": None, "sequence": 0, "revision": 0,
        "idempotency_key": key, "timestamp": "2026-07-19T00:00:00.000000Z",
        "payload": payload, "extensions": {},
    }


def completed_stage(kind: str, **extra: object) -> dict[str, object]:
    return {
        "kind": kind, "accountable_party": CREATOR,
        "performers": [{"kind": "human", "name": "Operator", "version": None,
                        "external_reference": None}],
        "execution_kind": "cognitive", "automation_mode": "manual",
        "boundary": {"kind": "cognitive_only", "description": "local"},
        "started_at": "2026-07-19T00:00:00.000000Z",
        "completed_at": "2026-07-19T00:00:01.000000Z", **extra,
    }


def repository_with_proposal(home: Path) -> tuple[CycleRepository, str, str, str]:
    repository = CycleRepository(home)
    start = envelope("cycle.start", None, "start-key", 0, {
        "creation_idempotency_key": "start-key", "expected_revision": 0,
        "raw_question": "Question?", "contract_version": "ai-scientist.v1",
        "boundary": {"kind": "cognitive_only", "description": "local"},
        "creator": CREATOR,
    })
    cycle_id = json.loads(repository.start_cycle(start))["cycle_id"]
    repository.execute(envelope("cycle.continue", cycle_id, "landscape-key", 1, {
        "expected_revision": 1, "operation": "landscape.complete",
        "stage_input": completed_stage(
            "landscape.complete", invalidate_current_proposal=False,
            landscape_artifacts=[{
                "title": "Landscape", "summary": "Committed sources",
                "source_artifact_ids": [], "limitations": ["Unverified sources"],
            }],
        ),
    }))
    repository.execute(envelope("cycle.continue", cycle_id, "hypothesis-key", 2, {
        "expected_revision": 2, "operation": "hypothesis.complete",
        "stage_input": completed_stage(
            "hypothesis.complete", invalidate_current_proposal=False,
            claims=[{
                "artifact_type": "claim", "statement": "Claim",
                "falsification_criteria": "Measure outcome", "evidence_artifact_ids": [],
                "parent_claim_ids": [], "rank": 1,
                "limitations": [
                    "Unvalidated candidate; rank is prioritization, not support.",
                    "Evidence text is explicitly unlinked to committed artifacts.",
                ],
            }],
        ),
    }))
    claims = repository.load(cycle_id)["current"]["claims"]
    repository.execute(envelope("cycle.continue", cycle_id, "proposal-key", 3, {
        "expected_revision": 3, "operation": "proposal.complete",
        "stage_input": completed_stage("proposal.complete", proposal={
            "claim_ids": claims, "risks": ["External execution risk"],
            "acceptance_criteria": ["Externally reviewed result"],
            "handoff_boundary": {"kind": "export_only", "description": "external only"},
        }),
    }))
    state = repository.load(cycle_id)
    proposal_id = state["current"]["proposal"]
    return repository, cycle_id, proposal_id, state["records"][proposal_id]["content_hash"]


def registry() -> AdapterRegistry:
    result = AdapterRegistry()
    result.register(mock_scorer_config(), MockScorerAdapter())
    return result


def staged_run(root: Path):
    registered = registry().probe("reference.mock_scorer")
    parameters = {"candidate": "AAAA", "target": "AAAT"}
    return ToolInvoker(root).invoke(
        registered, mock_scorer_request(parameters, 17), full_parameters=parameters,
        requested_seed=17, seed_handling="HONORED", inputs=mock_scorer_inputs(parameters),
        source_snapshot_ids=("fixture-sequences-v1",),
    )


def submit_command(repository: CycleRepository, cycle_id: str, proposal_id: str,
                   proposal_hash: str) -> dict[str, object]:
    revision = repository.load(cycle_id)["revision"]
    return envelope("result.submit", cycle_id, "adapter-admission-key", revision, {
        "expected_revision": revision, "proposal_id": proposal_id,
        "proposal_hash": proposal_hash, "supersedes_result_id": None,
        "execution_kind": "computational", "accountable_party": CREATOR,
        "performers": [{"kind": "organization", "name": "Mucha Science Adapter",
                        "version": "1", "external_reference": REFERENCE}],
        "started_at": "2026-07-19T00:00:00.000000Z",
        "completed_at": "2026-07-19T00:00:01.000000Z",
        "external_references": [REFERENCE],
        "staged_blob_ids": ["external_blob_00000000000000000000000000000000"],
        "result_manifest": {}, "deviations": [],
    })


def admission(tmp_path: Path, repository: CycleRepository,
              adapter_registry: AdapterRegistry | None = None,
              quota: AdmissionQuota = AdmissionQuota()) -> Admission:
    return Admission(
        adapter_registry or registry(), repository,
        permanent_root=tmp_path / "permanent",
        quarantine_root=tmp_path / "quarantine",
        quota=quota,
    )


def assert_no_staged_orphans(staging_root: Path) -> None:
    assert staging_root.is_dir()
    assert list(staging_root.iterdir()) == []


def test_valid_staged_artifact_is_admitted_and_queryable_by_repository_replay(tmp_path: Path):
    repository, cycle_id, proposal_id, proposal_hash = repository_with_proposal(tmp_path / "home")
    staging_root = tmp_path / "staging"
    invocation = staged_run(staging_root)

    outcome = admission(tmp_path, repository).admit(
        invocation.artifact.staging_path,
        submit_command(repository, cycle_id, proposal_id, proposal_hash),
    )

    assert outcome.admitted
    assert outcome.invocation == invocation.record
    assert Path(outcome.artifact_path).is_dir()
    assert Path(outcome.artifact_path).parent == tmp_path / "permanent"
    replay = repository.verified_replay(
        cycle_id, cursor={"cycle_id": cycle_id, "sequence": 0, "event_hash": GENESIS_HASH},
        max_events=128,
    )
    event = replay["events"][-1]
    assert event["name"] == "result.recorded"
    manifest = event["payload"]["result_manifest"]
    projected_invocation = invocation.record.to_dict()
    projected_invocation["invocation_sha256"] = projected_invocation.pop("invocation_id")
    assert manifest["invocation"] == projected_invocation
    assert manifest["manifest_sha256"] == invocation.artifact.manifest_sha256
    assert manifest["output_sha256s"] == list(invocation.artifact.output_sha256s)
    assert "output_bytes" not in json.dumps(event)
    assert_no_staged_orphans(staging_root)


def test_tampered_output_digest_is_rejected_quarantined_and_leaves_no_orphans(tmp_path: Path):
    repository, cycle_id, proposal_id, proposal_hash = repository_with_proposal(tmp_path / "home")
    staging_root = tmp_path / "staging"
    invocation = staged_run(staging_root)
    first_output = next((Path(invocation.artifact.staging_path) / "outputs").iterdir())
    first_output.write_bytes(first_output.read_bytes() + b"tampered")

    outcome = admission(tmp_path, repository).admit(
        invocation.artifact.staging_path,
        submit_command(repository, cycle_id, proposal_id, proposal_hash),
    )

    assert not outcome.admitted
    assert "digest" in outcome.reason
    assert Path(outcome.artifact_path).parent == tmp_path / "quarantine"
    assert Path(outcome.artifact_path).is_dir()
    assert repository.load(cycle_id)["revision"] == 4
    assert_no_staged_orphans(staging_root)


def test_unregistered_adapter_is_rejected(tmp_path: Path):
    repository, cycle_id, proposal_id, proposal_hash = repository_with_proposal(tmp_path / "home")
    staging_root = tmp_path / "staging"
    invocation = staged_run(staging_root)

    outcome = admission(tmp_path, repository, AdapterRegistry()).admit(
        invocation.artifact.staging_path,
        submit_command(repository, cycle_id, proposal_id, proposal_hash),
    )

    assert not outcome.admitted
    assert "registered" in outcome.reason
    assert Path(outcome.artifact_path).parent == tmp_path / "quarantine"
    assert_no_staged_orphans(staging_root)


def test_schema_invalid_manifest_is_rejected(tmp_path: Path):
    repository, cycle_id, proposal_id, proposal_hash = repository_with_proposal(tmp_path / "home")
    staging_root = tmp_path / "staging"
    invocation = staged_run(staging_root)
    manifest_path = Path(invocation.artifact.staging_path) / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["invocation"].pop("status")
    manifest_path.write_bytes(canonical_json(manifest))

    outcome = admission(tmp_path, repository).admit(
        invocation.artifact.staging_path,
        submit_command(repository, cycle_id, proposal_id, proposal_hash),
    )

    assert not outcome.admitted
    assert "schema" in outcome.reason
    assert Path(outcome.artifact_path).parent == tmp_path / "quarantine"
    assert_no_staged_orphans(staging_root)


def test_oversize_artifact_is_rejected(tmp_path: Path):
    repository, cycle_id, proposal_id, proposal_hash = repository_with_proposal(tmp_path / "home")
    staging_root = tmp_path / "staging"
    invocation = staged_run(staging_root)

    outcome = admission(
        tmp_path, repository,
        quota=AdmissionQuota(max_outputs=8, max_manifest_bytes=64 * 1024,
                             max_output_bytes=4, max_total_output_bytes=12),
    ).admit(
        invocation.artifact.staging_path,
        submit_command(repository, cycle_id, proposal_id, proposal_hash),
    )

    assert not outcome.admitted
    assert "quota" in outcome.reason
    assert Path(outcome.artifact_path).parent == tmp_path / "quarantine"
    assert_no_staged_orphans(staging_root)


def test_exact_admission_retry_is_idempotent_and_leaves_no_staging_or_handoff_orphans(tmp_path: Path):
    repository, cycle_id, proposal_id, proposal_hash = repository_with_proposal(tmp_path / "home")
    staging_root = tmp_path / "staging"
    invocation = staged_run(staging_root)
    command = submit_command(repository, cycle_id, proposal_id, proposal_hash)
    component = admission(tmp_path, repository)

    first = component.admit(invocation.artifact.staging_path, command)
    shutil.copytree(first.artifact_path, invocation.artifact.staging_path)
    second = component.admit(invocation.artifact.staging_path, command)

    assert first.admitted and second.admitted
    assert first.repository_response == second.repository_response
    events = repository.verified_replay(
        cycle_id, cursor={"cycle_id": cycle_id, "sequence": 0, "event_hash": GENESIS_HASH},
        max_events=128,
    )["events"]
    assert len([event for event in events if event["idempotency_key"] == "adapter-admission-key"]) == 1
    assert_no_staged_orphans(staging_root)
    assert not (tmp_path / "permanent" / ".ledger-handoff").exists()
