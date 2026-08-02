from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.muni_contracts import (
    CandidateSet,
    CollectedData,
    CollectionJob,
    ContractError,
    ReviewRecord,
    Study,
    TargetSelection,
    WetLabHandoff,
    WorkflowRun,
)
from src.platform_contracts import canonical_json

TS = "2026-08-02T00:00:00.000000Z"
HASH_A = "sha256:" + "a" * 64

CONTENTS: dict[type[object], dict[str, object]] = {
    Study: {
        "target_crop": "cropA",
        "target_pathogen": "pathogenX",
        "purpose": "purposeAlpha",
        "created_at": TS,
        "pack_ref": None,
    },
    TargetSelection: {
        "target_crop": "cropB",
        "target_pathogen": "pathogenY",
        "selected_by": "labTeamA",
        "note": "selectionNoteA",
    },
    CollectionJob: {
        "study_ref": "study-ref-a",
        "source_ref": "source-ref-a",
        "status": "SUCCEEDED",
        "started_at": TS,
        "finished_at": TS,
        "result_ref": "collected-ref-a",
        "reason": None,
    },
    CollectedData: {
        "job_ref": "job-ref-a",
        "source_record_ref": "source-record-ref-a",
        "digest": HASH_A,
    },
    WorkflowRun: {
        "study_ref": "study-ref-a",
        "kind": "DIAGNOSTIC_DISCOVERY",
        "status": "SUCCEEDED",
        "started_at": TS,
        "finished_at": TS,
    },
    CandidateSet: {
        "workflow_ref": "workflow-ref-a",
        "kind": "COMPOUND_SCREENING",
        "items": [
            {"candidate_ref": "candidate-ref-a", "label": "candidateA"},
            {"candidate_ref": "candidate-ref-b", "label": "candidateB"},
        ],
        "count": 2,
    },
    ReviewRecord: {
        "candidate_set_ref": "candidate-set-ref-a",
        "reviewer": "reviewerA",
        "decision": "APPROVED",
        "note": "reviewNoteA",
        "decided_at": TS,
    },
    WetLabHandoff: {
        "review_ref": "review-ref-a",
        "artifact_paths": ["artifact/path/a", "artifact/path/b"],
        "disclaimer": "dryLabOnlyDisclaimer",
    },
}

ID_FIELDS = {
    Study: "study_id",
    CollectionJob: "job_id",
    WorkflowRun: "run_id",
    CandidateSet: "set_id",
    ReviewRecord: "review_id",
    WetLabHandoff: "handoff_id",
}


@pytest.mark.parametrize("record_type,content", CONTENTS.items(), ids=lambda value: getattr(value, "__name__", "content"))
def test_every_contract_round_trips_with_stable_content_identity(
    record_type: type[object], content: dict[str, object]
) -> None:
    first = record_type.from_content(content)  # type: ignore[attr-defined]
    reordered = record_type.from_content(dict(reversed(tuple(content.items()))))  # type: ignore[attr-defined]

    assert first == reordered
    assert first.content_hash == reordered.content_hash  # type: ignore[attr-defined]
    assert first.record_id == reordered.record_id  # type: ignore[attr-defined]
    assert record_type.from_payload(first.to_payload()) == first  # type: ignore[attr-defined]
    assert record_type.from_json(first.to_json()) == first  # type: ignore[attr-defined]
    assert first.to_json() == canonical_json(first.to_payload())  # type: ignore[attr-defined]

    changed = dict(content)
    changed_field = next(name for name, value in content.items() if isinstance(value, str) and name not in {"status", "kind", "decision", "created_at", "started_at", "finished_at", "decided_at", "digest"})
    changed[changed_field] = f"{content[changed_field]}-different"
    different = record_type.from_content(changed)  # type: ignore[attr-defined]
    assert different.content_hash != first.content_hash  # type: ignore[attr-defined]
    if record_type in ID_FIELDS:
        assert different.record_id != first.record_id  # type: ignore[attr-defined]


