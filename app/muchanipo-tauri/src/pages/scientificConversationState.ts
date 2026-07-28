import {
  createResearchAssistantMessage,
  formatResearchDuration,
} from "../lib/researchConversation";
import type { ScientificState } from "../lib/scientificReducer";

const STAGE_LABELS: Readonly<Record<string, string>> = {
  L: "질문 검토",
  H: "가설 수립",
  P: "실험 설계",
  X: "외부 결과 확인",
  A: "근거 검토",
  W: "최종 판정",
};

const EVENT_LABELS: Readonly<Record<string, string>> = {
  "cycle.started": "연구 사이클을 시작했습니다",
  "cycle.continued": "다음 검증 단계로 이동했습니다",
  "cycle.completed": "검증 사이클을 완료했습니다",
  "responsibility.disposition.recorded": "책임 있는 판단을 기록했습니다",
  "responsibility.disposition.superseded": "책임 판단을 갱신했습니다",
  "proposal.rejected": "검증 제안을 반려했습니다",
  "result.recorded": "외부 결과를 기록했습니다",
  "validation.assessment.recorded": "검증 평가를 기록했습니다",
  "validation.assessment.transitioned": "검증 상태를 갱신했습니다",
  "export.created": "검토 패키지를 생성했습니다",
  "cycle.aborted": "연구 사이클을 중단했습니다",
  "cycle.snapshot": "검증 상태를 저장했습니다",
  "snapshot.repair_required": "검증 기록 복구가 필요합니다",
};

export type ActivityItemState = "complete" | "working" | "error" | "muted";

export interface ActivityItem {
  readonly id: string;
  readonly label: string;
  readonly meta: string;
  readonly state: ActivityItemState;
}

interface ScientificConversationInput {
  readonly actionError?: string;
  readonly elapsedSeconds: number;
  readonly errorCount: number;
  readonly hasActiveCycle: boolean;
  readonly isBrowserPreview: boolean;
  readonly startRequested: boolean;
  readonly state: ScientificState;
}

export function deriveScientificConversationState({
  actionError,
  elapsedSeconds,
  errorCount,
  hasActiveCycle,
  isBrowserPreview,
  startRequested,
  state,
}: ScientificConversationInput) {
  const isTerminal = state.events.some(
    (event) => event.type === "cycle.completed" || event.type === "cycle.aborted",
  );
  const isProcessing = !isBrowserPreview &&
    (startRequested || (hasActiveCycle && !isTerminal));
  const stageLabel = state.stage
    ? STAGE_LABELS[state.stage] ?? state.stage
    : "검증 준비";
  const visibleActionError = isBrowserPreview &&
      actionError?.includes("브라우저 미리보기")
    ? undefined
    : actionError;
  const elapsedLabel = formatResearchDuration(elapsedSeconds);
  const processSummary = isBrowserPreview
    ? "외부 작업 미실행"
    : visibleActionError || errorCount > 0
      ? `${elapsedLabel} 동안 작업 · 오류 확인 필요`
      : isProcessing
        ? `${elapsedLabel} 동안 작업 중 · ${stageLabel}`
        : `${elapsedLabel} 동안 작업 · 기록 ${state.events.length}개`;
  const activityItems: readonly ActivityItem[] = [
    {
      id: "question-received",
      label: "연구 질문을 대화에 기록했습니다",
      meta: "완료",
      state: "complete",
    },
    ...(isBrowserPreview
      ? [{
          id: "browser-boundary",
          label: "외부 자료 수집은 데스크톱 앱에서 실행됩니다",
          meta: "미실행",
          state: "muted" as const,
        }]
      : state.events.slice(-5).map((event) => ({
          id: event.message_id,
          label: EVENT_LABELS[event.type] ?? event.type,
          meta: `기록 ${event.sequence}`,
          state: "complete" as const,
        }))),
    ...(!isBrowserPreview && isProcessing
      ? [{
          id: "current-stage",
          label: `${stageLabel} 단계를 진행하고 있습니다`,
          meta: "진행 중",
          state: "working" as const,
        }]
      : []),
    ...(errorCount > 0
      ? [{
          id: "server-errors",
          label: `서버 오류 ${errorCount}건을 기록했습니다`,
          meta: "확인 필요",
          state: "error" as const,
        }]
      : []),
    ...(visibleActionError
      ? [{
          id: "action-error",
          label: visibleActionError,
          meta: "확인 필요",
          state: "error" as const,
        }]
      : []),
  ];

  return {
    activityItems,
    assistant: createResearchAssistantMessage({
      isBrowserPreview,
      startRequested: isProcessing,
      stage: state.stage ? stageLabel : undefined,
      eventCount: state.events.length,
    }),
    isProcessing,
    processSummary,
    visibleActionError,
  };
}
