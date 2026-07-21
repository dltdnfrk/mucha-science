"""Authoritative, side-effect-free reducer for scientific cycle ledgers."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Mapping

from .scientific_contracts import (
    ContractError, Responsibility, actor_assertion_from_mapping, canonical_id_array,
    canonical_json, content_record, digest, performer_from_mapping,
    stage_boundary_from_mapping, validate_adjudication_payload,
    validate_continue_payload, validate_disposition_payload, validate_export_payload,
    validate_supersede_payload,
)
from src.hitl.signoff_core import SignoffCore, SignoffError
from src.report.scientific_projector import ScientificReportProjector
from src.council.scientific_hypotheses import HypothesisError, HypothesisLifecycle
from src.evidence.scientific_validation import (
    ApplicabilityContext, ValidationError, adjudicate_current, aggregate_support,
    assessment_from_source, policy_from_source,
)


class CycleError(ValueError):
    """A lifecycle command cannot be applied."""


class GateUnsatisfied(CycleError):
    """A command's durable lifecycle precondition is not met."""


@dataclass(frozen=True)
class Reduction:
    state: dict[str, Any]
    event_name: str
    event_payload: dict[str, Any]
    result: dict[str, Any]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateUnsatisfied(message)


def _current(state: Mapping[str, Any], kind: str) -> Any:
    return state["current"].get(kind)

def _canonical_ids(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise ContractError("ID array must be a list or tuple")
    if any(not isinstance(value, str) for value in values):
        raise ContractError("IDs must be protocol IDs")
    return list(canonical_id_array(tuple(sorted(set(values)))))
def _materialize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _materialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_materialize(item) for item in value]
    return value



