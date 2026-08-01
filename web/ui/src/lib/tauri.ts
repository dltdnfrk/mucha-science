import { invoke } from "../api/client";
import { listen, type UnlistenFn } from "../api/client";
import type {
  CycleAbortPayload,
  CycleAcknowledgementPayload,
  ScientificActionName,
  ScientificActionPayloadMap,
  ScientificEvent,
  ScientificProtocolEnvelope,
} from "./types";
export type { CycleAbortPayload } from "./types";

export type BackendEventName =
  | "phase_change"
  | "run_started"
  | "pipeline_heartbeat"
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
  | "council_turn"
  | "council_persona_token"
  | "council_round_done"
  | "final_report"
  | "hitl_gate"
  | "report_chunk"
  | "done"
  | "warning"
  | "error";

export interface BackendEvent {
  event: BackendEventName;
  [key: string]: unknown;
}

export interface BackendAction {
  action?: "interview_answer" | "approve_designdoc" | "hitl_decision" | "abort";
  type?: "interview_answer" | "approve_designdoc" | "hitl_decision" | "cancel" | "abort";
  q_id?: string;
  question_id?: string;
  answer?: string;
  selected?: string;
  other_text?: string;
  [key: string]: unknown;
}

export interface PipelineRuntimeStatus {
  running: boolean;
  stdin_open?: boolean;
  child_tracked?: boolean;
  buffered_event_count?: number;
  child_pid?: number | null;
  runtime_age_ms?: number | null;
  last_event_elapsed_ms?: number | null;
  app_binary_path?: string | null;
  workspace_root?: string;
}

export function startPipeline(
  topic: string,
  pipeline: "stub" | "full" = "full",
  envs: Record<string, string> = {},
): Promise<void> {
  return invoke("start_pipeline", { topic, pipeline, envs });
}

export function sendAction(action: BackendAction): Promise<void> {
  return invoke("send_action", { action: normalizeBackendAction(action) });
}

export function getPipelineRuntimeStatus(): Promise<PipelineRuntimeStatus> {
  return invoke("pipeline_runtime_status");
}

export function listenBackendEvents(
  onEvent: (event: BackendEvent) => void,
): Promise<UnlistenFn> {
  return listen<unknown>("backend_event", ({ payload }) => {
    if (isBackendEvent(payload)) {
      onEvent(payload);
    }
  });
}

export function normalizeBackendAction(action: BackendAction): BackendAction {
  const actionName = action.action;
  const legacyActionName = action.type === "cancel" ? "abort" : action.type;

  if (
    (!actionName && !legacyActionName) ||
    (actionName && (!isBackendActionName(actionName) || (legacyActionName && actionName !== legacyActionName))) ||
    (legacyActionName && !isBackendActionName(legacyActionName))
  ) {
    throw new Error("Legacy action requires one unambiguous action discriminator.");
  }

  const normalized: BackendAction = { ...action, action: actionName ?? legacyActionName };
  if (normalized.action === "interview_answer") {
    const questionId = normalized.q_id ?? normalized.question_id;
    const answer = normalized.answer ??
      (normalized.selected === "OTHER" ? normalized.other_text : normalized.selected);
    if (
      typeof questionId !== "string" ||
      questionId.length === 0 ||
      typeof answer !== "string" ||
      answer.length === 0
    ) {
      throw new Error("Interview answers require a question ID and a non-empty answer.");
    }
    normalized.q_id = questionId;
    normalized.answer = answer;
  }

  delete normalized.type;
  delete normalized.question_id;
  return normalized;
}
function isBackendEvent(value: unknown): value is BackendEvent {
  // Legacy backend telemetry is permissive: the full research pipeline emits
  // event names beyond the stub-era catalog (run_started, stage telemetry,
  // final_report, …) and listeners preserve unknown legacy events.
  return isRecord(value) && typeof value.event === "string" && value.event.length > 0;
}

function isBackendActionName(value: unknown): value is NonNullable<BackendAction["action"]> {
  return value === "interview_answer" || value === "approve_designdoc" || value === "abort";
}
export type ScientificEnvelope = ScientificProtocolEnvelope;

export interface ScientificActionOptions {
  cycleId?: string | null;
  idempotencyKey?: string | null;
}
export type ScientificCapabilities = readonly string[];


export function welcomeCapabilities(
  response: ScientificEnvelope,
): ScientificCapabilities | undefined {
  if (response.name !== "protocol.welcome.response") {
    return undefined;
  }

  const capabilities = response.payload.capabilities;
  return Array.isArray(capabilities) && capabilities.every((value) => typeof value === "string")
    ? capabilities
    : undefined;
}

export function supportsScientificAction(
  capabilities: ScientificCapabilities | undefined,
  name: ScientificActionName,
): boolean {
  return capabilities?.includes(name) ?? false;
}

export function createAdvertisedScientificAction<TName extends ScientificActionName>(
  capabilities: ScientificCapabilities | undefined,
  name: TName,
  payload: ScientificActionPayloadMap[TName],
  options: ScientificActionOptions = {},
): ScientificEnvelope | undefined {
  return supportsScientificAction(capabilities, name)
    ? createScientificAction(name, payload, options)
    : undefined;
}

