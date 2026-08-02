#!/usr/bin/env python3
"""Validate a MUNI WetLabHandoff JSON artifact without repository imports."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

DISCLAIMER = (
    "DRY-LAB SIMULATION RESULTS ONLY - AWAITING WET-LAB VALIDATION; "
    "NO LABORATORY OUTCOME IS ESTABLISHED."
)
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
ID_PATTERNS = {
    "handoff_id": re.compile(r"muni_wet_lab_handoff_[0-9a-f]{32}\Z"),
    "review_id": re.compile(r"muni_review_[0-9a-f]{32}\Z"),
    "set_id": re.compile(r"muni_candidate_set_[0-9a-f]{32}\Z"),
    "study_id": re.compile(r"muni_study_[0-9a-f]{32}\Z"),
    "run_id": re.compile(r"muni_workflow_run_[0-9a-f]{32}\Z"),
}
FORBIDDEN_CLAIMS = (
    re.compile(r"\bproven\b", re.IGNORECASE),
    re.compile(r"\befficacy\b", re.IGNORECASE),
    re.compile(r"\befficacious\b", re.IGNORECASE),
    re.compile(r"\beffective\b", re.IGNORECASE),
    re.compile(r"\bkills\b", re.IGNORECASE),
    re.compile(r"\bcures?\b", re.IGNORECASE),
    re.compile(r"\bguaranteed\b", re.IGNORECASE),
    re.compile(r"\bperforms? better\b", re.IGNORECASE),
    re.compile(r"\bcontrols? (?:the )?pathogen\b", re.IGNORECASE),
    re.compile(r"\bprotects? (?:the )?crop\b", re.IGNORECASE),
    re.compile(r"효능|효과가\s*있|치료한다|방제한다|살균한다"),
)
KINDS = {"DIAGNOSTIC_DISCOVERY", "COMPOUND_SCREENING"}
DISPOSITIONS = {"RANKED", "EXCLUDED", "ABSTAINED"}
DECISIONS = {"APPROVED", "REJECTED", "NEEDS_MORE"}
SCHEMA_VERSION = "muni-research-handoff.v4"
IDENTITY_SCHEMA = "ai-scientist.identity.v1"
SAFE_INTEGER = 9_007_199_254_740_991

# Closed blocks: every field set the contract declares. Anything else is rejected;
# forward compatibility comes from a schema_version bump, not silent tolerance.
HANDOFF_FIELDS = (
    "handoff_id",
    "review_ref",
    "candidate_set_ref",
    "artifact_paths",
    "disclaimer",
    "evidence_digest",
)
PERSISTED_FIELDS = ("review_ref", "candidate_set_ref")
BOUNDARY_FIELDS = ("review_id", "candidate_set_id", "evidence_digest")
STUDY_FIELDS = (
    "study_id",
    "target_crop",
    "target_pathogen",
    "purpose",
    "created_at",
    "pack_ref",
)
REVIEW_FIELDS = (
    "review_id",
    "candidate_set_ref",
    "reviewer",
    "decision",
    "note",
    "decided_at",
)
CANDIDATE_SET_FIELDS = ("set_id", "workflow_ref", "kind", "count", "items")
PROVENANCE_FIELDS = ("collected_data",)
COLLECTED_DATA_FIELDS = ("job_ref", "source_ref", "source_record_ref", "digest")
LINEAGE_FIELDS = ("collection_adapters", "workflow")
ADAPTER_FIELDS = ("adapter_identity", "job_ref")
WORKFLOW_FIELDS = ("tool_identity", "run", "parameters")
RUN_FIELDS = ("run_id", "study_ref", "kind", "status", "started_at", "finished_at")
RATIONALE_FIELDS = (
    "reasons",
    "objective_evaluations",
    "per_objective_utility_ppm",
    "gate_result_ids",
)
UNCERTAINTY_FIELDS = ("abstention_reasons", "required_next_evidence")

# Candidate item projection rule (see CONTRACT.md 2.8): the outer item mirrors the
# hashed candidate_content field for field, and adds exactly these boundary fields.
ITEM_BOUNDARY_FIELDS = (
    "candidate_content",
    "candidate_content_hash",
    "rationale",
    "uncertainty",
)
# rationale/uncertainty are deterministic regroupings of flat content fields.
ITEM_DERIVED_PROJECTIONS = {
    "rationale": RATIONALE_FIELDS,
    "uncertainty": UNCERTAINTY_FIELDS,
}
PROJECTION_DEFAULTS = {"per_objective_utility_ppm": {}}


class IdentityError(ValueError):
    pass


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise IdentityError("surrogate code points are unsupported")
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if not -SAFE_INTEGER <= value <= SAFE_INTEGER:
            raise IdentityError("integer is outside the RFC 8785 safe range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise IdentityError("NaN and infinity are forbidden")
        raise IdentityError("binary floats are unsupported")
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise IdentityError("objects require string keys")
        return {
            key: _canonical_value(value[key])
            for key in sorted(value, key=lambda item: item.encode("utf-16-be"))
        }
    raise IdentityError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def deterministic_id(kind: str, content: dict[str, Any]) -> str:
    content_hash = digest(content)
    seed = {
        "seed_schema": IDENTITY_SCHEMA,
        "kind": kind,
        "content_hash": content_hash,
    }
    return f"{kind}_{hashlib.sha256(canonical_json(seed)).hexdigest()[:32]}"


class DuplicateKeyError(ValueError):
    pass


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def obj(self, parent: dict[str, Any], key: str, path: str) -> dict[str, Any] | None:
        if key not in parent:
            self.error(path, "required field is missing")
            return None
        value = parent[key]
        if not isinstance(value, dict):
            self.error(path, "must be an object")
            return None
        return value

    def array(
        self, parent: dict[str, Any], key: str, path: str, *, nonempty: bool = False
    ) -> list[Any] | None:
        if key not in parent:
            self.error(path, "required field is missing")
            return None
        value = parent[key]
        if not isinstance(value, list):
            self.error(path, "must be an array")
            return None
        if nonempty and not value:
            self.error(path, "must be a non-empty array")
        return value

    def string(
        self,
        parent: dict[str, Any],
        key: str,
        path: str,
        *,
        pattern: re.Pattern[str] | None = None,
        allowed: set[str] | None = None,
    ) -> str | None:
        if key not in parent:
            self.error(path, "required field is missing")
            return None
        value = parent[key]
        if not isinstance(value, str) or not value:
            self.error(path, "must be a non-empty string")
            return None
        if pattern is not None and pattern.fullmatch(value) is None:
            self.error(path, "has an invalid canonical format")
        if allowed is not None and value not in allowed:
            self.error(path, f"must be one of {sorted(allowed)}")
        return value

    def integer(
        self, parent: dict[str, Any], key: str, path: str, *, minimum: int = 0
    ) -> int | None:
        if key not in parent:
            self.error(path, "required field is missing")
            return None
        value = parent[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            self.error(path, f"must be an integer >= {minimum}")
            return None
        return value

    def require_fields(self, value: dict[str, Any], path: str, names: tuple[str, ...]) -> None:
        for name in names:
            if name not in value:
                self.error(f"{path}.{name}", "required field is missing")

    def reject_undeclared_fields(
        self, value: dict[str, Any], path: str, declared: tuple[str, ...]
    ) -> None:
        for key in sorted(value):
            if key not in declared:
                self.error(
                    f"{path}.{key}",
                    f"field is not declared in schema {SCHEMA_VERSION}",
                )


def _verify_item_projection(v: Validator, index: int, item: dict[str, Any]) -> None:
    """Bind the outer candidate item fields to the hashed candidate_content.

    The producer projects every candidate_content field to the outer item level
    unchanged and adds exactly the boundary fields (candidate_content,
    candidate_content_hash, rationale, uncertainty). rationale/uncertainty are
    deterministic regroupings of flat content fields. Any disagreement between
    the flat level and the hashed content is corruption or forgery.
    """
    content = item.get("candidate_content")
    if not isinstance(content, dict):
        return
    item_path = f"$.candidate_set.items[{index}]"
    for key in sorted(content):
        outer_path = f"{item_path}.{key}"
        if key not in item:
            v.error(
                outer_path,
                f"must mirror candidate_content.{key}: outer field is missing",
            )
        elif item[key] != content[key]:
            v.error(
                outer_path,
                f"must equal candidate_content.{key}: outer value {item[key]!r} "
                f"differs from hashed content value {content[key]!r}",
            )
    for key in sorted(item):
        if key not in content and key not in ITEM_BOUNDARY_FIELDS:
            v.error(
                f"{item_path}.{key}",
                "outer candidate field is not mirrored from candidate_content "
                f"and is not declared in schema {SCHEMA_VERSION}",
            )
    for derived, source_fields in ITEM_DERIVED_PROJECTIONS.items():
        projected = item.get(derived)
        if not isinstance(projected, dict):
            continue
        expected = {
            name: content.get(name, PROJECTION_DEFAULTS.get(name, []))
            for name in source_fields
        }
        if projected != expected:
            v.error(
                f"{item_path}.{derived}",
                f"must equal the projection of candidate_content fields "
                f"{list(source_fields)}: outer value {projected!r} "
                f"differs from projected content value {expected!r}",
            )


def validate(payload: Any) -> list[str]:
    v = Validator()
    if not isinstance(payload, dict):
        return ["$: top-level JSON value must be an object"]

    v.require_fields(
        payload,
        "$",
        (
            "schema_version",
            "handoff",
            "persisted",
            "boundary",
            "disclaimer",
            "study",
            "review",
            "candidate_set",
            "provenance",
            "lineage",
        ),
    )
    schema_version = v.string(payload, "schema_version", "$.schema_version")
    if schema_version is not None and schema_version != SCHEMA_VERSION:
        v.error("$.schema_version", f"must equal {SCHEMA_VERSION!r}")

    disclaimer = v.string(payload, "disclaimer", "$.disclaimer")
    if disclaimer is not None and disclaimer != DISCLAIMER:
        v.error("$.disclaimer", "must contain the canonical dry-lab disclaimer unchanged")

    handoff = v.obj(payload, "handoff", "$.handoff")
    persisted = v.obj(payload, "persisted", "$.persisted")
    boundary = v.obj(payload, "boundary", "$.boundary")
    study = v.obj(payload, "study", "$.study")
    review = v.obj(payload, "review", "$.review")
    candidate_set = v.obj(payload, "candidate_set", "$.candidate_set")
    provenance = v.obj(payload, "provenance", "$.provenance")
    lineage = v.obj(payload, "lineage", "$.lineage")

    handoff_id = review_ref = handoff_candidate_set_ref = nested_disclaimer = None
    handoff_evidence_digest = None
    if handoff is not None:
        v.require_fields(handoff, "$.handoff", HANDOFF_FIELDS)
        v.reject_undeclared_fields(handoff, "$.handoff", HANDOFF_FIELDS)
        handoff_id = v.string(handoff, "handoff_id", "$.handoff.handoff_id", pattern=ID_PATTERNS["handoff_id"])
        review_ref = v.string(handoff, "review_ref", "$.handoff.review_ref", pattern=ID_PATTERNS["review_id"])
        handoff_candidate_set_ref = v.string(handoff, "candidate_set_ref", "$.handoff.candidate_set_ref", pattern=ID_PATTERNS["set_id"])
        paths = v.array(handoff, "artifact_paths", "$.handoff.artifact_paths", nonempty=True)
        if paths is not None:
            for index, value in enumerate(paths):
                if not isinstance(value, str) or not value:
                    v.error(f"$.handoff.artifact_paths[{index}]", "must be a non-empty string")
        nested_disclaimer = v.string(handoff, "disclaimer", "$.handoff.disclaimer")
        handoff_evidence_digest = v.string(
            handoff,
            "evidence_digest",
            "$.handoff.evidence_digest",
            pattern=SHA256,
        )
        if nested_disclaimer is not None and nested_disclaimer != DISCLAIMER:
            v.error("$.handoff.disclaimer", "must contain the canonical dry-lab disclaimer unchanged")

    persisted_review_ref = persisted_candidate_set_ref = None
    if persisted is not None:
        v.require_fields(persisted, "$.persisted", PERSISTED_FIELDS)
        v.reject_undeclared_fields(persisted, "$.persisted", PERSISTED_FIELDS)
        persisted_review_ref = v.string(
            persisted, "review_ref", "$.persisted.review_ref", pattern=ID_PATTERNS["review_id"]
        )
        persisted_candidate_set_ref = v.string(
            persisted,
            "candidate_set_ref",
            "$.persisted.candidate_set_ref",
            pattern=ID_PATTERNS["set_id"],
        )

    boundary_review_id = boundary_candidate_set_id = evidence_digest = None
    if boundary is not None:
        v.require_fields(boundary, "$.boundary", BOUNDARY_FIELDS)
        v.reject_undeclared_fields(boundary, "$.boundary", BOUNDARY_FIELDS)
        boundary_review_id = v.string(
            boundary, "review_id", "$.boundary.review_id", pattern=ID_PATTERNS["review_id"]
        )
        boundary_candidate_set_id = v.string(
            boundary,
            "candidate_set_id",
            "$.boundary.candidate_set_id",
            pattern=ID_PATTERNS["set_id"],
        )
        evidence_digest = v.string(
            boundary,
            "evidence_digest",
            "$.boundary.evidence_digest",
            pattern=SHA256,
        )

    study_id = None
    if study is not None:
        v.require_fields(study, "$.study", STUDY_FIELDS)
        v.reject_undeclared_fields(study, "$.study", STUDY_FIELDS)
        study_id = v.string(study, "study_id", "$.study.study_id", pattern=ID_PATTERNS["study_id"])
        v.string(study, "target_crop", "$.study.target_crop")
        v.string(study, "target_pathogen", "$.study.target_pathogen")
        v.string(study, "purpose", "$.study.purpose")
        v.string(study, "created_at", "$.study.created_at", pattern=TIMESTAMP)
        if study.get("pack_ref") is not None:
            v.string(study, "pack_ref", "$.study.pack_ref")

    review_id = candidate_set_ref = None
    if review is not None:
        v.require_fields(review, "$.review", REVIEW_FIELDS)
        v.reject_undeclared_fields(review, "$.review", REVIEW_FIELDS)
        review_id = v.string(review, "review_id", "$.review.review_id", pattern=ID_PATTERNS["review_id"])
        candidate_set_ref = v.string(review, "candidate_set_ref", "$.review.candidate_set_ref", pattern=ID_PATTERNS["set_id"])
        v.string(review, "reviewer", "$.review.reviewer")
        decision = v.string(review, "decision", "$.review.decision", allowed=DECISIONS)
        if decision is not None and decision != "APPROVED":
            v.error("$.review.decision", "must be 'APPROVED' for a handoff")
        v.string(review, "note", "$.review.note")
        v.string(review, "decided_at", "$.review.decided_at", pattern=TIMESTAMP)

    set_id = workflow_ref = None
    if candidate_set is not None:
        v.require_fields(candidate_set, "$.candidate_set", CANDIDATE_SET_FIELDS)
        v.reject_undeclared_fields(candidate_set, "$.candidate_set", CANDIDATE_SET_FIELDS)
        set_id = v.string(candidate_set, "set_id", "$.candidate_set.set_id", pattern=ID_PATTERNS["set_id"])
        workflow_ref = v.string(candidate_set, "workflow_ref", "$.candidate_set.workflow_ref", pattern=ID_PATTERNS["run_id"])
        v.string(candidate_set, "kind", "$.candidate_set.kind", allowed=KINDS)
        count = v.integer(candidate_set, "count", "$.candidate_set.count")
        items = v.array(candidate_set, "items", "$.candidate_set.items")
        if items is not None:
            if count is not None and count != len(items):
                v.error("$.candidate_set.count", "must equal the number of candidate items")
            for index, item in enumerate(items):
                path = f"$.candidate_set.items[{index}]"
                if not isinstance(item, dict):
                    v.error(path, "must be an object")
                    continue
                v.require_fields(item, path, ("candidate_id", "candidate_content", "candidate_content_hash", "query_revision_id", "disposition", "composite_score_ppm", "rationale", "uncertainty"))
                v.string(item, "candidate_id", f"{path}.candidate_id")
                v.obj(item, "candidate_content", f"{path}.candidate_content")
                v.string(item, "candidate_content_hash", f"{path}.candidate_content_hash", pattern=SHA256)
                v.string(item, "query_revision_id", f"{path}.query_revision_id")
                disposition = v.string(item, "disposition", f"{path}.disposition", allowed=DISPOSITIONS)
                score = item.get("composite_score_ppm")
                if disposition == "RANKED":
                    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 1_000_000:
                        v.error(f"{path}.composite_score_ppm", "must be an integer from 0 through 1000000 for RANKED candidates")
                elif disposition in {"EXCLUDED", "ABSTAINED"} and score is not None:
                    v.error(f"{path}.composite_score_ppm", "must be null for EXCLUDED or ABSTAINED candidates")
                rationale = v.obj(item, "rationale", f"{path}.rationale")
                uncertainty = v.obj(item, "uncertainty", f"{path}.uncertainty")
                if rationale is not None:
                    rationale_path = f"{path}.rationale"
                    v.require_fields(rationale, rationale_path, RATIONALE_FIELDS)
                    v.reject_undeclared_fields(rationale, rationale_path, RATIONALE_FIELDS)
                    for name in ("reasons", "objective_evaluations", "gate_result_ids"):
                        v.array(rationale, name, f"{rationale_path}.{name}")
                    utilities = v.obj(rationale, "per_objective_utility_ppm", f"{rationale_path}.per_objective_utility_ppm")
                    if utilities is not None:
                        for name, utility in utilities.items():
                            if not isinstance(name, str) or not name or not isinstance(utility, int) or isinstance(utility, bool) or not 0 <= utility <= 1_000_000:
                                v.error(f"{rationale_path}.per_objective_utility_ppm", "keys must be non-empty strings and values integers from 0 through 1000000")
                                break
                if uncertainty is not None:
                    uncertainty_path = f"{path}.uncertainty"
                    v.require_fields(uncertainty, uncertainty_path, UNCERTAINTY_FIELDS)
                    v.reject_undeclared_fields(uncertainty, uncertainty_path, UNCERTAINTY_FIELDS)
                    for name in ("abstention_reasons", "required_next_evidence"):
                        values = v.array(uncertainty, name, f"{uncertainty_path}.{name}")
                        if values is not None and any(not isinstance(value, str) or not value for value in values):
                            v.error(f"{uncertainty_path}.{name}", "must contain only non-empty strings")

    provenance_jobs: dict[str, str] = {}
    if provenance is not None:
        v.reject_undeclared_fields(provenance, "$.provenance", PROVENANCE_FIELDS)
        collected = v.array(provenance, "collected_data", "$.provenance.collected_data", nonempty=True)
        if collected is not None:
            for index, item in enumerate(collected):
                path = f"$.provenance.collected_data[{index}]"
                if not isinstance(item, dict):
                    v.error(path, "must be an object")
                    continue
                v.require_fields(item, path, COLLECTED_DATA_FIELDS)
                v.reject_undeclared_fields(item, path, COLLECTED_DATA_FIELDS)
                job_ref = v.string(item, "job_ref", f"{path}.job_ref")
                source_ref = v.string(item, "source_ref", f"{path}.source_ref")
                v.string(item, "source_record_ref", f"{path}.source_record_ref")
                v.string(item, "digest", f"{path}.digest", pattern=SHA256)
                if job_ref is not None and source_ref is not None:
                    provenance_jobs[job_ref] = source_ref

    if lineage is not None:
        v.reject_undeclared_fields(lineage, "$.lineage", LINEAGE_FIELDS)
        adapters = v.array(lineage, "collection_adapters", "$.lineage.collection_adapters", nonempty=True)
        workflow = v.obj(lineage, "workflow", "$.lineage.workflow")
        adapter_jobs: dict[str, str] = {}
        if adapters is not None:
            for index, item in enumerate(adapters):
                path = f"$.lineage.collection_adapters[{index}]"
                if not isinstance(item, dict):
                    v.error(path, "must be an object")
                    continue
                v.require_fields(item, path, ADAPTER_FIELDS)
                v.reject_undeclared_fields(item, path, ADAPTER_FIELDS)
                identity = v.string(item, "adapter_identity", f"{path}.adapter_identity")
                job_ref = v.string(item, "job_ref", f"{path}.job_ref")
                if job_ref is not None and identity is not None:
                    adapter_jobs[job_ref] = identity
        if provenance_jobs != adapter_jobs:
            v.error("$.lineage.collection_adapters", "must align job_ref and source identity exactly with provenance.collected_data")
        if workflow is not None:
            v.require_fields(workflow, "$.lineage.workflow", WORKFLOW_FIELDS)
            v.reject_undeclared_fields(workflow, "$.lineage.workflow", WORKFLOW_FIELDS)
            v.string(workflow, "tool_identity", "$.lineage.workflow.tool_identity")
            parameters = v.obj(workflow, "parameters", "$.lineage.workflow.parameters")
            if parameters is not None and not parameters:
                v.error("$.lineage.workflow.parameters", "must be a non-empty object")
            run = v.obj(workflow, "run", "$.lineage.workflow.run")
            if run is not None:
                v.require_fields(run, "$.lineage.workflow.run", RUN_FIELDS)
                v.reject_undeclared_fields(run, "$.lineage.workflow.run", RUN_FIELDS)
                run_id = v.string(run, "run_id", "$.lineage.workflow.run.run_id", pattern=ID_PATTERNS["run_id"])
                run_study_ref = v.string(run, "study_ref", "$.lineage.workflow.run.study_ref", pattern=ID_PATTERNS["study_id"])
                run_kind = v.string(run, "kind", "$.lineage.workflow.run.kind", allowed=KINDS)
                status = v.string(run, "status", "$.lineage.workflow.run.status")
                if status is not None and status != "SUCCEEDED":
                    v.error("$.lineage.workflow.run.status", "must be 'SUCCEEDED'")
                started_at = v.string(run, "started_at", "$.lineage.workflow.run.started_at", pattern=TIMESTAMP)
                finished_at = v.string(run, "finished_at", "$.lineage.workflow.run.finished_at", pattern=TIMESTAMP)
                if (
                    started_at is not None
                    and finished_at is not None
                    and TIMESTAMP.fullmatch(started_at) is not None
                    and TIMESTAMP.fullmatch(finished_at) is not None
                    and finished_at < started_at
                ):
                    v.error(
                        "$.lineage.workflow.run.finished_at",
                        "must not precede $.lineage.workflow.run.started_at: "
                        f"finished_at {finished_at!r} is earlier than started_at {started_at!r}",
                    )
                if workflow_ref is not None and run_id is not None and workflow_ref != run_id:
                    v.error("$.candidate_set.workflow_ref", "must equal $.lineage.workflow.run.run_id")
                if study_id is not None and run_study_ref is not None and study_id != run_study_ref:
                    v.error("$.lineage.workflow.run.study_ref", "must equal $.study.study_id")
                if candidate_set is not None and run_kind is not None and candidate_set.get("kind") != run_kind:
                    v.error("$.lineage.workflow.run.kind", "must equal $.candidate_set.kind")

    if review_ref is not None and persisted_review_ref is not None and review_ref != persisted_review_ref:
        v.error("$.handoff.review_ref", "must equal $.persisted.review_ref")
    if (
        handoff_candidate_set_ref is not None
        and persisted_candidate_set_ref is not None
        and handoff_candidate_set_ref != persisted_candidate_set_ref
    ):
        v.error("$.handoff.candidate_set_ref", "must equal $.persisted.candidate_set_ref")
    if review_id is not None and persisted_review_ref is not None and review_id != persisted_review_ref:
        v.error("$.review.review_id", "must equal $.persisted.review_ref")
    if set_id is not None and persisted_candidate_set_ref is not None and set_id != persisted_candidate_set_ref:
        v.error("$.candidate_set.set_id", "must equal $.persisted.candidate_set_ref")
    if candidate_set_ref is not None and set_id is not None and candidate_set_ref != set_id:
        v.error("$.review.candidate_set_ref", "must equal $.candidate_set.set_id")
    if disclaimer is not None and nested_disclaimer is not None and disclaimer != nested_disclaimer:
        v.error("$.handoff.disclaimer", "must equal $.disclaimer")
    if (
        evidence_digest is not None
        and handoff_evidence_digest is not None
        and evidence_digest != handoff_evidence_digest
    ):
        v.error("$.handoff.evidence_digest", "must equal $.boundary.evidence_digest")

    def verify_identity(
        path: str,
        value: dict[str, Any] | None,
        identity_field: str,
        kind: str,
        content_fields: tuple[str, ...],
    ) -> None:
        if value is None:
            v.error(path, "cannot verify identity: identity object is missing or malformed")
            return
        missing = [name for name in (identity_field, *content_fields) if name not in value]
        if missing:
            v.error(path, f"cannot verify identity: required identity material is missing: {', '.join(missing)}")
            return
        try:
            expected = deterministic_id(kind, {name: value[name] for name in content_fields})
        except (IdentityError, UnicodeError) as exc:
            v.error(path, f"cannot verify identity: {exc}")
            return
        actual = value[identity_field]
        if actual != expected:
            v.error(path, f"identity mismatch: expected {expected}, actual {actual}")

    verify_identity(
        "$.study.study_id", study, "study_id", "muni_study",
        ("target_crop", "target_pathogen", "purpose", "created_at", "pack_ref"),
    )
    boundary_candidate_set = None
    if candidate_set is not None and boundary_candidate_set_id is not None:
        boundary_candidate_set = dict(candidate_set)
        boundary_candidate_set["candidate_set_id"] = boundary_candidate_set_id
    verify_identity(
        "$.boundary.candidate_set_id",
        boundary_candidate_set,
        "candidate_set_id",
        "muni_candidate_set",
        ("workflow_ref", "kind", "items", "count"),
    )
    boundary_review = None
    if (
        review is not None
        and boundary_review_id is not None
        and boundary_candidate_set_id is not None
    ):
        boundary_review = dict(review)
        boundary_review["review_id"] = boundary_review_id
        boundary_review["candidate_set_ref"] = boundary_candidate_set_id
    verify_identity(
        "$.boundary.review_id",
        boundary_review,
        "review_id",
        "muni_review",
        ("candidate_set_ref", "reviewer", "decision", "note", "decided_at"),
    )
    if provenance is None or lineage is None or evidence_digest is None:
        missing_evidence = []
        if provenance is None:
            missing_evidence.append("provenance")
        if lineage is None:
            missing_evidence.append("lineage")
        if evidence_digest is None:
            missing_evidence.append("boundary.evidence_digest")
        v.error(
            "$.boundary.evidence_digest",
            "cannot verify evidence digest: required evidence material is missing or malformed: "
            + ", ".join(missing_evidence),
        )
    else:
        try:
            expected_evidence_digest = digest(
                {"provenance": provenance, "lineage": lineage}
            )
        except (IdentityError, UnicodeError) as exc:
            v.error(
                "$.boundary.evidence_digest",
                f"cannot verify evidence digest: {exc}",
            )
        else:
            if evidence_digest != expected_evidence_digest:
                v.error(
                    "$.boundary.evidence_digest",
                    "digest mismatch: "
                    f"expected {expected_evidence_digest}, actual {evidence_digest}",
                )

    verify_identity(
        "$.handoff.handoff_id",
        handoff,
        "handoff_id",
        "muni_wet_lab_handoff",
        ("review_ref", "artifact_paths", "disclaimer", "evidence_digest"),
    )

    if candidate_set is not None and isinstance(candidate_set.get("items"), list):
        for index, item in enumerate(candidate_set["items"]):
            if not isinstance(item, dict):
                continue
            _verify_item_projection(v, index, item)
            path = f"$.candidate_set.items[{index}].candidate_content_hash"
            missing = [
                name for name in ("candidate_content", "candidate_content_hash")
                if name not in item
            ]
            if missing:
                v.error(path, f"cannot verify identity: required identity material is missing: {', '.join(missing)}")
                continue
            try:
                expected = digest(item["candidate_content"])
            except (IdentityError, UnicodeError) as exc:
                v.error(path, f"cannot verify identity: {exc}")
                continue
            actual = item["candidate_content_hash"]
            if actual != expected:
                v.error(path, f"identity mismatch: expected {expected}, actual {actual}")

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for pattern in FORBIDDEN_CLAIMS:
        match = pattern.search(serialized)
        if match is not None:
            v.error("$", f"forbidden efficacy-claim vocabulary found: {match.group(0)!r}")
    return list(dict.fromkeys(v.errors))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <path-to-handoff.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"INVALID {path}", file=sys.stderr)
        print(f"- $: cannot read file: {exc}", file=sys.stderr)
        return 2
    try:
        payload = json.loads(raw, object_pairs_hook=_object_no_duplicates)
    except (json.JSONDecodeError, DuplicateKeyError) as exc:
        print(f"INVALID {path}", file=sys.stderr)
        print(f"- $: malformed JSON: {exc}", file=sys.stderr)
        return 1
    errors = validate(payload)
    if errors:
        print(f"INVALID {path}")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"VALID {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
