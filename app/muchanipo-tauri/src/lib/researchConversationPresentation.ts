const MAX_THREAD_LABEL_LENGTH = 32;
const ELLIPSIS = "…";

export type ResearchAssistantState = "ready" | "loading";
export type ResearchAssistantMode = "preview" | "idle" | "running" | "observed";

export interface ResearchAssistantMessageInput {
  readonly eventCount?: number;
  readonly isBrowserPreview: boolean;
  readonly sourceNames?: readonly string[];
  readonly stage?: string;
  readonly startRequested?: boolean;
}

export interface ResearchAssistantMessage {
  readonly eventCount: number;
  readonly message: string;
  readonly mode: ResearchAssistantMode;
  readonly sourceNames: readonly string[];
  readonly stage?: string;
  readonly state: ResearchAssistantState;
}

export function normalizeResearchPrompt(prompt: string): string {
  const normalized = prompt.trim();
  if (normalized.length === 0) throw new ResearchPromptError();
  return normalized;
}

export function createResearchAssistantMessage(
  input: ResearchAssistantMessageInput,
): ResearchAssistantMessage {
  const eventCount = Number.isInteger(input.eventCount) && (input.eventCount ?? 0) > 0
    ? input.eventCount as number
    : 0;
  const sourceNames = [...new Set(
    (input.sourceNames ?? []).map((source) => source.trim()).filter(Boolean),
  )];
  const projection = {
    eventCount,
    sourceNames,
    ...(input.stage ? { stage: input.stage } : {}),
  };
  if (input.isBrowserPreview) {
    return {
      ...projection,
      mode: "preview",
      state: "ready",
      message:
        "브라우저 미리보기에서는 질문만 기록했으며 외부 자료 수집은 실행하지 않았습니다. 연구 서버에 연결한 뒤 다시 시작하세요.",
    };
  }

  const stageSummary = input.stage
    ? `${input.stage} 단계를 진행하고 있습니다.`
    : "질문의 범위를 확인하고 검증을 준비하고 있습니다.";
  if (input.startRequested) {
    const eventSummary = eventCount > 0 ? ` 확인된 이벤트 ${eventCount}개.` : "";
    return {
      ...projection,
      mode: "running",
      state: "loading",
      message: `${stageSummary}${eventSummary} 서버가 확인한 과정만 연구 기록에 추가합니다.`,
    };
  }
  return eventCount > 0
    ? {
        ...projection,
        mode: "observed",
        state: "ready",
        message: `검증 기록 ${eventCount}개를 확인했습니다. 연구 과정에서 근거와 판정 상태를 검토하세요.`,
      }
    : {
        ...projection,
        mode: "idle",
        state: "ready",
        message: sourceNames.length > 0
          ? `연결된 출처 ${sourceNames.join(", ")}에서 검증 가능한 연구를 시작할 수 있습니다.`
          : "질문을 보내면 Mucha가 검증 가능한 연구 흐름을 시작합니다.",
      };
}

export function formatResearchDuration(totalSeconds: number): string {
  const safeSeconds = Number.isFinite(totalSeconds)
    ? Math.max(0, Math.floor(totalSeconds))
    : 0;
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;
  if (hours > 0) return `${hours}시간 ${minutes}분 ${seconds}초`;
  if (minutes > 0) return `${minutes}분 ${seconds}초`;
  return `${seconds}초`;
}

const ARTIFACT_LABELS: Readonly<Record<string, string>> = {
  "evidence-ledger": "근거 장부",
  report: "최종 보고서",
  "source-audit": "출처 검토 기록",
};

export function formatResearchArtifactLabel(value: string): string {
  const normalized = value.trim();
  if (normalized.startsWith("artifact:")) {
    const kind = normalized.split(":")[1] ?? "";
    return ARTIFACT_LABELS[kind] ?? "연구 산출물";
  }
  const filename = normalized.split(/[\\/]/).at(-1);
  return filename && filename !== normalized ? `파일 · ${filename}` : normalized;
}

export function createThreadLabel(question: string): string {
  const normalized = normalizeResearchPrompt(question);
  if (normalized.length <= MAX_THREAD_LABEL_LENGTH) return normalized;
  const availableLength = MAX_THREAD_LABEL_LENGTH - ELLIPSIS.length;
  const candidate = normalized.slice(0, availableLength + 1);
  const boundary = candidate.lastIndexOf(" ");
  const prefix = boundary > 0
    ? normalized.slice(0, boundary)
    : normalized.slice(0, availableLength);
  return `${prefix}${ELLIPSIS}`;
}

export class ResearchPromptError extends Error {
  readonly code = "EMPTY_RESEARCH_PROMPT";

  constructor() {
    super("연구 질문을 한 문장 이상 입력하세요.");
    this.name = "ResearchPromptError";
  }
}
