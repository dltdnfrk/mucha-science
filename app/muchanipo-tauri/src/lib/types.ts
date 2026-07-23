export type LayerName =
  | "intent"
  | "research"
  | "evidence"
  | "council"
  | "synthesis"
  | "critique"
  | "refine"
  | "verify"
  | "report"
  | "publish";

export type BackendEventKind =
  | "pipeline_started"
  | "run_started"
  | "stage_started"
  | "stage_progress"
  | "stage_blocked"
  | "stage_completed"
  | "stage_failed"
  | "deep_interview_progress"
  | "deep_interview_artifacts"
  | "interview_ontology_delta"
  | "interview_question"
  | "research_progress"
  | "council_round_start"
  | "council_token"
  | "council_turn"
  | "council_persona_token"
  | "council_round_end"
  | "council_round_done"
  | "report_chunk"
  | "final_report"
  | "pipeline_error"
  | "error"
  | "pipeline_done"
  | "done";

interface BackendEventEnvelope {
  event?: BackendEventKind | string;
  type?: BackendEventKind | string;
  [key: string]: unknown;
}

export interface PipelineStartedEvent extends BackendEventEnvelope {
  type: "pipeline_started";
  event?: "pipeline_started" | "run_started";
  topic: string;
  session_id: string;
  ts: string;
}

export interface InterviewQuestionEvent extends BackendEventEnvelope {
  type: "interview_question";
  event?: "interview_question";
  question_id: string;
  prompt: string;
  options: { key: string; label: string }[];
  allow_other: boolean;
}

export interface InterviewOntologyDeltaEvent extends BackendEventEnvelope {
  type: "interview_ontology_delta";
  event?: "interview_ontology_delta";
  q_id?: string;
  question_id?: string;
  ontology_state?: Record<string, unknown>;
  ontology_delta?: Record<string, unknown>;
  entities?: Record<string, unknown>[];
  relations?: Record<string, unknown>[];
  unknowns?: Record<string, unknown>[];
  targets_unknown_ids?: string[];
  question_quality_gate?: Record<string, unknown>;
  coverage?: number;
  open_unknown_count?: number;
}

export interface CouncilRoundStartEvent extends BackendEventEnvelope {
  type: "council_round_start";
  event?: "council_round_start";
  round: number;
  layer: LayerName;
  personas: string[];
}

export interface CouncilTokenEvent extends BackendEventEnvelope {
  type: "council_token";
  event?: "council_token" | "council_turn" | "council_persona_token";
  round: number;
  persona: string;
  delta: string;
}

export interface CouncilRoundEndEvent extends BackendEventEnvelope {
  type: "council_round_end";
  event?: "council_round_end" | "council_round_done";
  round: number;
  layer: LayerName;
  summary: string;
}

export interface ReportChunkEvent extends BackendEventEnvelope {
  type: "report_chunk";
  event?: "report_chunk";
  delta: string;
  done: boolean;
}

export interface ResearchProgressEvent extends BackendEventEnvelope {
  type: "research_progress";
  event?: "research_progress";
  status: string;
  query?: string;
  query_index?: number;
  query_count?: number;
  backends?: string[];
  source_title?: string;
  source_url?: string;
  source_grade?: string;
  source_kind?: string;
  access_status?: string;
  accepted?: boolean;
  facet_ids?: string[];
  relevance_score?: number;
  reason?: string;
  facet_id?: string;
  message?: string;
  accepted_count?: number;
  min_accepted_sources?: number;
  gap_count?: number;
}

export interface StageLifecycleEvent extends BackendEventEnvelope {
  type?: "stage_started" | "stage_progress" | "stage_blocked" | "stage_completed" | "stage_failed";
  event: "stage_started" | "stage_progress" | "stage_blocked" | "stage_completed" | "stage_failed";
  stage: string;
  status?: string;
  message?: string;
  artifact_ref?: string;
  blockers?: unknown[];
  final_report_ready?: boolean | string | number;
  llm_council_ready?: boolean | string | number;
  blocks_product_pass?: boolean | string | number;
}

