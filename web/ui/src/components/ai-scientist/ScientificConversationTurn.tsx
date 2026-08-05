import type { ScientificState } from "../../lib/scientificReducer";
import type { ScientificActionName } from "../../lib/types";
import type { ScientificEnvelope } from "../../lib/tauri";
import type { ActivityItem } from "../../pages/scientificConversationState";
import { ScientificCycleView } from "../ScientificCycleView";
import { ChatMessage, ProcessDisclosure } from "./ResearchChatPrimitives";

interface ScientificConversationTurnProps {
  readonly abortUnavailableReason?: string;
  readonly actionError?: string;
  readonly activityItems: readonly ActivityItem[];
  readonly assistant: ReturnType<
    typeof import("../../lib/researchConversation").createResearchAssistantMessage
  >;
  readonly errors: readonly ScientificEnvelope[];
  readonly exportUnavailableReason?: string;
  readonly hasActiveCycle: boolean;
  readonly isBrowserPreview: boolean;
  readonly isProcessing: boolean;
  readonly onAbort: () => void;
  readonly onExport: () => void;
  readonly onRecover: () => void;
  readonly onReset: () => void;
  readonly onWorkflowAction: (
    name: ScientificActionName,
    payload: Record<string, unknown>,
  ) => void;
  readonly processSummary: string;
  readonly recoveryUnavailableReason?: string;
  readonly resetUnavailableReason?: string;
  readonly responses: readonly ScientificEnvelope[];
  readonly state: ScientificState;
  readonly submittedQuestion: string;
  readonly visibleActionError?: string;
  readonly workflowActions: readonly ScientificActionName[];
  readonly workflowUnavailableReason?: string;
}

export function ScientificConversationTurn({
  abortUnavailableReason,
  actionError,
  activityItems,
  assistant,
  errors,
  exportUnavailableReason,
  hasActiveCycle,
  isBrowserPreview,
  isProcessing,
  onAbort,
  onExport,
  onRecover,
  onReset,
  onWorkflowAction,
  processSummary,
  recoveryUnavailableReason,
  resetUnavailableReason,
  responses,
  state,
  submittedQuestion,
  visibleActionError,
  workflowActions,
  workflowUnavailableReason,
}: ScientificConversationTurnProps) {
  return (
    <div className="ms-chat-stream" id="scientific-latest-turn">
      <ChatMessage label="나" meta="방금" role="user" state="complete">
        <p>{submittedQuestion}</p>
      </ChatMessage>

      <div className="ms-chat-activity">
        <ProcessDisclosure
          defaultOpen={isProcessing ||
            Boolean(visibleActionError) ||
            (!isBrowserPreview && errors.length > 0)}
          key={`research-process-${isProcessing ? "processing" : "idle"}-${visibleActionError ?? "clear"}-${errors.length}`}
          summary={processSummary}
          title="연구 과정"
        >
          <ol aria-label="최근 연구 활동" className="ms-activity-log">
            {activityItems.map((item) => (
              <li data-state={item.state} key={item.id}>
                <span aria-hidden="true" className="ms-activity-log__marker" />
                <div>
                  <strong>{item.label}</strong>
                  <small>{item.meta}</small>
                </div>
              </li>
            ))}
          </ol>

          <ProcessDisclosure
            className="ms-activity-details"
            defaultOpen={Boolean(visibleActionError) || errors.length > 0}
            key={`research-details-${visibleActionError ?? "clear"}-${errors.length}`}
            summary={isBrowserPreview
              ? "데스크톱 전용"
              : `서버 기록 ${state.events.length}개`}
            title="세부 검증 기록 및 제어"
          >
            {isBrowserPreview ? (
              <div className="ms-preview-process">
                <p>
                  브라우저 미리보기에서는 외부 자료를 수집하지 않았습니다.
          실제 수집과 검증 상태는 MUNI lab 웹앱에서 확인하세요.
                </p>
              </div>
            ) : (
              <ScientificCycleView
                hasActiveCycle={hasActiveCycle}
                isBrowserPreview={false}
                state={state}
                responses={responses}
                errors={errors}
                actionError={actionError}
                resetUnavailableReason={resetUnavailableReason}
                recoveryUnavailableReason={recoveryUnavailableReason}
                abortUnavailableReason={abortUnavailableReason}
                exportUnavailableReason={exportUnavailableReason}
                onReset={onReset}
                onRecover={onRecover}
                onAbort={onAbort}
                onExport={onExport}
                workflowActions={workflowActions}
                workflowUnavailableReason={workflowUnavailableReason}
                onWorkflowAction={onWorkflowAction}
              />
            )}
          </ProcessDisclosure>
        </ProcessDisclosure>
      </div>

      <div aria-live="polite">
        <ChatMessage
          id="scientific-latest-message"
          label="Mucha"
          meta={assistant.state === "loading" ? "응답 준비 중" : "응답"}
          role="assistant"
          state={visibleActionError
            ? "error"
            : assistant.state === "loading"
              ? "loading"
              : "complete"}
        >
          <p role={visibleActionError ? "alert" : undefined}>
            {visibleActionError ?? assistant.message}
          </p>
        </ChatMessage>
      </div>
    </div>
  );
}
