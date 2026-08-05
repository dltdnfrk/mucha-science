import { useEffect, useState, type FormEvent } from "react";
import { RuleButton } from "../components/ai-scientist/AiScientistPrimitives";
import {
  ResearchComposer,
} from "../components/ai-scientist/ResearchChatPrimitives";
import { ScientificConversationTurn } from "../components/ai-scientist/ScientificConversationTurn";
import type { ScientificState } from "../lib/scientificReducer";
import type { ScientificActionName } from "../lib/types";
import type { ScientificEnvelope } from "../lib/tauri";
import { deriveScientificConversationState } from "./scientificConversationState";

interface ScientificPageViewProps {
  readonly actionError?: string;
  readonly abortUnavailableReason?: string;
  readonly errors: readonly ScientificEnvelope[];
  readonly exportUnavailableReason?: string;
  readonly hasActiveCycle: boolean;
  readonly isBrowserPreview: boolean;
  readonly onAbort: () => void;
  readonly onExport: () => void;
  readonly onQuestionChange: (question: string) => void;
  readonly onRecover: () => void;
  readonly onReset: () => void;
  readonly onStart: () => void;
  readonly onWorkflowAction: (
    name: ScientificActionName,
    payload: Record<string, unknown>,
  ) => void;
  readonly question: string;
  readonly recoveryUnavailableReason?: string;
  readonly resetUnavailableReason?: string;
  readonly responses: readonly ScientificEnvelope[];
  readonly startRequested: boolean;
  readonly startUnavailableReason?: string;
  readonly state: ScientificState;
  readonly submittedQuestion?: string;
  readonly workflowActions: readonly ScientificActionName[];
  readonly workflowUnavailableReason?: string;
}

const STARTER_QUESTIONS = [
  "해수 온도 상승이 연안 조류 생장에 미치는 영향을 조사해줘",
  "상온 초전도체 연구의 재현성 근거를 비교해줘",
] as const;

export function ScientificPageView({
  actionError,
  abortUnavailableReason,
  errors,
  exportUnavailableReason,
  hasActiveCycle,
  isBrowserPreview,
  onAbort,
  onExport,
  onQuestionChange,
  onRecover,
  onReset,
  onStart,
  onWorkflowAction,
  question,
  recoveryUnavailableReason,
  resetUnavailableReason,
  responses,
  startRequested,
  startUnavailableReason,
  state,
  submittedQuestion,
  workflowActions,
  workflowUnavailableReason,
}: ScientificPageViewProps) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [startedAt] = useState(() => Date.now());
  const hasQuestion = question.trim().length > 0;
  const conversation = deriveScientificConversationState({
    actionError,
    elapsedSeconds,
    errorCount: errors.length,
    hasActiveCycle,
    isBrowserPreview,
    startRequested,
    state,
  });

  const submitQuestion = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onStart();
  };

  useEffect(() => {
    if (!conversation.isProcessing) return;

    const updateElapsed = () => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    };
    updateElapsed();
    const intervalId = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(intervalId);
  }, [conversation.isProcessing, startedAt]);

  return (
    <main className="ms-research-main">
      <section aria-label="MUNI lab 연구 대화" className="ms-chat-workspace">
        <div className="ms-chat-thread">
          {submittedQuestion ? (
            <ScientificConversationTurn
              abortUnavailableReason={abortUnavailableReason}
              actionError={actionError}
              activityItems={conversation.activityItems}
              assistant={conversation.assistant}
              errors={errors}
              exportUnavailableReason={exportUnavailableReason}
              hasActiveCycle={hasActiveCycle}
              isBrowserPreview={isBrowserPreview}
              isProcessing={conversation.isProcessing}
              onAbort={onAbort}
              onExport={onExport}
              onRecover={onRecover}
              onReset={onReset}
              onWorkflowAction={onWorkflowAction}
              processSummary={conversation.processSummary}
              recoveryUnavailableReason={recoveryUnavailableReason}
              resetUnavailableReason={resetUnavailableReason}
              responses={responses}
              state={state}
              submittedQuestion={submittedQuestion}
              visibleActionError={conversation.visibleActionError}
              workflowActions={workflowActions}
              workflowUnavailableReason={workflowUnavailableReason}
            />
          ) : (
            <section aria-labelledby="ms-chat-empty-title" className="ms-chat-empty">
              <p className="ms-chat-empty__kicker">AI SCIENTIST</p>
              <h2 id="ms-chat-empty-title">무엇을 연구해볼까요?</h2>
              <p className="ms-chat-empty__description">
                질문을 보내면 Mucha가 자료를 찾고, 검증 과정을 대화 안에 기록합니다.
              </p>
              <div aria-label="추천 연구 질문" className="ms-chat-starters">
                {STARTER_QUESTIONS.map((starter) => (
                  <button
                    key={starter}
                    onClick={() => onQuestionChange(starter)}
                    type="button"
                  >
                    {starter}
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>

        <div className="ms-chat-composer-dock">
          <ResearchComposer
            id="scientific-question"
            label="Mucha에게 연구 질문 보내기"
            helper={isBrowserPreview
              ? "미리보기에서는 대화만 기록하며 외부 수집은 실행하지 않습니다."
              : "제출하면 과학적 검증 사이클을 시작합니다. 문헌 수집은 기본 연구 대화에서 실행합니다."}
            placeholder="연구 질문을 입력하세요…"
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            onSubmit={submitQuestion}
            state={startRequested ? "loading" : "default"}
            error={conversation.visibleActionError}
            action={(
              <RuleButton
                aria-describedby="scientific-question-helper"
                disabled={!hasQuestion || Boolean(startUnavailableReason)}
                loading={startRequested}
                title={startUnavailableReason}
                type="submit"
                variant="primary"
              >
                보내기
              </RuleButton>
            )}
          />
        </div>
      </section>
    </main>
  );
}
