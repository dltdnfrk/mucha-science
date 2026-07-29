import type {
  PipelineCancellationAcknowledgement,
  PipelineRuntimeStatus,
} from "./pipelineExecutionClient";
import type {
  PipelineLaunchReceipt,
  PipelineProcessIdentity,
} from "./researchExecution";
import type { BackendEvent } from "./tauriClient";


export const WEB_PIPELINE_PROTOCOL = "mucha-science.web.v1";

export class WebPipelineProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WebPipelineProtocolError";
  }
}

export function parseWebPipelineMessage(data: unknown): Record<string, unknown> {
  if (typeof data !== "string") {
    throw new WebPipelineProtocolError("웹 연구 서버가 텍스트가 아닌 응답을 보냈습니다.");
  }
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new WebPipelineProtocolError("웹 연구 서버 응답이 올바른 JSON이 아닙니다.");
    }
    throw error;
  }
  if (!isRecord(value)) {
    throw new WebPipelineProtocolError("웹 연구 서버 응답 형식이 올바르지 않습니다.");
  }
  if (value.protocol === WEB_PIPELINE_PROTOCOL && value.type === "error") {
    const error = value.error;
    const message = isRecord(error) && typeof error.message === "string"
      ? error.message
      : "웹 연구 서버가 요청을 거부했습니다.";
    throw new WebPipelineProtocolError(message);
  }
  return value;
}

export function parsePipelineLaunchReceipt(
  value: Record<string, unknown>,
): PipelineLaunchReceipt {
  if (
    value.protocol !== WEB_PIPELINE_PROTOCOL
    || value.type !== "run.started"
    || !isRecord(value.receipt)
    || !isLaunchReceipt(value.receipt)
  ) {
    throw new WebPipelineProtocolError("웹 연구 시작 응답이 올바르지 않습니다.");
  }
  return value.receipt;
}

export function parsePipelineCancellation(
  value: Record<string, unknown>,
): PipelineCancellationAcknowledgement {
  if (
    value.protocol !== WEB_PIPELINE_PROTOCOL
    || value.type !== "run.cancelled"
    || !isRecord(value.acknowledgement)
    || !isCancellationAcknowledgement(value.acknowledgement)
  ) {
    throw new WebPipelineProtocolError("웹 연구 취소 응답이 올바르지 않습니다.");
  }
  return value.acknowledgement;
}

export function parsePipelineRuntimeStatus(
  value: Record<string, unknown>,
): PipelineRuntimeStatus {
  const status = value.status;
  if (
    value.protocol !== WEB_PIPELINE_PROTOCOL
    || value.type !== "runtime.status"
    || !isRecord(status)
    || typeof status.running !== "boolean"
  ) {
    throw new WebPipelineProtocolError("웹 연구 상태 응답이 올바르지 않습니다.");
  }
  const running: boolean = status.running;
  return {
    running,
    ...(typeof status.stdin_open === "boolean" ? { stdin_open: status.stdin_open } : {}),
    ...(typeof status.child_tracked === "boolean" ? { child_tracked: status.child_tracked } : {}),
    ...(typeof status.buffered_event_count === "number"
      ? { buffered_event_count: status.buffered_event_count }
      : {}),
    ...(typeof status.child_pid === "number" || status.child_pid === null
      ? { child_pid: status.child_pid }
      : {}),
    ...(typeof status.app_run_id === "string" || status.app_run_id === null
      ? { app_run_id: status.app_run_id }
      : {}),
    ...(typeof status.runtime_age_ms === "number" || status.runtime_age_ms === null
      ? { runtime_age_ms: status.runtime_age_ms }
      : {}),
    ...(typeof status.workspace_root === "string"
      ? { workspace_root: status.workspace_root }
      : {}),
  };
}

export function toWebBackendEvent(
  value: Record<string, unknown>,
): BackendEvent | undefined {
  if (
    value.protocol === WEB_PIPELINE_PROTOCOL
    && value.type === "transport.heartbeat"
  ) {
    return undefined;
  }
  return typeof value.event === "string" && value.event.length > 0
    ? { ...value, event: value.event }
    : undefined;
}

function isLaunchReceipt(value: Record<string, unknown>): value is PipelineLaunchReceipt {
  return (
    typeof value.app_run_id === "string"
    && typeof value.generation === "number"
    && typeof value.launch_nonce === "string"
    && typeof value.owner_boot_id === "string"
    && typeof value.executable_path === "string"
    && typeof value.executable_digest === "string"
    && typeof value.reserved_at_unix_ms === "number"
    && isReceiptPhase(value.phase)
    && (value.identity === null || isProcessIdentity(value.identity))
    && (value.terminal_kind === null || isTerminalKind(value.terminal_kind))
    && typeof value.termination_observed === "boolean"
    && typeof value.reaped === "boolean"
    && typeof value.termination_kill_sent === "boolean"
  );
}

function isProcessIdentity(value: unknown): value is PipelineProcessIdentity {
  return (
    isRecord(value)
    && typeof value.pid === "number"
    && typeof value.process_start_time === "string"
    && typeof value.pgid === "number"
    && typeof value.launch_nonce === "string"
    && typeof value.generation === "number"
    && typeof value.owner_boot_id === "string"
    && typeof value.executable_digest === "string"
  );
}

function isCancellationAcknowledgement(
  value: unknown,
): value is PipelineCancellationAcknowledgement {
  return (
    isRecord(value)
    &&
    typeof value.acknowledged === "boolean"
    && typeof value.app_run_id === "string"
    && typeof value.generation === "number"
    && typeof value.termination_observed === "boolean"
    && typeof value.reaped === "boolean"
    && typeof value.kill_sent === "boolean"
  );
}

function isReceiptPhase(
  value: unknown,
): value is PipelineLaunchReceipt["phase"] {
  return (
    value === "reserved"
    || value === "spawned"
    || value === "running"
    || value === "cancel_requested"
    || value === "exit_observed"
    || value === "terminal"
  );
}

function isTerminalKind(
  value: unknown,
): value is Exclude<PipelineLaunchReceipt["terminal_kind"], null> {
  return value === "completed" || value === "failed" || value === "canceled";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
