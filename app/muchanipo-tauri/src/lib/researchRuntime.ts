import type { BackendEvent } from "./tauriClient";
import type { ResearchRuntimeContext } from "./researchExecution";
export type { ResearchRuntimeContext } from "./researchExecution";
export {
  toResearchProviderProjection,
} from "./researchProviderProjection";
export type { ResearchProviderProjection } from "./researchProviderProjection";
export { emptyResearchActivity, toResearchActivityProjections } from "./researchActivity";
export { reduceResearchActivity } from "./researchActivityReducer";
export type { OrdinalUncertainty, ResearchActivity, ResearchActivityProjection, ResearchCounterSearch, ResearchStance } from "./researchActivity";

const STORAGE_KEY_VERSION = "v1";

const RESEARCH_STATUS_LABELS: Readonly<Record<string, string>> = {
  adaptive_followup_query_plan: "후속 검색 계획",
  claim_evidence_gate: "주장과 근거 검증",
  claim_traceability_scored: "주장 추적성 평가",
  evidence_compared: "근거 비교",
  evidence_ledger_built: "근거 장부 생성",
  facet_gap_scheduler_report: "근거 공백 보완 계획",
  facet_summary: "주제별 근거 요약",
  knowledge_gap: "근거 공백 확인",
  max_plus_benchmark_scored: "품질 벤치마크 평가",
  query_planned: "검색 계획",
  query_route_ledger_built: "검색 경로 기록",
  ready_before_council: "전문가 검토 준비",
  report_writing: "보고서 작성",
  research_plan_ready: "연구 계획 준비",
  research_process_completeness: "연구 과정 완전성 확인",
  research_quality_ready: "연구 품질 검토 완료",
  searching: "자료 검색",
  source_audit_gate: "출처 감사",
  source_decision: "출처 채택 판단",
  source_decision_ledger_built: "출처 판단 기록",
  source_evaluated: "출처 평가",
  source_found: "출처 발견",
  source_resolved: "출처 확인",
  uncertainty_ledger_built: "불확실성 기록",
};

export type ResearchConversationEvent =
  | ResearchProgressConversationEvent
  | ResearchReportConversationEvent;

export type ResearchProgressConversationEvent = {
  readonly event: "research_progress";
  readonly eventId: string;
  readonly runId: string;
  readonly turnId: string;
  readonly stage: string;
  readonly sourceIds: readonly string[];
  readonly artifactIds: readonly string[];
};

export type ResearchReportConversationEvent = {
  readonly event: "report_chunk" | "final_report";
  readonly eventId: string;
  readonly runId: string;
  readonly turnId: string;
  readonly body: string;
  readonly sourceIds: readonly string[];
  readonly artifactIds: readonly string[];
};

export type ResearchInteractionOption = {
  readonly key: string;
  readonly label: string;
  readonly value?: string;
};

export type ResearchInteraction = {
  readonly kind: "inline";
  readonly id: string;
  readonly title: string;
  readonly prompt: string;
  readonly options: readonly ResearchInteractionOption[];
};

export function researchConversationStorageKey(
  context: Pick<ResearchRuntimeContext, "runId">,
): string {
  return `muchanipo.research-conversation.${STORAGE_KEY_VERSION}.${context.runId}`;
}

export function toResearchConversationEvent(
  event: BackendEvent,
  context: ResearchRuntimeContext,
): ResearchConversationEvent | undefined {
  if (!isEventForContext(event, context)) return undefined;

  const eventId = `${context.runId}:${context.turnId}:${context.eventIndex}`;
  const artifactIds = readStrictStringArray(event["artifact_ids"]);
  if (!artifactIds) return undefined;

  switch (event.event) {
    case "research_progress": {
      const status = requiredText(event.status);
      if (!status) return undefined;
      const sourceIds = readSourceIds(event.source_url);
      if (!sourceIds) return undefined;
      return {
        event: "research_progress",
        eventId,
        runId: context.runId,
        turnId: context.turnId,
        stage: researchStage(status, event.query, event.source_title),
        sourceIds,
        artifactIds,
      };
    }
    case "report_chunk": {
      const body = requiredText(event.markdown) ?? requiredText(event.delta);
      if (!body) return undefined;
      return reportConversationEvent("report_chunk", eventId, body, context, artifactIds);
    }
    case "final_report": {
      const body = requiredText(event.markdown);
      const reportPath = requiredText(event.report_path);
      if (!body || !reportPath) return undefined;
      const vaultPath = requiredText(event.vault_path);
      return reportConversationEvent(
        "final_report",
        eventId,
        body,
        context,
        [...new Set([...artifactIds, reportPath, ...(vaultPath ? [vaultPath] : [])])],
      );
    }
    default:
      return undefined;
  }
}

