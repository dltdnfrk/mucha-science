"""Deterministic scientific-report projection with detached accountability overlay."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from src.pipeline.scientific_contracts import (
    ContractError, byte_digest, canonical_json, decode_json_object,
)


REPORT_FORMAT = "scientific-report-body.v1"
ASSURANCE_LABEL = "asserted/unverified; no identity, authority, or approval is verified"
PHYSICAL_BOUNDARY_LABEL = "physical execution is external completed work; this report commands no physical action"


class ReportProjectionError(ValueError):
    """Raised when a caller tries to include final accountability in report bytes."""


@dataclass(frozen=True)
class ScientificReportBody:
    """Exact immutable bytes and their byte hash."""
    body_utf8: bytes
    body_hash: str
    content: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.body_utf8.endswith(b"\n") or self.body_utf8.endswith(b"\n\n"):
            raise ReportProjectionError("scientific report bodies must end in exactly one LF")
        if self.body_hash != byte_digest(self.body_utf8):
            raise ReportProjectionError("report body hash must cover exact UTF-8 bytes")
        try:
            content = decode_json_object(self.body_utf8[:-1])
        except ContractError as exc:
            raise ReportProjectionError("scientific report body must be canonical JSON") from exc
        if not isinstance(content, Mapping) or canonical_json(content) + b"\n" != self.body_utf8:
            raise ReportProjectionError("scientific report body must be canonical JSON")
        object.__setattr__(self, "content", _freeze_value(content))

def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value

def _reject_final_accountability(value: Any) -> None:
    """Reject caller-supplied final-accountability data rather than masking it."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key.startswith("final_accountability"):
                raise ReportProjectionError("report body must not contain final accountability")
            _reject_final_accountability(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _reject_final_accountability(item)


def compose_scientific_report_body(*, cycle_id: str, source_revision: int,
                                   reducer_output: Mapping[str, Any],
                                   policy_output: Mapping[str, Any],
                                   hitl_output: Mapping[str, Any],
                                   limitations: tuple[str, ...] | list[str]) -> ScientificReportBody:
    """Compose bytes from already-derived projections; this function performs no validation or HITL reduction."""
    if not cycle_id or source_revision < 0 or any(not item for item in limitations):
        raise ReportProjectionError("invalid immutable report projection input")
    _reject_final_accountability(reducer_output)
    _reject_final_accountability(policy_output)
    _reject_final_accountability(hitl_output)
    content: dict[str, Any] = {
        "format": REPORT_FORMAT,
        "cycle_id": cycle_id,
        "source_revision": source_revision,
        "scientific": dict(reducer_output),
        "validation": dict(policy_output),
        "responsibilities": dict(hitl_output),
        "limitations": list(limitations),
        "authority_assurance": ASSURANCE_LABEL,
        "physical_execution_boundary": PHYSICAL_BOUNDARY_LABEL,
    }
    body_utf8 = canonical_json(content) + b"\n"
    return ScientificReportBody(body_utf8, byte_digest(body_utf8), content)


def render_status_overlay(*, report_body_id: str, at_revision: int,
                          final_accountability_status: str,
                          disposition_id: str | None, generated_at: str) -> dict[str, Any]:
    """Return the non-authoritative, non-hashed final-accountability display projection."""
    if (not report_body_id or at_revision < 0 or not generated_at
            or final_accountability_status not in {"pending", "satisfied"}):
        raise ReportProjectionError("invalid status overlay input")
    if final_accountability_status == "satisfied":
        if not isinstance(disposition_id, str) or not disposition_id:
            raise ReportProjectionError("satisfied status overlay requires a committed disposition ID")
    elif disposition_id is not None:
        raise ReportProjectionError("pending status overlay must not name a disposition")
    return {
        "report_body_id": report_body_id,
        "at_revision": at_revision,
        "final_accountability_status": final_accountability_status,
        "disposition_id": disposition_id,
        "label": "final accountability is a detached asserted/unverified status overlay",
        "generated_at": generated_at,
    }


class ScientificReportProjector:
    """The sole report composer for the scientific-cycle domain."""

    def compose(self, **kwargs: Any) -> ScientificReportBody:
        return compose_scientific_report_body(**kwargs)
    def compose_from_state(self, *, state: Mapping[str, Any], source_revision: int,
                           body_kind: str, limitations: tuple[str, ...]) -> ScientificReportBody:
        """Derive immutable body bytes exclusively from committed reducer records."""
        if body_kind not in {"interim", "final"} or source_revision != state.get("revision"):
            raise ReportProjectionError("report projection must use the exact committed revision")
        records = state.get("records")
        requirements = state.get("requirements")
        dispositions = state.get("dispositions")
        if not isinstance(records, Mapping):
            raise ReportProjectionError("report projection requires committed records")
        if not isinstance(requirements, Mapping) or not isinstance(dispositions, Mapping):
            raise ReportProjectionError("report projection requires committed requirements and dispositions mappings")
        if (not all(isinstance(key, str) and isinstance(value, str) for key, value in requirements.items())
                or not all(isinstance(key, str) and isinstance(value, str) for key, value in dispositions.items())):
            raise ReportProjectionError("committed requirements and dispositions mappings must contain string IDs")
        scientific = {
            record_id: record["content"] for record_id, record in records.items()
            if isinstance(record, Mapping) and record.get("record_type") in {
                "landscape_artifact", "claim", "proposal", "controlled_import_result", "analysis_artifact", "stage"
            }
        }
        validation: dict[str, Any] = {}
        assessments = state.get("assessments")
        if not isinstance(assessments, Mapping):
            raise ReportProjectionError("report projection requires committed current assessments")
        for assessment_id, assessment in assessments.items():
            if not isinstance(assessment_id, str) or not assessment_id:
                raise ReportProjectionError("current assessment identity must be a nonempty string")
            identity_record = records.get(assessment_id)
            if (not isinstance(identity_record, Mapping)
                    or identity_record.get("id") != assessment_id
                    or identity_record.get("record_type") != "validation_assessment"
                    or not isinstance(assessment, Mapping)
                    or not isinstance(assessment.get("id"), str)
                    or assessment.get("record_type") != "validation_assessment"
                    or records.get(assessment["id"]) != assessment):
                raise ReportProjectionError("current assessment must reference committed assessment records")
            content = assessment.get("content")
            if not isinstance(content, Mapping):
                raise ReportProjectionError("current assessment record must contain content")
            validation[assessment["id"]] = content
        responsibility_requirements: dict[str, str] = {}
        responsibility_dispositions: dict[str, str] = {}
        for responsibility, requirement_id in requirements.items():
            requirement = records.get(requirement_id)
            if not isinstance(requirement, Mapping) or requirement.get("record_type") != "responsibility_requirement":
                raise ReportProjectionError("requirements mapping must reference committed requirement records")
            content = requirement.get("content")
            if not isinstance(content, Mapping) or content.get("responsibility") != responsibility:
                raise ReportProjectionError("requirements mapping responsibility does not match committed record")
            if responsibility == "final_accountability":
                continue
            responsibility_requirements[responsibility] = requirement_id
            disposition_id = dispositions.get(requirement_id)
            if disposition_id is None:
                continue
            disposition = records.get(disposition_id)
            if not isinstance(disposition, Mapping) or disposition.get("record_type") != "responsibility_disposition":
                raise ReportProjectionError("dispositions mapping must reference committed disposition records")
            disposition_content = disposition.get("content")
            if (not isinstance(disposition_content, Mapping)
                    or disposition_content.get("responsibility") != responsibility
                    or disposition_content.get("requirement_id") != requirement_id
                    or disposition_content.get("scope_hash") != content.get("scope_hash")):
                raise ReportProjectionError("dispositions mapping must bind the current requirement and scope")
            responsibility_dispositions[requirement_id] = disposition_id
        responsibilities = {
            "requirements": responsibility_requirements,
            "dispositions": responsibility_dispositions,
        }
        return self.compose(cycle_id=state["cycle_id"], source_revision=source_revision,
                            reducer_output=scientific, policy_output=validation,
                            hitl_output=responsibilities, limitations=limitations)
    def verify_exact_bytes(self, body_utf8: bytes, body_hash: str) -> None:
        """Verify a detached caller binding covers the exact rendered report bytes."""
        if not body_utf8.endswith(b"\n") or body_utf8.endswith(b"\n\n"):
            raise ReportProjectionError("scientific report bodies must end in exactly one LF")
        if byte_digest(body_utf8) != body_hash:
            raise ReportProjectionError("report body hash must cover exact UTF-8 bytes")

    def status_overlay(self, **kwargs: Any) -> dict[str, Any]:
        return render_status_overlay(**kwargs)
