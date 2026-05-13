"""Pipeline package: Idea-to-Council orchestration modules (stages/state/runner,
imported directly as src.pipeline.<module>) plus the public AI-scientist contracts
re-exported at the package root."""
from .scientific_contracts import (
    ACTIONS, ADJUDICATION_MODES, CONTINUE_OPERATIONS, ERRORS, EVENTS,
    ActorAssertion, ActorKind, AssertionSource, AssessmentState, AuthorityKind,
    AuthorityScope, ContractError, EvidenceQuality, ExceptionInterpretationDisposition,
    ExecutionAccountabilityDisposition, ExternalReference, FinalAccountabilityDisposition,
    GENESIS_HASH, IDENTITY_SCHEMA, NoveltyValueJudgmentDisposition, Outcome, Performer,
    PROTOCOL, PROTOCOL_VERSION, ProtocolEnvelope, QuestionSelectionDisposition,
    Responsibility, ResponsibilityDisposition, ResponsibilityRequirement,
    SafetyEthicsReviewDisposition, Stage, StageBoundary, StageRecord, Support,
    ValidationDimensions, ValidationLevel, VerificationStatus, byte_digest,
    canonical_id_array, canonical_json, command_digest, content_record,
    decode_json_object, deterministic_id, digest, event_frame_hash, normalize_question,
    validate_adjudication_payload, validate_continue_payload, validate_policy_tuple,
)

from .goals_artifacts import (
    GOALS_HERMES_SCORING_FIELDS,
    GOALS_STAGE_ARTIFACT_FIELDS,
    GOALS_STAGE_STATUSES,
    build_goals_stage_artifact,
    default_hermes_scoring,
    goals_stage_artifact_contract_report,
    normalize_stage_artifact,
    stage_status_for_event,
)
from .goals_stages import (
    CANONICAL_GOALS_STAGES,
    GOALS_STAGE_LEGACY_STAGE_MAP,
    INTERNAL_SUBSTEP_TO_CANONICAL_STAGE_MAP,
    LEGACY_TO_CANONICAL_STAGE_MAP,
    PUBLIC_GOALS_STAGES,
    PUBLIC_GOALS_STAGE_IDS,
    GoalsStageContract,
    canonical_stage_ids,
    goals_stage_by_id,
    goals_stage_contract_report,
    legacy_stages_for_public_stage,
    normalize_public_stage,
    public_goals_stage_ids,
    public_stage_for_internal_substep,
    public_stage_for_legacy,
)

__all__ = [name for name in globals() if not name.startswith("_")]