export function createAcknowledgementAction(
  capabilities: ScientificCapabilities | undefined,
  event: ScientificEnvelope,
  payload: CycleAcknowledgementPayload,
): ScientificEnvelope | undefined {
  if (!event.cycle_id) {
    return undefined;
  }

  return createAdvertisedScientificAction(capabilities, "cycle.ack", payload, {
    cycleId: event.cycle_id,
  });
}
export function createAcknowledgementForScientificEvent(
  capabilities: ScientificCapabilities | undefined,
  event: ScientificEvent,
  payload: CycleAcknowledgementPayload,
): ScientificEnvelope | undefined {
  return createAdvertisedScientificAction(capabilities, "cycle.ack", payload, {
    cycleId: event.session_id,
  });
}
export function abortPayloadFromServer(
  envelope: ScientificEnvelope,
): CycleAbortPayload | undefined {
  const { expected_revision, actor, reason, final_observation } = envelope.payload;
  return isSafeNonNegativeInteger(expected_revision) &&
    isRecord(actor) &&
    typeof reason === "string" &&
    reason.length > 0 &&
    typeof final_observation === "string"
    ? { expected_revision, actor, reason, final_observation }
    : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)
  );
}

export function createScientificAction<TName extends ScientificActionName>(
  name: TName,
  payload: ScientificActionPayloadMap[TName],
  options: ScientificActionOptions = {},
): ScientificEnvelope {
  const message_id = scientificId("message");
  const readAction = isScientificReadAction(name);
  const idempotency_key = name === "protocol.hello"
    ? (payload as ScientificActionPayloadMap["protocol.hello"]).handshake_idempotency_key
    : readAction
      ? null
      : options.idempotencyKey ?? scientificId("idempotency");
  return {
    protocol: "muchanipo",
    protocol_version: "ai-scientist.v1",
    kind: "action",
    name,
    message_id,
    cycle_id: options.cycleId ?? null,
    correlation_id: message_id,
    causation_id: null,
    sequence: 0,
    revision: 0,
    idempotency_key,
    timestamp: scientificTimestamp(),
    payload: payload as Record<string, unknown>,
    extensions: {},
  };
}
export function acceptedCycleId(response: ScientificEnvelope): string | undefined {
  return response.name === "command.accepted.response" &&
    typeof response.cycle_id === "string"
    ? response.cycle_id
    : undefined;
}

export function startScientificSidecar(
  sidecarPath?: string,
): Promise<void> {
  return invoke("start_scientific_sidecar", { sidecarPath });
}
export function stopScientificSidecar(): Promise<void> {
  return invoke("stop_scientific_sidecar");
}

export function sendScientificAction(
  envelope: ScientificEnvelope,
): Promise<void> {
  return invoke("write_envelope", { envelope });
}

export function listenScientificEvents(
  onEvent: (event: ScientificEnvelope) => void,
): Promise<UnlistenFn> {
  return listen<ScientificEnvelope>("backend_event", ({ payload }) => {
    if (isScientificEnvelope(payload) && (payload.kind === "event" || payload.kind === "snapshot" || payload.kind === "diagnostic")) {
      onEvent(payload);
    }
  });
}

export function listenScientificResponses(
  onResponse: (response: ScientificEnvelope) => void,
): Promise<UnlistenFn> {
  return listen<ScientificEnvelope>("backend_event", ({ payload }) => {
    if (isScientificEnvelope(payload) && payload.kind === "response") {
      onResponse(payload);
    }
  });
}

export function listenScientificErrors(
  onError: (error: ScientificEnvelope) => void,
): Promise<UnlistenFn> {
  return listen<ScientificEnvelope>("backend_event", ({ payload }) => {
    if (isScientificEnvelope(payload) && payload.kind === "error") {
      onError(payload);
    }
  });
}

export function toScientificEvent(
  envelope: unknown,
): ScientificEvent | undefined {
  if (!isScientificEnvelope(envelope) ||
      (envelope.kind !== "event" && envelope.kind !== "snapshot" && envelope.kind !== "diagnostic") ||
      !envelope.cycle_id) {
    return undefined;
  }

  return {
    protocol: "ai-scientist.v1",
    message_id: envelope.message_id,
    session_id: envelope.cycle_id,
    sequence: envelope.sequence,
    revision: envelope.revision,
    type: envelope.name,
    payload: envelope.payload,
  };
}
function scientificId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID().replaceAll("-", "")}`;
}

function scientificTimestamp(): string {
  return new Date().toISOString().replace(/\.(\d{3})Z$/, ".$1000Z");
}

const protocolIdPattern = /^[a-z][a-z0-9_]*_[0-9a-f]{32}$/;
const timestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;
const scientificReadActions = new Set<ScientificActionName>([
  "cycle.replay",
  "cycle.resume",
  "export.get",
  "report.render",
  "cycle.ack",
]);
function isScientificReadAction(name: ScientificActionName): boolean {
  return scientificReadActions.has(name);
}

function isSafeNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isNullableProtocolId(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && protocolIdPattern.test(value));
}

export function isScientificEnvelope(value: unknown): value is ScientificEnvelope {
  if (!isRecord(value)) {
    return false;
  }

  return (
    value.protocol === "muchanipo" &&
    value.protocol_version === "ai-scientist.v1" &&
    (value.kind === "action" ||
      value.kind === "event" ||
      value.kind === "response" ||
      value.kind === "error" ||
      value.kind === "snapshot" ||
      value.kind === "diagnostic") &&
    typeof value.name === "string" &&
    value.name.length > 0 &&
    typeof value.message_id === "string" &&
    protocolIdPattern.test(value.message_id) &&
    isNullableProtocolId(value.cycle_id) &&
    isNullableProtocolId(value.correlation_id) &&
    isNullableProtocolId(value.causation_id) &&
    isSafeNonNegativeInteger(value.sequence) &&
    isSafeNonNegativeInteger(value.revision) &&
    (value.idempotency_key === null ||
      (typeof value.idempotency_key === "string" && value.idempotency_key.length > 0)) &&
    typeof value.timestamp === "string" &&
    timestampPattern.test(value.timestamp) &&
    isRecord(value.payload) &&
    isRecord(value.extensions)
  );
}