export interface PipelineErrorEvent extends BackendEventEnvelope {
  type: "pipeline_error";
  event?: "pipeline_error" | "error";
  message: string;
  fatal: boolean;
}

export interface PipelineDoneEvent extends BackendEventEnvelope {
  type: "pipeline_done";
  event?: "pipeline_done" | "done";
  report_path: string;
}

export type BackendEvent =
  | PipelineStartedEvent
  | InterviewOntologyDeltaEvent
  | InterviewQuestionEvent
  | StageLifecycleEvent
  | ResearchProgressEvent
  | CouncilRoundStartEvent
  | CouncilTokenEvent
  | CouncilRoundEndEvent
  | ReportChunkEvent
  | PipelineErrorEvent
  | PipelineDoneEvent;

export interface UserAction {
  type: "interview_answer" | "cancel" | "resume";
  question_id?: string;
  selected?: string;
  other_text?: string;
}

export function backendEventName(event: BackendEvent): string {
  return String(event.event ?? event.type ?? "");
}
export const AI_SCIENTIST_PROTOCOL = "ai-scientist.v1" as const;

export type AccountabilityLabel = "asserted" | "unverified";
export type ValidationStatus = "pending" | "passed" | "failed" | "not_applicable";

export interface ValidationDimensions {
  empirical: ValidationStatus;
  methodological: ValidationStatus;
  reproducibility: ValidationStatus;
  ethical: ValidationStatus;
}

export interface Accountability {
  label: AccountabilityLabel;
  asserted_by?: string;
  assertion?: string;
}

export interface ScientificEnvelope<TType extends string, TPayload> {
  protocol: typeof AI_SCIENTIST_PROTOCOL;
  message_id: string;
  session_id: string;
  sequence: number;
  revision: number;
  type: TType;
  payload: TPayload;
}

export interface ScientificProtocolEnvelope {
  protocol: "muchanipo";
  protocol_version: typeof AI_SCIENTIST_PROTOCOL;
  kind: "action" | "event" | "response" | "error" | "snapshot" | "diagnostic";
  name: string;
  message_id: string;
  cycle_id: string | null;
  correlation_id: string | null;
  causation_id: string | null;
  sequence: number;
  revision: number;
  idempotency_key: string | null;
  timestamp: string;
  payload: Record<string, unknown>;
  extensions: Record<string, unknown>;
}

export interface ScientificCursor {
  cycle_id: string;
  sequence: number;
  event_hash: string;
}

export interface HelloPayload {
  handshake_idempotency_key: string;
  client_instance_id: string;
  supported_versions: [typeof AI_SCIENTIST_PROTOCOL];
  capabilities: string[];
  projection: string;
  cursors: ScientificCursor[];
}

export interface CycleStartPayload {
  creation_idempotency_key: string;
  expected_revision: 0;
  raw_question: string;
  contract_version: typeof AI_SCIENTIST_PROTOCOL;
  boundary: { kind: "cognitive_only"; description: string };
  creator: Record<string, unknown>;
}

export type EmptyScientificActionPayload = Record<string, never>;

export interface CycleAbortPayload {
  expected_revision: number;
  actor: Record<string, unknown>;
  reason: string;
  final_observation: string;
}

export interface RevisionedScientificPayload {
  expected_revision?: number;
  [key: string]: unknown;
}

export interface CycleReplayPayload {
  client_instance_id: string;
  request_ordinal: number;
  cursor: ScientificCursor;
  max_events: number;
}

export interface CycleResumePayload {
  client_instance_id: string;
  request_ordinal: number;
  cycle_id: string;
  cursor: ScientificCursor;
  projection: string;
}

export interface ExportCreatePayload {
  expected_revision: number;
  format: "scientific-export.v1";
  artifact_ids: string[];
  report_body_id: string | null;
  redaction_profile_id: string | null;
  external_reference_ids: string[];
}