export function toResearchInteraction(
  event: BackendEvent,
  context: ResearchRuntimeContext,
): ResearchInteraction | undefined {
  if (!isEventForContext(event, context)) return undefined;

  const options = normalizeInteractionOptions(event.options);
  if (!options) return undefined;

  switch (event.event) {
    case "interview_question": {
      const id = requiredText(event.q_id);
      const prompt = requiredText(event.text);
      if (!id || !prompt) return undefined;
      return {
        kind: "inline",
        id,
        title: "Research question",
        prompt,
        options,
      };
    }
    case "hitl_gate": {
      const id = requiredText(event.gate);
      const title = requiredText(event.title);
      const prompt = requiredText(event.prompt);
      if (!id || !title || !prompt) return undefined;
      return { kind: "inline", id, title, prompt, options };
    }
    default:
      return undefined;
  }
}

function isEventForContext(event: BackendEvent, context: ResearchRuntimeContext): boolean {
  return requiredText(event.app_run_id) === context.runId
    && event["generation"] === context.generation;
}

function reportConversationEvent(
  event: ResearchReportConversationEvent["event"],
  eventId: string,
  body: string,
  context: ResearchRuntimeContext,
  artifactIds: readonly string[],
): ResearchReportConversationEvent {
  return {
    event,
    eventId,
    runId: context.runId,
    turnId: context.turnId,
    body,
    sourceIds: [],
    artifactIds,
  };
}

function researchStage(status: string, query: unknown, sourceTitle: unknown): string {
  const parts = [humanizeStatus(status), optionalText(query), optionalText(sourceTitle)];
  return parts.filter((part): part is string => part !== undefined).join(" · ");
}

function humanizeStatus(status: string): string {
  return RESEARCH_STATUS_LABELS[status.trim().toLowerCase()] ?? "연구 진행";
}

function readSourceIds(value: unknown): readonly string[] | undefined {
  if (value === undefined || value === null) return [];
  const sourceUrl = requiredText(value);
  return sourceUrl ? [sourceUrl] : undefined;
}

function readStrictStringArray(value: unknown): readonly string[] | undefined {
  if (value === undefined) return [];
  if (!Array.isArray(value)) return undefined;
  const values = value.map(requiredText);
  return values.every((item): item is string => item !== undefined) ? values : undefined;
}

function normalizeInteractionOptions(
  value: readonly unknown[] | undefined,
): readonly ResearchInteractionOption[] | undefined {
  if (value === undefined) return [];
  const options = value.map(normalizeInteractionOption);
  return options.every((option): option is ResearchInteractionOption => option !== undefined)
    ? options
    : undefined;
}

function normalizeInteractionOption(
  value: unknown,
  index: number,
): ResearchInteractionOption | undefined {
  if (typeof value === "string") return stringInteractionOption(value, index);
  if (!isRecord(value)) return undefined;

  const label = firstRequiredText(value["label"], value["text"], value["description"], value["value"], value["key"]);
  const key = firstOptionalText(value["key"], value["value"], value["id"]) ?? optionKey(index);
  const optionValue = value["value"];
  if (!label || (optionValue !== undefined && !requiredText(optionValue))) return undefined;
  const normalizedValue = optionalText(optionValue);
  return normalizedValue ? { key, label, value: normalizedValue } : { key, label };
}

function stringInteractionOption(value: string, index: number): ResearchInteractionOption | undefined {
  const text = requiredText(value);
  if (!text) return undefined;
  const match = text.match(/^([A-Za-z])[).\s-]*(.*)$/);
  const label = requiredText(match?.[2]) ?? text;
  return { key: match?.[1]?.toUpperCase() ?? optionKey(index), label };
}

function optionKey(index: number): string {
  return String.fromCharCode("A".charCodeAt(0) + index);
}

function firstRequiredText(...values: readonly unknown[]): string | undefined {
  for (const value of values) {
    const text = requiredText(value);
    if (text) return text;
  }
  return undefined;
}

function firstOptionalText(...values: readonly unknown[]): string | undefined {
  for (const value of values) {
    const text = optionalText(value);
    if (text) return text;
  }
  return undefined;
}

function requiredText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function optionalText(value: unknown): string | undefined {
  return typeof value === "string" ? requiredText(value) : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