def _canonical_stage_input(data: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(data)
    if result["kind"] not in {"execution.not_run", "cycle.complete"}:
        result["accountable_party"] = actor_assertion_from_mapping(result["accountable_party"])
        _require(
            result["accountable_party"]["actor_kind"] == "human",
            "completed stages require a human accountable party",
        )
        result["performers"] = [performer_from_mapping(item) for item in result["performers"]]
    if "boundary" in result:
        result["boundary"] = stage_boundary_from_mapping(result["boundary"])
    return result


def initial_state(cycle_id: str, raw_question: str, contract_version: str,
                  boundary: Mapping[str, Any], creator: Mapping[str, Any]) -> dict[str, Any]:
    from .scientific_contracts import normalize_question
    question = normalize_question(raw_question)
    canonical_creator = actor_assertion_from_mapping(creator)
    canonical_boundary = stage_boundary_from_mapping(boundary)
    state: dict[str, Any] = {
        "cycle_id": cycle_id, "revision": 0, "sequence": 0, "terminal": None,
        "question": question, "contract_version": contract_version, "boundary": canonical_boundary,
        "creator": canonical_creator, "records": {}, "current": {"claims": [], "results": []},
        "requirements": {}, "dispositions": {}, "stages": [], "assessments": {},
    }
    cycle = content_record("cycle", {"normalized_question": question, "contract_version": contract_version,
                                      "boundary": canonical_boundary, "creator": canonical_creator}, {"cycle_id": cycle_id})
    state["records"][cycle["id"]] = cycle
    for ordinal, responsibility in enumerate(Responsibility):
        content = {"cycle_id": cycle_id, "responsibility": responsibility.value,
                   "requirement_ordinal": ordinal, "scope_kind": "cycle", "scope_ids": [],
                   "scope_hash": digest({"scope_kind": "cycle", "scope_ids": []}), "status_at_creation": "pending",
                   "supersedes_requirement_id": None}
        record = content_record("responsibility_requirement", content,
                                {"cycle_id": cycle_id, "responsibility": responsibility.value, "ordinal": ordinal})
        state["records"][record["id"]] = record
        state["requirements"][responsibility.value] = record["id"]
    return state


class ScientificCycleReducer:
    """The only lifecycle transition authority; it never performs physical execution."""

    def apply(self, state: Mapping[str, Any], action: Mapping[str, Any]) -> Reduction:
        state = deepcopy(dict(state))
        payload = action.get("payload", action)
        if not isinstance(payload, Mapping):
            raise CycleError("command payload must be an object")
        if state.get("terminal"):
            raise GateUnsatisfied("cycle is terminal")
        name = str(action.get("name", ""))
        try:
            if name == "cycle.continue": return self._continue(state, payload)
            if name.startswith("responsibility.") and name.endswith(".disposition"): return self._disposition(state, name, payload)
            if name == "responsibility.disposition.supersede": return self._supersede(state, payload)
            if name == "proposal.reject": return self._reject_proposal(state, payload)
            if name == "result.submit": return self._result(state, payload)
            if name == "validation.adjudicate": return self._adjudicate(state, payload)
            if name == "export.create": return self._export(state, payload)
            if name == "cycle.abort": return self._abort(state, payload)
        except (ContractError, SignoffError, ValidationError) as exc:
            raise GateUnsatisfied(str(exc)) from exc
        raise CycleError("unsupported lifecycle command")

    def _record(self, state: dict[str, Any], record_type: str, content: Mapping[str, Any]) -> dict[str, Any]:
        record = content_record(record_type, content, {"cycle_id": state["cycle_id"], "ordinal": len(state["records"]), "content_hash": digest(content)})
        state["records"][record["id"]] = record
        return record

    def _stage(self, state: dict[str, Any], stage: str, data: Mapping[str, Any], *, artifact_ids: list[str] | None = None,
               proposal_id: str | None = None, proposal_hash: str | None = None, result_ids: list[str] | None = None,
               report_body_id: str | None = None) -> dict[str, Any]:
        artifact_ids = _canonical_ids(artifact_ids or ())
        result_ids = _canonical_ids(result_ids or ())
        ordinal = sum(item["content"]["stage"] == stage for item in state["stages"])
        content = {"cycle_id": state["cycle_id"], "stage": stage, "stage_ordinal": ordinal,
                   "origin": "muchanipo", "status": "not_run" if stage == "X" else "completed",
                   "execution_kind": data["execution_kind"], "accountable_party": data["accountable_party"],
                   "performers": data["performers"], "automation_mode": data["automation_mode"],
                   "boundary": data["boundary"], "started_at": data["started_at"], "completed_at": data["completed_at"],
                   "artifact_ids": artifact_ids, "proposal_id": proposal_id, "proposal_hash": proposal_hash,
                   "result_ids": result_ids, "report_body_id": report_body_id, "supersedes_stage_id": None}
        record = self._record(state, "stage", content)
        state["stages"].append(record)
        return record

    def _rescope(self, state: dict[str, Any], responsibility: Responsibility, kind: str, ids: list[str]) -> str:
        old = state["requirements"][responsibility.value]
        if kind == "report_body":
            if (len(ids) != 2
                    or not re.fullmatch(r"[a-z][a-z0-9_]*_[0-9a-f]{32}", ids[0])
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", ids[1])):
                raise ContractError("report-body scope must contain its canonical ID and hash")
            scope_ids = list(ids)
        else:
            scope_ids = _canonical_ids(ids)
        content = {"cycle_id": state["cycle_id"], "responsibility": responsibility.value,
                   "requirement_ordinal": sum(record["content"].get("responsibility") == responsibility.value for record in state["records"].values()),
                   "scope_kind": kind, "scope_ids": scope_ids, "scope_hash": digest({"scope_kind": kind, "scope_ids": scope_ids}),
                   "status_at_creation": "pending", "supersedes_requirement_id": old}
        record = self._record(state, "responsibility_requirement", content)
        state["requirements"][responsibility.value] = record["id"]
        return record["id"]
    def _invalidate_downstream(self, state: dict[str, Any], *, claims: bool = False,
                               proposal: bool = False, results: bool = False,
                               analysis: bool = False, report: bool = False) -> None:
        """Clear only mutable current references; append replacement gates for stale scopes."""
        if claims:
            state["current"]["claims"] = []
            state["current"].pop("hypothesis", None)
            self._rescope(state, Responsibility.NOVELTY_VALUE_JUDGMENT, "claims", [])
            proposal = True
        if proposal:
            state["current"].pop("proposal", None)
            state["current"].pop("local_x", None)
            for responsibility in (Responsibility.SAFETY_ETHICS_REVIEW, Responsibility.EXECUTION_ACCOUNTABILITY):
                self._rescope(state, responsibility, "proposal", [])
            results = True
        if results:
            state["current"]["results"] = []
            self._rescope(state, Responsibility.EXCEPTION_INTERPRETATION, "results", [])
            analysis = True
        if analysis:
            state["current"].pop("analysis", None)
            state["current"].pop("support", None)
            report = True
        if report:
            state["current"].pop("final_report", None)
            self._rescope(state, Responsibility.FINAL_ACCOUNTABILITY, "cycle", [])


    def _continue(self, state: dict[str, Any], payload: Mapping[str, Any]) -> Reduction:
        validate_continue_payload(payload)
        operation, data = payload["operation"], _canonical_stage_input(payload["stage_input"])
        created: list[str] = []
        if operation == "landscape.complete":
            if _current(state, "proposal"):
                _require(data["invalidate_current_proposal"] is True, "landscape replacement must invalidate current proposal")
            self._invalidate_downstream(state, claims=True)
            artifacts = []
            for item in data["landscape_artifacts"]:
                record = self._record(state, "landscape_artifact", {"cycle_id": state["cycle_id"], "artifact_type": "landscape", **dict(item)})
                artifacts.append(record["id"])
                artifacts = _canonical_ids(artifacts)
            _require(bool(artifacts), "landscape requires named artifacts")
            stage = self._stage(state, "L", data, artifact_ids=artifacts)
            state["current"]["landscape"] = stage["id"]
            created.extend(artifacts)
        elif operation == "hypothesis.complete":
            _require(_current(state, "landscape"), "landscape is required")
            if _current(state, "proposal"):
                _require(data["invalidate_current_proposal"] is True, "hypothesis replacement must invalidate current proposal")
            state["current"]["claims"] = []
            state["current"].pop("hypothesis", None)
            self._invalidate_downstream(state, proposal=True)
            claims = []
            try:
                HypothesisLifecycle().validate_h_stage_claims(data["claims"], state["records"])
            except HypothesisError as exc:
                raise GateUnsatisfied(str(exc)) from exc
            for item in data["claims"]:
                record = self._record(state, "claim", {"cycle_id": state["cycle_id"], "artifact_type": "claim", **dict(item)})
                claims.append(record["id"])
                claims = _canonical_ids(claims)
            _require(bool(claims), "hypothesis requires claims")
            stage = self._stage(state, "H", data, artifact_ids=claims)
            state["current"]["claims"] = claims
            state["current"]["hypothesis"] = stage["id"]
            self._rescope(state, Responsibility.NOVELTY_VALUE_JUDGMENT, "claims", claims)
        elif operation == "proposal.complete":
            claims = state["current"]["claims"]
            _require(claims and list(data["proposal"]["claim_ids"]) == claims, "proposal must bind current claims")
            self._invalidate_downstream(state, proposal=True)
            proposal = self._record(state, "proposal", {"cycle_id": state["cycle_id"], "artifact_type": "proposal", **dict(data["proposal"])})
            stage = self._stage(state, "P", data, artifact_ids=[proposal["id"]], proposal_id=proposal["id"], proposal_hash=proposal["content_hash"])
            state["current"]["proposal"] = proposal["id"]
            for responsibility in (Responsibility.SAFETY_ETHICS_REVIEW, Responsibility.EXECUTION_ACCOUNTABILITY):
                self._rescope(state, responsibility, "proposal", [proposal["id"]])
            created.append(proposal["id"])
        elif operation == "execution.not_run":
            proposal = state["records"].get(_current(state, "proposal"))
            _require(proposal and data["proposal_id"] == proposal["id"] and data["proposal_hash"] == proposal["content_hash"], "not-run must name current proposal")
            stage = self._stage(state, "X", data, proposal_id=proposal["id"], proposal_hash=proposal["content_hash"])
            state["current"].setdefault("local_x", {})[proposal["id"]] = stage["id"]
        elif operation == "analysis.complete":
            results = state["current"]["results"]
            _require(results and list(data["result_ids"]) == results, "analysis must bind current results")
            requirement_id = state["requirements"][Responsibility.EXCEPTION_INTERPRETATION.value]
            disposition_id = state["dispositions"].get(requirement_id)
            disposition = state["records"].get(disposition_id)
            _require(
                disposition and disposition["content"]["status"] == "satisfied"
                and disposition["content"].get("actor", {}).get("actor_kind") == "human",
                "human exception interpretation is required before analysis",
            )
            self._invalidate_downstream(state, analysis=True)
            artifacts = []
            for item in data["analysis_artifacts"]:
                _require(list(item.get("result_ids", [])) == results and set(item.get("claim_ids", [])) <= set(state["current"]["claims"]), "analysis artifact has foreign lineage")
                record = self._record(state, "analysis_artifact", {"cycle_id": state["cycle_id"], "artifact_type": "analysis", **dict(item)})
                artifacts.append(record["id"])
                artifacts = _canonical_ids(artifacts)
            _require(bool(artifacts), "analysis requires named artifacts")
            stage = self._stage(state, "A", data, artifact_ids=artifacts, result_ids=results)
            state["current"]["analysis"] = stage["id"]
            created.extend(artifacts)
        elif operation in {"write.interim", "write.final"}:
            _require(data["source_revision"] == state["revision"], "report must name exact current revision")
            self._validate_report_lineage(state, data, final=operation == "write.final")
            report = ScientificReportProjector().compose_from_state(state=state, source_revision=state["revision"],
                                                                      body_kind="final" if operation == "write.final" else "interim",
                                                                      limitations=tuple(data["limitations"]))
            body = self._record(state, "report_body", {"cycle_id": state["cycle_id"], "body_kind": "final" if operation == "write.final" else "interim",
                "format": "scientific-report-body.v1", "source_revision": state["revision"], "source_artifact_ids": list(data["source_artifact_ids"]),
                "claim_ids": list(data["claim_ids"]), "result_ids": list(data["result_ids"]), "analysis_artifact_ids": list(data["analysis_artifact_ids"]),
                "limitations": list(data["limitations"]), "body_blob_id": None, "body_hash": report.body_hash, "body_utf8": report.body_utf8.decode("utf-8")})
            stage = self._stage(state, "W", data, artifact_ids=[body["id"]], report_body_id=body["id"])
            created.append(body["id"])
            if operation == "write.interim":
                state["current"]["interim_report"] = stage["id"]
            if operation == "write.final":
                state["current"]["final_report"] = stage["id"]
                self._rescope(state, Responsibility.FINAL_ACCOUNTABILITY, "report_body", [body["id"], body["content"]["body_hash"]])
        elif operation == "cycle.complete":
            return self._complete(state, data)
        else:
            raise CycleError("unsupported continue operation")
        return Reduction(state, "cycle.continued", {"operation": operation, "created_records": [stage["id"], *created], "superseded_record_ids": [], "derived_current_refs": dict(state["current"])}, {"stage_id": stage["id"]})

    def _validate_report_lineage(self, state: Mapping[str, Any], data: Mapping[str, Any], *, final: bool) -> None:
        for field in ("source_artifact_ids", "claim_ids", "result_ids", "analysis_artifact_ids"):
            for record_id in data[field]: _require(record_id in state["records"], f"report has nonexistent {field}")
        _require(list(data["claim_ids"]) == state["current"]["claims"], "report must bind current claims")
        _require(list(data["result_ids"]) == state["current"]["results"], "report must bind current results")
        if final:
            _require(_current(state, "proposal") and _current(state, "analysis") and data["analysis_artifact_ids"], "final report requires current P and A")
            analysis = state["records"][_current(state, "analysis")]["content"]
            _require(set(data["analysis_artifact_ids"]) <= set(analysis["artifact_ids"]), "report analysis lineage is not current")

    def _assessment_context(self, state: Mapping[str, Any], source: Mapping[str, Any]) -> ApplicabilityContext:
        stage_id = _current(state, "analysis")
        stage = state["records"].get(stage_id)
        _require(stage and source["analysis_stage_id"] == stage_id, "assessment must name current analysis")
        _require(
            list(source["claim_ids"]) == state["current"]["claims"]
            and list(source["result_ids"]) == state["current"]["results"]
            and list(source["analysis_artifact_ids"]) == stage["content"]["artifact_ids"],
            "assessment lineage is not current",
        )
        return ApplicabilityContext(
            tuple(state["current"]["claims"]), tuple(state["current"]["results"]), stage_id,
            tuple(stage["content"]["artifact_ids"]), policy_from_source(source),
        )

    def _refresh_support(self, state: dict[str, Any]) -> None:
        stage_id = _current(state, "analysis")
        stage = state["records"].get(stage_id)
        if not stage:
            state["current"].pop("support", None)
            return
        current_claims = tuple(state["current"]["claims"])
        current_results = tuple(state["current"]["results"])
        current_artifacts = tuple(stage["content"]["artifact_ids"])
        assessments = []
        for assessment_id, record in state["assessments"].items():
            content = record["content"]
            if (tuple(content["claim_ids"]) == current_claims
                    and tuple(content["result_ids"]) == current_results
                    and content["analysis_stage_id"] == stage_id
                    and tuple(content["analysis_artifact_ids"]) == current_artifacts):
                assessments.append(assessment_from_source(content, assessment_id=assessment_id))
        support = aggregate_support(assessments)
        state["current"]["support"] = {
            "status": support.status.value,
            "supporting": support.supporting,
            "refuting": support.refuting,
            "inconclusive": support.inconclusive,
            "accepted_assessment_ids": list(support.accepted_assessment_ids),
        }

    def _require_completion_dispositions(self, state: Mapping[str, Any]) -> None:
        for responsibility in Responsibility:
            requirement_id = state["requirements"].get(responsibility.value)
            disposition_id = state["dispositions"].get(requirement_id)
            requirement = state["records"].get(requirement_id)
            disposition = state["records"].get(disposition_id)
            _require(requirement and disposition, f"{responsibility.value} disposition is missing or stale")
            content = disposition["content"]
            allowed_statuses = {"satisfied"}
            if responsibility is Responsibility.EXCEPTION_INTERPRETATION:
                allowed_statuses.add("not_applicable")
            _require(
                content.get("requirement_id") == requirement_id
                and content.get("responsibility") == responsibility.value
                and content.get("scope_hash") == requirement["content"].get("scope_hash")
                and content.get("actor", {}).get("actor_kind") == "human"
                and content.get("status") in allowed_statuses,
                f"{responsibility.value} disposition is not current",
            )
            details = content.get("details", {})
            if responsibility is Responsibility.QUESTION_SELECTION:
                _require(
                    details.get("selected_normalized_question") == state["question"],
                    "question-selection disposition is not current",
                )
            if responsibility is Responsibility.EXCEPTION_INTERPRETATION and content.get("status") == "not_applicable":
                _require(
                    details.get("no_exception_assertion") is True and not details.get("deviations"),
                    "exception-interpretation not_applicable disposition is invalid",
                )
    def _disposition(self, state: dict[str, Any], name: str, payload: Mapping[str, Any]) -> Reduction:
        responsibility = name.split(".")[1]
        validate_disposition_payload(responsibility, payload)
        requirement_id = state["requirements"].get(responsibility)
        _require(requirement_id == payload["requirement_id"] and requirement_id not in state["dispositions"], "disposition is stale")
        requirement = state["records"][requirement_id]["content"]
        try:
            content = SignoffCore.validate_disposition_input(requirement={"id": requirement_id, **requirement}, existing_disposition=None,
                responsibility=responsibility, payload=payload)
        except ValueError as exc:
            raise GateUnsatisfied(str(exc)) from exc
        self._validate_disposition_scope(state, responsibility, content["details"])
        record = self._record(state, "responsibility_disposition", content | {"responsibility": responsibility})
        state["dispositions"][requirement_id] = record["id"]
        return Reduction(state, "responsibility.disposition.recorded", {"responsibility": responsibility, "requirement_id": requirement_id, "disposition_id": record["id"], "created_records": [record["id"]], "derived_current_refs": dict(state["current"])}, {"disposition_id": record["id"]})

    def _validate_disposition_scope(self, state: Mapping[str, Any], responsibility: str, details: Mapping[str, Any]) -> None:
        proposal_id = _current(state, "proposal")
        if responsibility in {Responsibility.SAFETY_ETHICS_REVIEW.value, Responsibility.EXECUTION_ACCOUNTABILITY.value}:
            proposal = state["records"].get(proposal_id)
            _require(proposal and details.get("proposal_id") == proposal_id and details.get("proposal_hash") == proposal["content_hash"], "disposition proposal is not current")
        if responsibility == Responsibility.QUESTION_SELECTION.value:
            _require(
                details.get("selected_normalized_question") == state["question"],
                "disposition question is not current",
            )
        elif responsibility == Responsibility.EXCEPTION_INTERPRETATION.value:
            _require(list(details.get("result_ids", [])) == state["current"]["results"], "disposition results are not current")
            hashes = [state["records"][record_id]["content_hash"] for record_id in state["current"]["results"]]
            _require(list(details.get("result_hashes", [])) == hashes, "disposition result hashes are not current")
        elif responsibility == Responsibility.NOVELTY_VALUE_JUDGMENT.value:
            _require(list(details.get("claim_ids", [])) == state["current"]["claims"], "disposition claims are not current")

    def _export(self, state: dict[str, Any], payload: Mapping[str, Any]) -> Reduction:
        validate_export_payload(payload)
        self._check_export_gates(state)
        return Reduction(
            state,
            "export.created",
            {"created_records": [], "superseded_record_ids": [], "derived_current_refs": dict(state["current"])},
            {},
        )

    def export_ready(self, state: Mapping[str, Any]) -> bool:
        """Server-derived export gate status for client display; never a mutation gate."""
        if state.get("terminal"):
            return False
        try:
            self._check_export_gates(state)
        except GateUnsatisfied:
            return False
        return True

    def _check_export_gates(self, state: Mapping[str, Any]) -> None:
        for current_ref, label in (
            ("landscape", "landscape"),
            ("hypothesis", "hypothesis"),
            ("proposal", "proposal"),
        ):
            _require(_current(state, current_ref), f"current {label} is required")
        proposal = state["records"].get(_current(state, "proposal"))
        _require(proposal is not None, "current proposal is required")
        local_x_id = state.get("current", {}).get("local_x", {}).get(proposal["id"])
        local_x = state["records"].get(local_x_id)
        _require(
            local_x and local_x["content"].get("stage") == "X"
            and local_x["content"].get("status") == "not_run"
            and local_x["content"].get("execution_kind") == "not_run",
            "current proposal requires local X=not_run",
        )
        for responsibility in (
            Responsibility.QUESTION_SELECTION,
            Responsibility.SAFETY_ETHICS_REVIEW,
            Responsibility.EXECUTION_ACCOUNTABILITY,
        ):
            requirement_id = state["requirements"].get(responsibility.value)
            disposition_id = state["dispositions"].get(requirement_id)
            requirement = state["records"].get(requirement_id)
            disposition = state["records"].get(disposition_id)
            content = disposition.get("content") if isinstance(disposition, Mapping) else None
            _require(
                requirement and isinstance(content, Mapping)
                and content.get("requirement_id") == requirement_id
                and content.get("responsibility") == responsibility.value
                and content.get("scope_hash") == requirement["content"].get("scope_hash")
                and content.get("status") == "satisfied"
                and content.get("actor", {}).get("actor_kind") == "human",
                f"{responsibility.value} disposition is not current",
            )
            details = content.get("details")
            _require(isinstance(details, Mapping), f"{responsibility.value} disposition details are invalid")
            if responsibility is Responsibility.QUESTION_SELECTION:
                _require(
                    details.get("selected_normalized_question") == state["question"],
                    "question-selection disposition is not current",
                )
            elif responsibility is Responsibility.SAFETY_ETHICS_REVIEW:
                _require(
                    details.get("proposal_id") == proposal["id"]
                    and details.get("proposal_hash") == proposal["content_hash"]
                    and details.get("export_only_boundary_confirmed") is True,
                    "safety_ethics_review disposition is not current",
                )
            else:
                _require(
                    details.get("proposal_id") == proposal["id"]
                    and details.get("proposal_hash") == proposal["content_hash"],
                    "execution_accountability disposition is not current",
                )
                actor_assertion_from_mapping(details.get("handoff_owner"))
                boundary = stage_boundary_from_mapping(details.get("execution_boundary"))
                _require(boundary["kind"] == "export_only", "execution_accountability disposition is not export_only")

    def apply_verified_result(self, state: Mapping[str, Any], result: Mapping[str, Any]) -> Reduction:
        """Record a repository-verified import; this is deliberately not wire-dispatchable."""
        state = deepcopy(dict(state))
        if state.get("terminal"):
            raise GateUnsatisfied("cycle is terminal")
        result = _materialize(result)
        content = result.get("content")
        if (result.get("record_type") != "result"
                or not isinstance(result.get("id"), str)
                or not isinstance(content, Mapping)
                or content.get("proposal_id") != _current(state, "proposal")):
            raise GateUnsatisfied("verified result does not bind the current proposal")
        proposal = state["records"].get(content["proposal_id"])
        _require(
            proposal and content.get("proposal_hash") == proposal["content_hash"],
            "verified result proposal is not current",
        )
        supersedes_result_id = content.get("supersedes_result_id")
        current_results = list(state["current"]["results"])
        if supersedes_result_id is not None:
            _require(supersedes_result_id in current_results, "verified correction supersedes a noncurrent result")
            current_results.remove(supersedes_result_id)
        _require(result["id"] not in state["records"], "verified result already exists")
        state["records"][result["id"]] = result
        current_results.append(result["id"])
        current_results = _canonical_ids(current_results)
        self._invalidate_downstream(state, analysis=True)
        state["current"]["results"] = current_results
        self._rescope(state, Responsibility.EXCEPTION_INTERPRETATION, "results", current_results)
        return Reduction(
            state,
            "result.recorded",
            {
                "result_id": result["id"],
                "result_hash": result["content_hash"],
                "artifact_refs": list(content["artifact_refs"]),
                "supersedes_result_id": supersedes_result_id,
                "proposal_id": content["proposal_id"],
                "proposal_hash": content["proposal_hash"],
                "execution_kind": content["execution_kind"],
                "accountable_party": content["accountable_party"],
                "performers": list(content["performers"]),
                "started_at": content["started_at"],
                "completed_at": content["completed_at"],
                "external_references": list(content["external_references"]),
                "staged_blob_ids": list(content["staged_blob_ids"]),
                "result_manifest": content["result_manifest"],
                "deviations": list(content["deviations"]),
                "created_records": [result["id"]],
                "superseded_record_ids": [supersedes_result_id] if supersedes_result_id else [],
                "derived_current_refs": dict(state["current"]),
            },
            {"result_id": result["id"], "result_hash": result["content_hash"]},
        )

    def _result(self, state: dict[str, Any], payload: Mapping[str, Any]) -> Reduction:
        raise GateUnsatisfied("result.submit requires a repository-owned verified import")

    def _adjudicate(self, state: dict[str, Any], payload: Mapping[str, Any]) -> Reduction:
        validate_adjudication_payload(payload)
        source = dict(payload.get("assessment") or payload)
        if payload["mode"] == "create":
            context = self._assessment_context(state, source)
            adjudicate_current(source=source, context=context)
            record = self._record(state, "validation_assessment", source)
            state["assessments"][record["id"]] = record
            self._refresh_support(state)
            return Reduction(state, "validation.assessment.recorded", {"assessment_id": record["id"], **source, "created_records": [record["id"]], "derived_current_refs": dict(state["current"])}, {"assessment_id": record["id"]})
        previous = state["assessments"].get(payload["assessment_id"])
        _require(previous is not None, "assessment not found")
        _require(previous["content"]["assessment_state"] == source["from_state"], "assessment transition source state changed")
        for field in ("claim_ids", "result_ids", "analysis_stage_id", "analysis_artifact_ids", "validation_policy_id", "validation_policy_version", "validation_policy_reference"):
            _require(canonical_json(previous["content"].get(field)) == canonical_json(source.get(field)),
                     f"assessment {field} bytes changed")
        updated_content = dict(previous["content"]) | {"assessment_state": source["to_state"]}
        context = self._assessment_context(state, updated_content)
        adjudicate_current(
            source=updated_content,
            context=context,
            prior_state=source["from_state"],
        )
        transition = self._record(state, "assessment_transition", {"assessment_id": payload["assessment_id"], **source})
        updated = self._record(state, "validation_assessment", updated_content)
        state["assessments"][payload["assessment_id"]] = updated
        self._refresh_support(state)
        return Reduction(state, "validation.assessment.transitioned", {"assessment_id": payload["assessment_id"], "transition_id": transition["id"], "created_records": [transition["id"], updated["id"]], "derived_current_refs": dict(state["current"])}, {"assessment_id": payload["assessment_id"]})

    def _supersede(self, state: dict[str, Any], payload: Mapping[str, Any]) -> Reduction:
        validate_supersede_payload(payload)
        responsibility = Responsibility(payload["responsibility"])
        requirement_id = state["requirements"].get(responsibility.value)
        _require(requirement_id == payload["requirement_id"], "requirement is not current")
        disposition_id = state["dispositions"].get(requirement_id)
        _require(disposition_id == payload["superseded_disposition_id"], "disposition is not current")
        requirement = state["records"][requirement_id]["content"]
        replacement_requirement_id = self._rescope(
            state, responsibility, requirement["scope_kind"], list(requirement["scope_ids"])
        )
        replacement_disposition_id = None
        replacement = payload["replacement_disposition"]
        if replacement is not None:
            replacement_requirement = state["records"][replacement_requirement_id]["content"]
            try:
                content = SignoffCore.validate_disposition_input(
                    requirement={"id": replacement_requirement_id, **replacement_requirement},
                    existing_disposition=None,
                    responsibility=responsibility.value,
                    payload=replacement,
                )
            except ValueError as exc:
                raise GateUnsatisfied(str(exc)) from exc
            self._validate_disposition_scope(state, responsibility.value, content["details"])
            record = self._record(
                state, "responsibility_disposition",
                content | {"responsibility": responsibility.value},
            )
            replacement_disposition_id = record["id"]
            state["dispositions"][replacement_requirement_id] = replacement_disposition_id
        created_records = [replacement_requirement_id]
        if replacement_disposition_id is not None:
            created_records.append(replacement_disposition_id)
        return Reduction(
            state,
            "responsibility.disposition.superseded",
            {
                "responsibility": responsibility.value,
                "old_requirement_id": requirement_id,
                "new_requirement_id": replacement_requirement_id,
                "superseded_disposition_id": disposition_id,
                "replacement_disposition_id": replacement_disposition_id,
                "created_records": created_records,
                "superseded_record_ids": [requirement_id, disposition_id],
                "derived_current_refs": dict(state["current"]),
            },
            {
                "requirement_id": replacement_requirement_id,
                "disposition_id": replacement_disposition_id,
            },
        )

    def _abort(self, state: dict[str, Any], payload: Mapping[str, Any]) -> Reduction:
        actor = actor_assertion_from_mapping(payload["actor"])
        reason = payload.get("reason")
        observation = payload.get("final_observation")
        _require(isinstance(reason, str) and bool(reason), "abort reason is required")
        _require(isinstance(observation, str), "abort final observation is required")
        state["terminal"] = "aborted"
        return Reduction(
            state,
            "cycle.aborted",
            {
                "actor": actor,
                "reason": reason,
                "final_observation": observation,
                "created_records": [],
                "superseded_record_ids": [],
                "derived_current_refs": dict(state["current"]),
            },
            {"status": "aborted"},
        )
    def _reject_proposal(self, state: dict[str, Any], payload: Mapping[str, Any]) -> Reduction:
        proposal = state["records"].get(_current(state, "proposal"))
        _require(proposal and payload.get("proposal_id") == proposal["id"] and payload.get("proposal_hash") == proposal["content_hash"], "proposal is not current")
        actor = actor_assertion_from_mapping(payload["actor"])
        _require(isinstance(payload.get("recoverable"), bool) and isinstance(payload.get("reason"), str) and payload["reason"], "proposal rejection reason is required")
        rejection = self._record(state, "proposal_rejection", {
            "proposal_id": proposal["id"], "proposal_hash": proposal["content_hash"],
            "actor": actor, "reason": payload["reason"], "recoverable": payload["recoverable"],
        })
        self._invalidate_downstream(state, proposal=True)
        return Reduction(
            state,
            "proposal.rejected",
            {
                "proposal_id": proposal["id"],
                "proposal_hash": proposal["content_hash"],
                "rejection_record_id": rejection["id"],
                "recoverable": payload["recoverable"],
                "created_records": [rejection["id"]],
                "superseded_record_ids": [proposal["id"]],
                "derived_current_refs": dict(state["current"]),
            },
            {"rejected": proposal["id"], "rejection_id": rejection["id"]},
        )

    def _complete(self, state: dict[str, Any], data: Mapping[str, Any]) -> Reduction:
        stage = state["records"].get(_current(state, "final_report"))
        _require(stage and data["report_stage_id"] == stage["id"], "current final report is required")
        body = state["records"].get(data["report_body_id"])
        _require(body and stage["content"]["report_body_id"] == body["id"] and body["content"]["body_hash"] == data["report_body_hash"], "completion report bytes are not current")
        self._require_completion_dispositions(state)
        requirement_id = state["requirements"][Responsibility.FINAL_ACCOUNTABILITY.value]
        disposition_id = state["dispositions"].get(requirement_id)
        _require(data["final_accountability_requirement_id"] == requirement_id and data["final_accountability_disposition_id"] == disposition_id, "completion final disposition is stale")
        disposition = state["records"].get(disposition_id)
        details = disposition.get("content", {}).get("details") if isinstance(disposition, Mapping) else None
        _require(
            disposition and disposition["content"]["status"] == "satisfied"
            and isinstance(details, Mapping)
            and details.get("report_body_id") == body["id"]
            and details.get("report_body_hash") == body["content"]["body_hash"]
            and details.get("reviewed_exact_bytes") is True
            and details.get("limitations_acknowledged") is True,
            "final accountability is not current",
        )
        state["terminal"] = "completed"
        return Reduction(state, "cycle.completed", {"report_body_id": body["id"], "report_body_hash": data["report_body_hash"], "final_accountability_disposition_id": disposition_id, "created_records": [], "superseded_record_ids": [], "derived_current_refs": dict(state["current"])}, {"status": "completed"})
