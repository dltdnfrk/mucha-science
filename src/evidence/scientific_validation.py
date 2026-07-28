"""Pure scientific-validation policy and support aggregation.

Validation levels describe the modality of an assessment only.  They never
upgrade confidence, quality, applicability, outcome, or claim support.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping

from src.pipeline.scientific_contracts import (
    AssessmentState,
    AuthorityKind,
    ExternalReference,
    EvidenceStance,
    Outcome,
    ValidationLevel,
    actor_assertion_from_mapping,
    canonical_id_array,
)
from src.pipeline.scientific_contracts import (
    AssertionSource, AuthorityScope, ContractError,
    VerificationStatus,
)




class ValidationError(ValueError):
    """Raised when an assessment cannot be evaluated against its declared links."""


class SupportStatus(StrEnum):
    UNASSESSED = "unassessed"
    SUPPORTING = "supporting"
    REFUTING = "refuting"
    MIXED = "mixed"
    INCONCLUSIVE = "inconclusive"
    DISPUTED = "disputed"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"


def stance_from_lifecycle(status: SupportStatus) -> EvidenceStance:
    """Project lifecycle state to claim stance without discarding lifecycle detail."""
    if not isinstance(status, SupportStatus):
        raise ValidationError("support lifecycle status must use SupportStatus")
    return {
        SupportStatus.SUPPORTING: EvidenceStance.SUPPORTS_CLAIM,
        SupportStatus.REFUTING: EvidenceStance.REFUTES_CLAIM,
        SupportStatus.MIXED: EvidenceStance.MIXED,
    }.get(status, EvidenceStance.INCONCLUSIVE)


class PolicyDisposition(StrEnum):
    ACCEPTABLE = "acceptable"
    PENDING = "pending"
    EXPORT_ONLY = "export_only"


@dataclass(frozen=True)
class Qualification:
    kind: str
    asserted_unverified: bool = False


@dataclass(frozen=True)
class ValidationPolicy:
    policy_id: str
    version: str
    reference: ExternalReference | None
    consequential: bool = False

    @property
    def is_general(self) -> bool:
        return self.policy_id == "muchanipo.validation.general" and self.version == "1.0.0"

    def __post_init__(self) -> None:
        if self.is_general and self.reference is not None:
            raise ValidationError("the built-in general policy has no external reference")
        if self.consequential and self.reference is None:
            raise ValidationError("consequential policy requires an external reference")
        if not self.is_general and not self.consequential:
            raise ValidationError("only the built-in policy or declared external consequential policy is supported")


@dataclass(frozen=True)
class AssessmentLinks:
    claim_ids: tuple[str, ...]
    result_ids: tuple[str, ...]
    analysis_stage_id: str
    analysis_artifact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        canonical_id_array(self.claim_ids, nonempty=True)
        canonical_id_array(self.result_ids, nonempty=True)
        canonical_id_array(self.analysis_artifact_ids, nonempty=True)
        if not self.analysis_stage_id:
            raise ValidationError("analysis_stage_id is required")


@dataclass(frozen=True)
class Assessment:
    assessment_id: str
    links: AssessmentLinks
    state: str
    outcome: Outcome
    validation_level: ValidationLevel
    evidence_quality: str
    model_confidence: str | None
    applicability: str
    policy: ValidationPolicy
    qualifications: tuple[Qualification, ...] = ()
    methods_and_statistics: bool = False
    independent: bool = False
    assessor_asserted_unverified: bool = False
    current: bool = True


@dataclass(frozen=True)
class ApplicabilityContext:
    claim_ids: tuple[str, ...]
    result_ids: tuple[str, ...]
    analysis_stage_id: str
    analysis_artifact_ids: tuple[str, ...]
    policy: ValidationPolicy
    claims_current: bool = True
    results_current: bool = True
    analysis_current: bool = True


@dataclass(frozen=True)
class PolicyDecision:
    disposition: PolicyDisposition
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SupportAggregation:
    status: SupportStatus
    supporting: int
    refuting: int
    inconclusive: int
    accepted_assessment_ids: tuple[str, ...]


def _quality_rank(value: str) -> int:
    ranks = {"unknown": 0, "low": 1, "moderate": 2, "high": 3}
    try:
        return ranks[value]
    except KeyError as exc:
        raise ValidationError("unknown evidence quality") from exc


def validate_applicability(assessment: Assessment, context: ApplicabilityContext) -> None:
    """Require exact current claim/result/A links and an unchanged policy tuple."""
    if assessment.links.claim_ids != context.claim_ids:
        raise ValidationError("assessment claim links do not apply to the current claim set")
    if assessment.links.result_ids != context.result_ids:
        raise ValidationError("assessment result links do not apply to the current result set")
    if assessment.links.analysis_stage_id != context.analysis_stage_id:
        raise ValidationError("assessment analysis stage does not apply")
    if assessment.links.analysis_artifact_ids != context.analysis_artifact_ids:
        raise ValidationError("assessment analysis artifacts do not apply")
    if not (context.claims_current and context.results_current and context.analysis_current):
        raise ValidationError("assessment links are no longer current")
    if assessment.policy != context.policy:
        raise ValidationError("assessment policy tuple does not apply")


def policy_decision(assessment: Assessment, context: ApplicabilityContext) -> PolicyDecision:
    """Evaluate policy gates without changing the assessment's V-level or outcome."""
    validate_applicability(assessment, context)
    if assessment.applicability != "applicable":
        return PolicyDecision(PolicyDisposition.PENDING, ("assessment is not applicable",))
    if not assessment.assessor_asserted_unverified:
        return PolicyDecision(PolicyDisposition.PENDING, ("assessor assurance must be explicitly asserted/unverified",))
    if not all(item.asserted_unverified for item in assessment.qualifications):
        return PolicyDecision(PolicyDisposition.PENDING, ("qualifications must be explicitly asserted/unverified",))

    policy = context.policy
    if policy.consequential:
        reference = policy.reference
        has_authority = bool(reference and reference.authority_scope.kind is AuthorityKind.EXTERNALLY_ASSERTED)
        has_qualified_human = bool(assessment.qualifications)
        if not (reference and has_authority and has_qualified_human):
            return PolicyDecision(PolicyDisposition.EXPORT_ONLY, ("consequential policy remains pending without asserted qualified humans and external authority",))
        return PolicyDecision(PolicyDisposition.PENDING, ("external consequential policy is asserted/unverified and not interpreted by software",))
    qualification_kinds = {item.kind for item in assessment.qualifications}

    if assessment.validation_level is ValidationLevel.V0:
        return PolicyDecision(PolicyDisposition.PENDING, ("V0 is unassessed and cannot be accepted",))
    if assessment.validation_level is ValidationLevel.V1:
        sufficient = bool({"subject_matter", "benchmark"} & qualification_kinds) and _quality_rank(assessment.evidence_quality) >= 1
        return PolicyDecision(PolicyDisposition.ACCEPTABLE if sufficient else PolicyDisposition.PENDING,
                              () if sufficient else ("V1 requires asserted subject-matter or benchmark qualification and low quality",))
    if assessment.validation_level is ValidationLevel.V2:
        sufficient = (assessment.methods_and_statistics and assessment.independent
                      and _quality_rank(assessment.evidence_quality) >= 2)
        return PolicyDecision(PolicyDisposition.ACCEPTABLE if sufficient else PolicyDisposition.PENDING,
                              () if sufficient else ("V2 requires methods, statistics, independence, and moderate quality",))
    if assessment.validation_level is ValidationLevel.V3:
        return PolicyDecision(PolicyDisposition.PENDING, ("general policy does not accept V3",))
    raise ValidationError("unknown validation level")


