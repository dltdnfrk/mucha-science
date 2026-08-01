#!/usr/bin/env python3
"""Run the synthetic M1 end-to-end plumbing proof.

This script uses only the synthetic-m1 pack and the reference mock scorer. It
proves contract and admission plumbing; it does not assess scientific or model
performance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evidence_ladder import (  # noqa: E402
    EvidenceLadderError,
    derive_auto_calibration_eligibility,
    validate_pairing,
)
from src.objectives import (  # noqa: E402
    OBJECTIVE_REGISTRY,
    PLATFORM_CONSTRAINT_IDS,
    CandidateDecision,
    CandidateInput,
    combine_candidates,
    create_query_revision,
)
from src.packs_loader import PackHandle, load_pack  # noqa: E402
from src.pipeline.scientific_contracts import canonical_json, digest  # noqa: E402
from src.platform_contracts import (  # noqa: E402
    ApplicationType,
    AssayObservation,
    ConstraintOutcome,
    Measurement,
    ObjectiveTerm,
    Prediction,
)
from src.tools_ext.adapters.mock_scorer import (  # noqa: E402
    MockScorerAdapter,
    mock_scorer_config,
    mock_scorer_inputs,
    mock_scorer_request,
)
from src.tools_ext.admission import Admission  # noqa: E402
from src.tools_ext.invoker import InvocationResult, ToolInvoker  # noqa: E402
from src.tools_ext.registry import AdapterRegistry  # noqa: E402

DISCLAIMER = "synthetic data — plumbing proof, no performance claim"
ADAPTER_ID = "reference.mock_scorer"
SEED_BASE = 20_260_801


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _read_json(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(canonical_json(value) + b"\n")


def _pack_identity(handle: PackHandle) -> dict[str, Any]:
    return {
        "name": handle.name,
        "version": handle.version,
        "manifest_sha256": handle.manifest_sha256,
        "restricted": handle.restricted,
    }


class RunLedger:
    """Small test-scoped repository sink used by the real admission path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.count = 0

    def submit_external_result(
        self,
        command: Mapping[str, Any],
        *,
        staging_root: str | Path,
        quota: object,
    ) -> bytes:
        del staging_root, quota
        material = json.loads(canonical_json(command))
        payload = material.get("payload")
        if not isinstance(payload, dict) or payload.get("disclaimer") != DISCLAIMER:
            raise ValueError("admitted invocation is missing the synthetic-data disclaimer")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as ledger:
            ledger.write(canonical_json(material) + b"\n")
        self.count += 1
        return canonical_json({"admitted": True, "ledger_sequence": self.count})


def _query_revision(target_id: str, created_at: str):
    definition = OBJECTIVE_REGISTRY["target_binding_activity"]
    objective = ObjectiveTerm.from_content(
        {
            "term_id": "target_binding_activity",
            "objective_ref": definition.objective_ref,
            "weight_units": 1_000_000,
            "parameters": {"target_ids": [target_id]},
        }
    )
    return create_query_revision(
        query_id="synthetic-m1-query",
        application_type=ApplicationType.CONTAINED_LAB,
        objectives=(objective,),
        user_constraints=(),
        actor="m1-plumbing-loop",
        created_at=created_at,
    )


def _admission_command(candidate_id: str, sequence: int) -> dict[str, Any]:
    return {
        "kind": "m1.synthetic-tool-result",
        "idempotency_key": f"m1-{candidate_id}-{sequence}",
        "payload": {
            "candidate_id": candidate_id,
            "disclaimer": DISCLAIMER,
            "synthetic": True,
        },
    }


