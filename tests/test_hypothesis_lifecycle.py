from __future__ import annotations

from dataclasses import replace
import pytest

from src.council.scientific_hypotheses import HypothesisError, HypothesisLifecycle
from src.pipeline.scientific_cycle import GateUnsatisfied, ScientificCycleReducer, initial_state


def candidate(claim: str = "Treatment changes the measured outcome") -> dict[str, object]:
    return {
        "claim": claim,
        "rationale": "A mechanism predicts a measurable difference.",
        "evidence": ["observational dataset"],
        "counterevidence": ["confounding can explain the difference"],
        "falsification_criteria": "A controlled comparison shows no difference.",
    }
def actor() -> dict[str, object]:
    return {
        "actor_kind": "human", "display_name": "Operator", "organization": None,
        "role": "reviewer", "assertion_source": "operator_entry",
        "verification_status": "operator_asserted_unverified",
        "authority_scope": {"kind": "none", "scope": None}, "external_reference": None,
    }


def boundary() -> dict[str, str]:
    return {"kind": "cognitive_only", "description": "cognitive only"}


def stage(kind: str, **extra: object) -> dict[str, object]:
    return {
        "kind": kind, "accountable_party": actor(),
        "performers": [{"kind": "human", "name": "Operator", "version": None,
                        "external_reference": None}],
        "execution_kind": "cognitive", "automation_mode": "manual", "boundary": boundary(),
        "started_at": "2026-07-19T00:00:00.000000Z",
        "completed_at": "2026-07-19T00:00:01.000000Z", **extra,
    }


def continue_action(operation: str, stage_input: dict[str, object]) -> dict[str, object]:
    return {
        "name": "cycle.continue",
        "payload": {"expected_revision": 0, "operation": operation, "stage_input": stage_input},
    }


def test_hypothesis_parsing_rejects_aliases_and_missing_falsification():
    lifecycle = HypothesisLifecycle()
    for malformed in (
        {"candidates": [candidate()]},
        [{key: value for key, value in candidate().items() if key != "falsification_criteria"}],
        [candidate() | {"statement": candidate()["claim"]}],
        [candidate() | {"counter_evidence": candidate()["counterevidence"]}],
        [candidate() | {"falsification": candidate()["falsification_criteria"]}],
    ):
        with pytest.raises(HypothesisError):
            lifecycle.parse(malformed)


def test_parsing_requires_claim_rationale_evidence_and_counterevidence():
    lifecycle = HypothesisLifecycle()
    parsed = lifecycle.parse([candidate()])
    assert parsed[0].status == "candidate"
    assert parsed[0].to_record()["validation_status"] == "unvalidated"
    with pytest.raises(HypothesisError):
        lifecycle.parse([{key: value for key, value in candidate().items() if key != "counterevidence"}])


def test_critique_rank_and_evolution_have_stable_lineage_without_validation():
    lifecycle = HypothesisLifecycle()
    original = lifecycle.parse([candidate()])[0]
    critiqued = lifecycle.critique([original])[0]
    ranked = lifecycle.rank([critiqued])[0]
    evolved = lifecycle.evolve(ranked, candidate("A bounded treatment changes the outcome"))
    assert original.id in evolved.parent_ids
    assert ranked.rank == 1
    assert evolved.to_record()["validation_status"] == "unvalidated"
    assert "Falsification test required" in " ".join(critiqued.critiques)
def test_evolution_rejects_non_array_parent_ids_before_lineage_union():
    lifecycle = HypothesisLifecycle()
    original = lifecycle.parse([candidate()])[0]
    with pytest.raises(HypothesisError, match="parent_ids"):
        lifecycle.evolve(original, candidate() | {"parent_ids": original.id})


def test_h_stage_validation_requires_complete_unvalidated_provenance_shape():
    lifecycle = HypothesisLifecycle()
    hypothesis = lifecycle.rank(lifecycle.parse([candidate()]))
    claim = lifecycle.h_stage_input(hypothesis)["claims"][0]
    lifecycle.validate_h_stage_claims([claim], [])

    without_unvalidated = dict(claim) | {
        "limitations": [
            limitation for limitation in claim["limitations"]
            if not limitation.startswith("Unvalidated candidate")
        ],
    }
    without_unlinked_evidence = dict(claim) | {
        "limitations": [
            limitation for limitation in claim["limitations"]
            if not limitation.startswith("Evidence text is explicitly unlinked")
        ],
    }
    malformed_shape = dict(claim) | {"validation_status": "unvalidated"}
    for malformed in (without_unvalidated, without_unlinked_evidence, malformed_shape):
        with pytest.raises(HypothesisError):
            lifecycle.validate_h_stage_claims([malformed], [])