def aggregate_support(assessments: Iterable[Assessment]) -> SupportAggregation:
    """Aggregate only current accepted assessments; confidence and V-level never tie-break."""
    current_items = tuple(item for item in assessments if item.current)
    accepted = tuple(item for item in current_items if item.state == AssessmentState.ACCEPTED.value)
    supporting = sum(item.outcome is Outcome.SUPPORTS for item in accepted)
    refuting = sum(item.outcome is Outcome.REFUTES for item in accepted)
    inconclusive = sum(item.outcome is Outcome.INCONCLUSIVE for item in accepted)
    if supporting and refuting:
        status = SupportStatus.MIXED
    elif supporting:
        status = SupportStatus.SUPPORTING
    elif refuting:
        status = SupportStatus.REFUTING
    elif inconclusive:
        status = SupportStatus.INCONCLUSIVE
    elif any(item.state == "disputed" for item in current_items):
        status = SupportStatus.DISPUTED
    elif any(item.state == "withdrawn" for item in current_items):
        status = SupportStatus.WITHDRAWN
    elif any(item.state == "superseded" for item in current_items):
        status = SupportStatus.SUPERSEDED
    else:
        status = SupportStatus.UNASSESSED
    return SupportAggregation(status, supporting, refuting, inconclusive,
                              tuple(sorted(item.assessment_id for item in accepted)))