def _screen_candidates(
    candidates: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    pack: PackHandle,
    work_root: Path,
    ledger_path: Path,
) -> tuple[list[CandidateInput], list[dict[str, Any]], list[InvocationResult]]:
    registry = AdapterRegistry()
    registry.register(mock_scorer_config(), MockScorerAdapter())
    registered = registry.probe(ADAPTER_ID)
    repository = RunLedger(ledger_path)
    admission = Admission(
        registry,
        repository,
        permanent_root=work_root / "admitted",
        quarantine_root=work_root / "quarantine",
    )
    invoker = ToolInvoker(work_root / "staging", timeout_seconds=10)
    screened: list[CandidateInput] = []
    traces: list[dict[str, Any]] = []
    invocations: list[InvocationResult] = []
    constraint_id = PLATFORM_CONSTRAINT_IDS["synthesizability"]

    for index, candidate in enumerate(candidates):
        candidate_id = candidate.get("id")
        structure = candidate.get("structure_like")
        target_sequence = target.get("sequence")
        synthesizable = candidate.get("synthesizable")
        if (
            not isinstance(candidate_id, str)
            or not isinstance(structure, str)
            or not isinstance(target_sequence, str)
            or not isinstance(synthesizable, bool)
        ):
            raise ValueError("pack candidate/target fields do not match the M1 schema")
        seed = SEED_BASE + index
        parameters = {"candidate": structure, "target": target_sequence}
        invocation = invoker.invoke(
            registered,
            mock_scorer_request(parameters, seed),
            full_parameters=parameters,
            requested_seed=seed,
            seed_handling="HONORED",
            inputs=mock_scorer_inputs(parameters),
            source_snapshot_ids=(pack.manifest_sha256,),
        )
        if invocation.record.status != "SUCCEEDED" or invocation.parsed is None:
            raise RuntimeError(f"mock scorer failed for {candidate_id}: {invocation.record.status}")
        admitted = admission.admit(
            invocation.artifact.staging_path,
            _admission_command(candidate_id, index + 1),
        )
        if not admitted.admitted:
            raise RuntimeError(f"admission rejected {candidate_id}: {admitted.reason}")
        output = dict(invocation.parsed.canonical_output)
        score_ppm = output.get("score_ppm")
        if not isinstance(score_ppm, int):
            raise RuntimeError(f"mock scorer returned no integer score for {candidate_id}")
        screened.append(
            CandidateInput(
                candidate_id,
                candidate,
                {"target_binding_activity": score_ppm},
                {
                    constraint_id: (
                        ConstraintOutcome.PASS if synthesizable else ConstraintOutcome.FAIL
                    )
                },
            )
        )
        traces.append(
            {
                "candidate_id": candidate_id,
                "score_ppm": score_ppm,
                "objective_term_id": "target_binding_activity",
                "tool": dict(invocation.record.tool),
                "adapter": dict(invocation.record.adapter),
                "parameters": dict(invocation.record.full_parameters),
                "parameter_sha256": invocation.record.parameter_sha256,
                "seed": invocation.record.requested_seed,
                "seed_handling": invocation.record.seed_handling,
                "invocation_id": invocation.record.invocation_id,
                "canonical_output_sha256": invocation.record.canonical_output_sha256,
                "admitted_manifest_sha256": invocation.artifact.manifest_sha256,
                "pack_identity": _pack_identity(pack),
                "disclaimer": DISCLAIMER,
            }
        )
        invocations.append(invocation)

    if repository.count != len(candidates):
        raise RuntimeError("not every screening invocation landed in the run ledger")
    return screened, traces, invocations


def _decision_payload(decision: CandidateDecision) -> dict[str, Any]:
    return {
        "candidate_id": decision.candidate_id,
        "candidate_content_hash": decision.candidate_content_hash,
        "disposition": decision.disposition.value,
        "rank": decision.rank,
        "composite_score_ppm": decision.composite_score_ppm,
        "per_objective_utility_ppm": dict(decision.per_objective_utility_ppm),
        "reasons": list(decision.reasons),
        "required_next_evidence": list(decision.required_next_evidence),
    }