@pytest.mark.parametrize("record_type,content", CONTENTS.items(), ids=lambda value: getattr(value, "__name__", "content"))
def test_payload_validators_reject_missing_and_extra_fields(
    record_type: type[object], content: dict[str, object]
) -> None:
    missing = dict(content)
    missing.pop(next(iter(missing)))
    with pytest.raises(ContractError):
        record_type.from_content(missing)  # type: ignore[attr-defined]
    with pytest.raises(ContractError):
        record_type.from_content({**content, "unexpected": True})  # type: ignore[attr-defined]


def test_canonical_json_and_ids_ignore_dictionary_key_order() -> None:
    left = CandidateSet.from_content(CONTENTS[CandidateSet])
    right = CandidateSet.from_content({
        **CONTENTS[CandidateSet],
        "items": [
            {"label": "candidateA", "candidate_ref": "candidate-ref-a"},
            {"label": "candidateB", "candidate_ref": "candidate-ref-b"},
        ],
    })
    assert left.to_json() == right.to_json()
    assert left.set_id == right.set_id


def test_unknown_enum_values_are_rejected() -> None:
    invalid = (
        (CollectionJob, {**CONTENTS[CollectionJob], "status": "UNKNOWN"}),
        (WorkflowRun, {**CONTENTS[WorkflowRun], "kind": "UNKNOWN"}),
        (WorkflowRun, {**CONTENTS[WorkflowRun], "status": "UNKNOWN"}),
        (CandidateSet, {**CONTENTS[CandidateSet], "kind": "UNKNOWN"}),
        (ReviewRecord, {**CONTENTS[ReviewRecord], "decision": "UNKNOWN"}),
    )
    for record_type, content in invalid:
        with pytest.raises(ContractError):
            record_type.from_content(content)


def test_workflow_run_carries_exactly_one_kind() -> None:
    for asserted_both in (
        ["DIAGNOSTIC_DISCOVERY", "COMPOUND_SCREENING"],
        "DIAGNOSTIC_DISCOVERY|COMPOUND_SCREENING",
    ):
        with pytest.raises(ContractError):
            WorkflowRun.from_content({**CONTENTS[WorkflowRun], "kind": asserted_both})


def test_candidate_count_must_match_items() -> None:
    with pytest.raises(ContractError, match="count"):
        CandidateSet.from_content({**CONTENTS[CandidateSet], "count": 1})


@pytest.mark.parametrize("disclaimer", ["", None])
def test_handoff_disclaimer_is_required_and_nonempty(disclaimer: object) -> None:
    with pytest.raises(ContractError, match="disclaimer"):
        WetLabHandoff.from_content({**CONTENTS[WetLabHandoff], "disclaimer": disclaimer})
    missing = dict(CONTENTS[WetLabHandoff])
    missing.pop("disclaimer")
    with pytest.raises(ContractError):
        WetLabHandoff.from_content(missing)


def test_study_is_target_agnostic_with_no_default_target() -> None:
    targets = (("cropA", "pathogenX"), ("cropB", "pathogenY"), ("cropC", "pathogenZ"))
    studies = [Study.from_content({**CONTENTS[Study], "target_crop": crop, "target_pathogen": pathogen}) for crop, pathogen in targets]
    assert [(study.target_crop, study.target_pathogen) for study in studies] == list(targets)
    assert len({study.study_id for study in studies}) == 3
    with pytest.raises(TypeError):
        Study()  # type: ignore[call-arg]


def test_contracts_and_nested_payloads_are_frozen_and_ids_are_verified() -> None:
    study = Study.from_content(CONTENTS[Study])
    with pytest.raises(FrozenInstanceError):
        study.purpose = "different"  # type: ignore[misc]

    candidate_set = CandidateSet.from_content(CONTENTS[CandidateSet])
    with pytest.raises(TypeError):
        candidate_set.items[0]["label"] = "changed"  # type: ignore[index]
    with pytest.raises(ContractError):
        Study.from_payload({**study.to_payload(), "study_id": "study_tampered"})