export interface ExportGetPayload {
  client_instance_id: string;
  request_ordinal: number;
  export_id: string;
  include_archive_bytes: boolean;
}

export interface ReportRenderPayload {
  client_instance_id: string;
  request_ordinal: number;
  cycle_id: string;
  at_revision: number;
  format: "canonical_json" | "markdown" | "html";
  include_status_overlay: boolean;
}

export interface CycleAcknowledgementPayload {
  client_instance_id: string;
  ack_ordinal: number;
  checkpoint: ScientificCursor;
  state_hash: string;
}

export type ScientificActionPayloadMap = {
  "protocol.hello": HelloPayload;
  "cycle.start": CycleStartPayload;
  "cycle.replay": CycleReplayPayload;
  "cycle.resume": CycleResumePayload;
  "cycle.continue": RevisionedScientificPayload;
  "responsibility.question_selection.disposition": RevisionedScientificPayload;
  "responsibility.safety_ethics_review.disposition": RevisionedScientificPayload;
  "responsibility.execution_accountability.disposition": RevisionedScientificPayload;
  "responsibility.exception_interpretation.disposition": RevisionedScientificPayload;
  "responsibility.novelty_value_judgment.disposition": RevisionedScientificPayload;
  "responsibility.final_accountability.disposition": RevisionedScientificPayload;
  "responsibility.disposition.supersede": RevisionedScientificPayload;
  "proposal.reject": RevisionedScientificPayload;
  "result.submit": RevisionedScientificPayload;
  "validation.adjudicate": RevisionedScientificPayload;
  "export.create": ExportCreatePayload;
  "export.get": ExportGetPayload;
  "report.render": ReportRenderPayload;
  "cycle.abort": CycleAbortPayload;
  "cycle.ack": CycleAcknowledgementPayload;
};

export type ScientificActionName = keyof ScientificActionPayloadMap;

export const SCIENTIFIC_EVENT_NAMES = [
  "cycle.started",
  "cycle.continued",
  "cycle.completed",
  "responsibility.disposition.recorded",
  "responsibility.disposition.superseded",
  "proposal.rejected",
  "result.recorded",
  "validation.assessment.recorded",
  "validation.assessment.transitioned",
  "export.created",
  "cycle.aborted",
  "cycle.snapshot",
  "snapshot.repair_required",
] as const;

export const SCIENTIFIC_RESPONSE_NAMES = [
  "protocol.welcome.response",
  "command.accepted.response",
  "cycle.replay.response",
  "cycle.resume.response",
  "export.get.response",
  "report.render.response",
  "cycle.acknowledged.response",
] as const;

export const SCIENTIFIC_ERROR_NAMES = [
  "command.rejected.error",
  "protocol.invalid.error",
] as const;

export const SCIENTIFIC_ERROR_CODES = [
  "protocol_invalid",
  "protocol_unsupported",
  "unknown_action",
  "validation_failed",
  "unsupported_transition",
  "supersession_conflict",
  "import_forbidden",
  "export_too_large",
  "feature_disabled",
  "capability_required",
  "read_only",
  "policy_required",
  "gate_unsatisfied",
  "idempotency_conflict",
  "revision_conflict",
  "cursor_ahead",
  "cursor_mismatch",
  "ack_mismatch",
  "not_found",
  "artifact_not_found",
  "repository_corrupt",
  "commit_outcome_unknown",
] as const;

export type ScientificEvent = ScientificEnvelope<string, unknown>;

export interface ScientificSuccessResponse {
  ok: true;
  action: ScientificActionName;
  accepted_sequence: number;
  accepted_revision: number;
}

export interface ScientificErrorResponse {
  ok: false;
  error: ScientificError;
}

export interface ScientificError {
  code: string;
  message: string;
  retryable?: boolean;
  details?: unknown;
}

export type ScientificResponse = ScientificSuccessResponse | ScientificErrorResponse;