def test_h_stage_projection_requires_an_explicit_rank():
    lifecycle = HypothesisLifecycle()
    with pytest.raises(HypothesisError, match="explicit rank"):
        lifecycle.h_stage_input(lifecycle.parse([candidate()]))
def test_ranked_batches_require_unique_contiguous_ranks_but_allow_inverse_ordering():
    lifecycle = HypothesisLifecycle()
    hypotheses = lifecycle.parse([
        candidate(),
        candidate("A distinct treatment changes a different measured outcome"),
    ])
    duplicate = [replace(hypotheses[0], rank=1), replace(hypotheses[1], rank=1)]
    gapped = [replace(hypotheses[0], rank=1), replace(hypotheses[1], rank=3)]
    for invalid in (duplicate, gapped):
        with pytest.raises(HypothesisError, match="unique contiguous"):
            lifecycle.h_stage_input(invalid)

    ranked = lifecycle.rank(hypotheses)
    inverse = list(reversed(ranked))
    projection = lifecycle.h_stage_input(inverse)
    assert [claim["rank"] for claim in projection["claims"]] == [item.rank for item in inverse]
    lifecycle.validate_h_stage_claims(projection["claims"], [])
    duplicate_claims = [dict(claim) | {"rank": 1} for claim in projection["claims"]]
    gapped_claims = [
        dict(projection["claims"][0]) | {"rank": 1},
        dict(projection["claims"][1]) | {"rank": 3},
    ]
    for invalid in (duplicate_claims, gapped_claims):
        with pytest.raises(HypothesisError, match="unique contiguous"):
            lifecycle.validate_h_stage_claims(invalid, [])


def test_h_stage_validation_rejects_fabricated_duplicate_self_cyclic_and_stale_parents():
    lifecycle = HypothesisLifecycle()
    projection = lifecycle.h_stage_input(lifecycle.rank(lifecycle.parse([candidate()])))["claims"][0]

    def committed_claim(claim_id: str, parent_ids: list[str] | None = None) -> dict[str, object]:
        return {
            "id": claim_id,
            "record_type": "claim",
            "content": {"artifact_type": "claim", "parent_claim_ids": parent_ids or []},
        }

    valid_parent_id = "claim_current"
    lifecycle.validate_h_stage_claims(
        [dict(projection) | {"parent_claim_ids": [valid_parent_id]}],
        {valid_parent_id: committed_claim(valid_parent_id)},
    )
    original = lifecycle.rank(lifecycle.critique(lifecycle.parse([candidate()])))[0]
    evolved = lifecycle.rank([lifecycle.evolve(
        original, candidate("A bounded treatment changes the outcome"),
    )])
    lifecycle.validate_h_stage_claims(
        lifecycle.h_stage_input(evolved)["claims"],
        {original.id: committed_claim(original.id)},
    )

    fabricated = dict(projection) | {"parent_claim_ids": ["claim_fabricated"]}
    duplicate = dict(projection) | {"parent_claim_ids": [valid_parent_id, valid_parent_id]}
    self_link = dict(projection) | {"parent_claim_ids": ["claim_self"]}
    cyclic = dict(projection) | {"parent_claim_ids": ["claim_a"]}
    stale = dict(projection) | {"parent_claim_ids": ["claim_stale"]}
    for malformed, committed in (
        (fabricated, {}),
        (duplicate, {valid_parent_id: committed_claim(valid_parent_id)}),
        (self_link, {"claim_self": committed_claim("claim_self", ["claim_self"])}),
        (cyclic, {
            "claim_a": committed_claim("claim_a", ["claim_b"]),
            "claim_b": committed_claim("claim_b", ["claim_a"]),
        }),
        (stale, {"claim_stale": committed_claim("claim_stale", ["claim_missing"])}),
        (stale, {
            "claim_stale": committed_claim("claim_stale"),
            "requirement_current_claims": {
                "record_type": "responsibility_requirement",
                "content": {
                    "responsibility": "novelty_value_judgment",
                    "scope_kind": "claims",
                    "scope_ids": [valid_parent_id],
                    "requirement_ordinal": 1,
                },
            },
        }),
    ):
        with pytest.raises(HypothesisError):
            lifecycle.validate_h_stage_claims([malformed], committed)