def run(pack_dir: Path, out_dir: Path, *, inject_backdated_observation: bool = False) -> Path:
    handle = load_pack(pack_dir)
    targets_doc = _read_json(pack_dir / "targets.json")
    candidates_doc = _read_json(pack_dir / "candidates.json")
    assay_doc = _read_json(pack_dir / "assay_vocab.json")
    targets = targets_doc.get("targets")
    candidates = candidates_doc.get("candidates")
    endpoints = assay_doc.get("endpoints")
    if not isinstance(targets, list) or not targets or not isinstance(candidates, list) or not candidates:
        raise ValueError("pack must provide at least one target and candidate")
    if not isinstance(endpoints, list) or not endpoints:
        raise ValueError("pack must provide at least one assay endpoint")
    target, endpoint = targets[0], endpoints[0]
    if not isinstance(target, dict) or not isinstance(endpoint, dict):
        raise ValueError("pack target and endpoint entries must be objects")
    target_id, endpoint_id, unit = target.get("id"), endpoint.get("id"), endpoint.get("unit")
    if not all(isinstance(item, str) and item for item in (target_id, endpoint_id, unit)):
        raise ValueError("pack target and endpoint identity fields must be nonempty strings")

    if out_dir.exists():
        raise FileExistsError(f"output directory already exists: {out_dir}")
    out_dir.mkdir(parents=True)
    started = datetime.now(timezone.utc)
    revision = _query_revision(target_id, _utc_timestamp(started))

    with tempfile.TemporaryDirectory(prefix="m1-loop-") as temporary:
        screened, score_traces, invocations = _screen_candidates(
            candidates,
            target,
            handle,
            Path(temporary),
            out_dir / "invocation_ledger.jsonl",
        )

    combination = combine_candidates(revision, screened)
    expected_excluded = {item["id"] for item in candidates if item.get("synthesizable") is False}
    actual_excluded = {item.candidate_id for item in combination.excluded}
    if not expected_excluded or actual_excluded != expected_excluded:
        raise RuntimeError(
            "synthesizability gate failed: "
            f"expected excluded {sorted(expected_excluded)}, got {sorted(actual_excluded)}"
        )
    if combination.debug_blocked_as_ranked or not combination.ranked:
        raise RuntimeError("D1 ranking gate produced no valid top-ranked candidate")

    top = combination.ranked[0]
    score_trace = next(trace for trace in score_traces if trace["candidate_id"] == top.candidate_id)
    top_invocation = next(
        item for item in invocations if item.record.invocation_id == score_trace["invocation_id"]
    )
    issued_at = _utc_timestamp(started + timedelta(seconds=1))
    locked_at = _utc_timestamp(started + timedelta(seconds=2))
    assay_started = started + timedelta(seconds=3)
    if inject_backdated_observation:
        assay_started = started + timedelta(seconds=1)
    observed_at = started + timedelta(seconds=4)
    paired_at = started + timedelta(seconds=5)
    condition_hash = digest(
        {"assay_condition_id": "synthetic-m1-purified-enzyme", "endpoint_ref": endpoint_id}
    )
    prediction = Prediction.from_content(
        {
            "prediction_series_id": f"synthetic-m1:{top.candidate_id}:{endpoint_id}",
            "origin": "PLATFORM_COMPUTATION",
            "estimand": {
                "candidate_id": top.candidate_id,
                "target_id": target_id,
                "endpoint_ref": endpoint_id,
                "unit": unit,
                "condition_scope_hash": condition_hash,
            },
            "result": {"kind": "POINT", "value": str(top.composite_score_ppm)},
            "issued_at": issued_at,
            "locked_at": locked_at,
            "invocation_lineage_hash": digest([item.record.invocation_id for item in invocations]),
            "revision": 1,
            "recomputes_prediction_id": None,
            "predictor_signature": top_invocation.record.adapter["build_sha256"],
            "input_hashes": [handle.manifest_sha256, top.candidate_content_hash],
            "uncertainty": {"status": "not_estimated_for_plumbing_proof"},
            "objective_normalizer_hash": revision.objectives[0].objective_ref["sha256"],
            "calibration_model_hash": None,
            "epistemic_status": "RANKABLE_PREDICTION",
        }
    )
    observation = AssayObservation.from_content(
        {
            "evidence_tier": "PURIFIED_ENZYME",
            "origin": "PLATFORM_ASSAY",
            "candidate_id": top.candidate_id,
            "target_id": target_id,
            "endpoint_ref": endpoint_id,
            "assay_condition_id": "synthetic-m1-purified-enzyme",
            "result": {"kind": "POINT", "value": "0.500000", "unit": unit},
            "raw_artifact_refs": ["synthetic://m1/simulated-wet-lab-result"],
            "replicate_group_ref": "synthetic-m1-replicates",
            "source_record_id": None,
            "assay_started_at": _utc_timestamp(assay_started),
            "observed_at": _utc_timestamp(observed_at),
            "qc_status": "PASS",
        }
    )
    measurement = Measurement.from_content(
        {
            "observation_id": observation.observation_id,
            "originating_prediction_id": prediction.prediction_id,
            "pairing_design": "PROSPECTIVE_LOCKED",
            "pair_relation": "DIRECT_ESTIMAND",
            "benchmark_split_role": "NONE",
            "pair_created_at": _utc_timestamp(paired_at),
            "compatibility_check_ref": f"exact-unit:{unit}",
        }
    )
    try:
        validated = validate_pairing(
            measurement,
            prediction,
            observation,
            convertible_units={(unit, unit)},
        )
    except EvidenceLadderError as exc:
        raise EvidenceLadderError(f"PROSPECTIVE_LOCKED pairing rejected: {exc}") from exc
    eligibility = derive_auto_calibration_eligibility(validated)
    if not eligibility.eligible:
        raise EvidenceLadderError(
            "auto-calibration eligibility rejected: " + "; ".join(eligibility.reasons)
        )

    ranking_payload = {
        "artifact_kind": "RankingResults",
        "synthetic": True,
        "disclaimer": DISCLAIMER,
        "query_revision": revision.to_payload(),
        "target_ids": [target_id],
        "ranked": [_decision_payload(item) for item in combination.ranked],
        "excluded": [_decision_payload(item) for item in combination.excluded],
        "abstained": [_decision_payload(item) for item in combination.abstained],
        "resolved_constraints": [item.to_content() for item in combination.resolved_constraints],
        "policy_bundle_ref": dict(combination.policy_bundle_ref),
    }
    wrappers = (
        ("ranked_results.json", ranking_payload),
        ("prediction.json", {"artifact_kind": "Prediction", "synthetic": True, "disclaimer": DISCLAIMER, "record": prediction.to_payload()}),
        ("assay_observation.json", {"artifact_kind": "AssayObservation", "synthetic": True, "simulated_wet_lab": True, "disclaimer": DISCLAIMER, "record": observation.to_payload()}),
        ("measurement.json", {"artifact_kind": "Measurement", "synthetic": True, "disclaimer": DISCLAIMER, "pairing_validation": {"design": "PROSPECTIVE_LOCKED", "passed": True, "auto_calibration_eligible": True}, "record": measurement.to_payload()}),
    )
    for filename, payload in wrappers:
        _write_json(out_dir / filename, payload)

    provenance = {
        "artifact_kind": "ProvenanceAudit",
        "synthetic": True,
        "disclaimer": DISCLAIMER,
        "pack_identity": _pack_identity(handle),
        "query_revision_id": revision.revision_id,
        "screening": {
            "adapter_id": ADAPTER_ID,
            "invocation_count": len(score_traces),
            "admission_ledger": "invocation_ledger.jsonl",
            "all_invocations_admitted": True,
            "score_traces": score_traces,
        },
        "ranking": {
            "combiner": "src.objectives.combine_candidates",
            "policy_bundle_ref": dict(combination.policy_bundle_ref),
            "synthesizability_constraint_id": PLATFORM_CONSTRAINT_IDS["synthesizability"],
            "excluded_candidate_ids": sorted(actual_excluded),
        },
        "evidence_pair": {
            "prediction_id": prediction.prediction_id,
            "observation_id": observation.observation_id,
            "measurement_id": measurement.measurement_id,
            "pairing_design": "PROSPECTIVE_LOCKED",
            "pairing_validation_passed": True,
            "auto_calibration_eligible": True,
        },
    }
    _write_json(out_dir / "provenance_audit.json", provenance)
    return out_dir


def _default_out() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return ROOT / "runs" / "m1" / stamp


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthetic M1 end-to-end plumbing proof")
    parser.add_argument("--pack", type=Path, default=ROOT / "packs" / "synthetic-m1")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--inject-backdated-observation",
        action="store_true",
        help="debug gate: make assay start precede prediction lock and require rejection",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    out_dir = args.out if args.out is not None else _default_out()
    output_preexisted = out_dir.exists()
    try:
        completed = run(
            args.pack.resolve(),
            out_dir.resolve(),
            inject_backdated_observation=args.inject_backdated_observation,
        )
    except Exception as exc:
        if not output_preexisted and out_dir.exists():
            shutil.rmtree(out_dir)
        print(f"M1 ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"M1 SUCCESS: {DISCLAIMER}")
    print(f"Output directory: {completed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