def policy_from_source(source: Mapping[str, object]) -> ValidationPolicy:
    """Parse a serialized policy tuple into the sole validation-policy value."""
    policy_id, version = source.get("validation_policy_id"), source.get("validation_policy_version")
    reference = source.get("validation_policy_reference")
    try:
        parsed_reference = None if reference is None else ExternalReference(
            reference_type=reference["reference_type"], issuer=reference["issuer"], title=reference["title"],
            uri_or_identifier=reference["uri_or_identifier"], content_hash=reference["content_hash"],
            assertion_source=AssertionSource(reference["assertion_source"]),
            verification_status=VerificationStatus(reference["verification_status"]),
            authority_scope=AuthorityScope(AuthorityKind(reference["authority_scope"]["kind"]), reference["authority_scope"]["scope"]),
        )
        return ValidationPolicy(str(policy_id), str(version), parsed_reference,
                                consequential=str(policy_id).startswith("external:"))
    except (KeyError, TypeError, ValueError, ContractError) as exc:
        raise ValidationError("invalid adjudication policy input") from exc


def assessment_from_source(source: Mapping[str, object], *, assessment_id: str | None = None) -> Assessment:
    """Deserialize the frozen assessment fields used by policy and support."""
    try:
        policy = policy_from_source(source)
        assessor = actor_assertion_from_mapping(source["assessor"])
        qualifications = tuple(
            Qualification(str(item["kind"]), item["asserted_unverified"] is True)
            for item in source["qualifications"]
        )
        return Assessment(
            assessment_id=assessment_id or str(source.get("assessment_id", "pending")),
            links=AssessmentLinks(tuple(source["claim_ids"]), tuple(source["result_ids"]),
                                  str(source["analysis_stage_id"]), tuple(source["analysis_artifact_ids"])),
            state=str(source["assessment_state"]), outcome=Outcome(source["result_outcome"]),
            validation_level=ValidationLevel(source["validation_level"]),
            evidence_quality=str(source["evidence_quality"]),
            model_confidence=source.get("model_confidence"), applicability=str(source["applicability"]),
            policy=policy, qualifications=qualifications,
            methods_and_statistics=source.get("methods_and_statistics") is True,
            independent=source.get("independent") is True,
            assessor_asserted_unverified=assessor["verification_status"] in {
                "operator_asserted_unverified",
                "external_reference_unverified",
            },
        )
    except (KeyError, TypeError, ValueError, ContractError) as exc:
        raise ValidationError("invalid adjudication policy input") from exc


def adjudicate_current(*, source: Mapping[str, object], context: ApplicabilityContext,
                       prior_state: str | None = None) -> PolicyDecision:
    """Validate an immutable adjudication against current reducer links and policy."""
    allowed_edges = {
        None: {AssessmentState.PENDING.value},
        AssessmentState.PENDING.value: {AssessmentState.ACCEPTED.value, AssessmentState.REJECTED.value, AssessmentState.DISPUTED.value},
        AssessmentState.DISPUTED.value: {AssessmentState.ACCEPTED.value, AssessmentState.REJECTED.value},
    }
    state = source.get("assessment_state")
    if state not in allowed_edges.get(prior_state, set()):
        raise ValidationError("illegal assessment state transition")
    assessment = assessment_from_source(source)
    decision = policy_decision(assessment, context)
    if state == AssessmentState.ACCEPTED.value and decision.disposition is not PolicyDisposition.ACCEPTABLE:
        raise ValidationError("assessment cannot be accepted under the current policy")
    return decision