def test_hypothesis_parent_parsing_and_evolution_reject_duplicate_links():
    lifecycle = HypothesisLifecycle()
    original = lifecycle.parse([candidate()])[0]
    with pytest.raises(HypothesisError, match="duplicates"):
        lifecycle.parse([candidate() | {"parent_ids": ["claim_parent", "claim_parent"]}])
    with pytest.raises(HypothesisError, match="repeat"):
        lifecycle.evolve(original, candidate() | {"parent_ids": [original.id]})


def test_counter_hypotheses_and_h_stage_claims_are_explicitly_unvalidated():
    lifecycle = HypothesisLifecycle()
    ranked = lifecycle.rank(lifecycle.parse([candidate()]))
    counter = lifecycle.counter_hypotheses(ranked)[0]
    h_input = lifecycle.h_stage_input(ranked)
    assert counter.parent_ids == (ranked[0].id,)
    assert h_input["kind"] == "hypothesis.complete"
    assert h_input["claims"][0]["rank"] == 1
    assert "Unvalidated candidate" in h_input["claims"][0]["limitations"][0]
def test_h_stage_lifecycle_output_references_only_committed_artifacts_and_reduces():
    lifecycle = HypothesisLifecycle()
    hypotheses = lifecycle.rank(lifecycle.critique(lifecycle.parse([candidate()])))
    reducer = ScientificCycleReducer()
    state = initial_state("cycle_00000000000000000000000000000000", "Question?",
                          "ai-scientist.v1", boundary(), actor())
    landscape = reducer.apply(state, continue_action("landscape.complete", stage(
        "landscape.complete", invalidate_current_proposal=False, landscape_artifacts=[{
            "title": "Landscape", "summary": "Committed source",
            "source_artifact_ids": [], "limitations": ["Unverified source"],
        }],
    )))
    evidence_id = landscape.state["records"][landscape.result["stage_id"]]["content"]["artifact_ids"][0]
    h_projection = lifecycle.h_stage_input(
        hypotheses, evidence_artifact_ids={hypotheses[0].id: [evidence_id]},
    )
    reduction = reducer.apply(landscape.state, continue_action("hypothesis.complete", stage(
        "hypothesis.complete", invalidate_current_proposal=False, claims=h_projection["claims"],
    )))
    claim = reduction.state["records"][reduction.state["current"]["claims"][0]]["content"]
    assert claim["evidence_artifact_ids"] == [evidence_id]
    assert all(record_id in reduction.state["records"] for record_id in claim["evidence_artifact_ids"])
    assert "Unvalidated candidate" in claim["limitations"][0]


def test_reducer_rejects_dangling_h_stage_evidence_references():
    lifecycle = HypothesisLifecycle()
    hypotheses = lifecycle.rank(lifecycle.parse([candidate()]))
    reducer = ScientificCycleReducer()
    state = initial_state("cycle_00000000000000000000000000000000", "Question?",
                          "ai-scientist.v1", boundary(), actor())
    landscape = reducer.apply(state, continue_action("landscape.complete", stage(
        "landscape.complete", invalidate_current_proposal=False, landscape_artifacts=[{
            "title": "Landscape", "summary": "Committed source",
            "source_artifact_ids": [], "limitations": ["Unverified source"],
        }],
    )))
    h_projection = lifecycle.h_stage_input(
        hypotheses, evidence_artifact_ids={hypotheses[0].id: ["artifact_missing"]},
    )
    with pytest.raises(GateUnsatisfied, match="uncommitted evidence"):
        reducer.apply(landscape.state, continue_action("hypothesis.complete", stage(
            "hypothesis.complete", invalidate_current_proposal=False, claims=h_projection["claims"],
        )))
