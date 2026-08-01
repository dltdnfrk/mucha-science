import { useEffect, useRef, useState, type FormEvent } from "react";
import { ResearchComposer } from "../components/ai-scientist/ResearchChatPrimitives";
import { ArrowUpIcon, StopIcon } from "../components/ai-scientist/MuchaWorkspaceIcons";
import { ResearchConversationTurn } from "../components/ai-scientist/ResearchConversationTurn";
import { ResearchInteractionCard } from "../components/ai-scientist/ResearchInteractionCard";
import type { ResearchConversationController } from "../lib/researchConversationController";

const STARTER_QUESTIONS = [
  "최근 5년간 장내 미생물과 우울증의 인과 근거를 검토해줘.",
  "해조류 기반 탄소 포집 기술의 성능과 한계를 비교해줘.",
] as const;

interface ResearchConversationPageProps {
  readonly conversation: ResearchConversationController;
  readonly runtimeLabel: string;
  readonly sourceCount: number;
}

export function ResearchConversationPage({
  conversation,
  runtimeLabel,
  sourceCount,
}: ResearchConversationPageProps) {
  const [prompt, setPrompt] = useState("");
  const [now, setNow] = useState(Date.now());
  const endRef = useRef<HTMLDivElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const shouldFollowRef = useRef(true);

  useEffect(() => {
    if (!conversation.isRunning) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [conversation.isRunning]);

  useEffect(() => {
    if (!shouldFollowRef.current) return;
    endRef.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "end",
    });
  }, [conversation.pendingInteraction, conversation.session.turns]);

  useEffect(() => {
    const keepLatestTurnVisible = () => {
      if (shouldFollowRef.current) endRef.current?.scrollIntoView({ block: "end" });
    };
    window.addEventListener("resize", keepLatestTurnVisible);
    return () => window.removeEventListener("resize", keepLatestTurnVisible);
  }, []);

  const submitPrompt = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const accepted = await conversation.submit(prompt);
    if (accepted) setPrompt("");
  };

  const hasConversation = conversation.session.turns.length > 0;
  const activeTurnId = conversation.activeTurnId
    ?? [...conversation.session.turns].reverse().find(
      (turn) => conversation.runtimeByTurn[turn.turnId]?.status === "running",
    )?.turnId;
  const activeTurn = activeTurnId
    ? conversation.session.turns.find((turn) => turn.turnId === activeTurnId)
    : undefined;
  const latestProgress = activeTurn?.progress[activeTurn.progress.length - 1];
  const cancellationRequested = activeTurnId
    ? conversation.runtimeByTurn[activeTurnId]?.cancellationRequested
    : false;

  return (
    <main className="ms-chat-workspace" aria-labelledby="research-chat-heading">
        <h1 className="ms-visually-hidden" id="research-chat-heading">
          Mucha Science 연구 대화
        </h1>
        <p className="ms-visually-hidden" role="status" aria-atomic="true" aria-live="polite">
          {conversation.isRunning
            ? latestProgress ? `연구 진행: ${latestProgress}` : "연구를 준비하고 있습니다."
            : ""}
        </p>
        <div
          className="ms-chat-thread"
          onScroll={(event) => {
            const target = event.currentTarget;
            shouldFollowRef.current = target.scrollHeight - target.scrollTop - target.clientHeight < 160;
          }}
          ref={threadRef}
          tabIndex={0}
        >
          {hasConversation ? (
            <div className="ms-chat-stream">
              {conversation.session.turns.map((turn) => (
                <ResearchConversationTurn
                  key={turn.turnId}
                  now={now}
                  onCancel={conversation.cancelTurn}
                  onExport={conversation.exportTurn}
                  runtime={conversation.runtimeByTurn[turn.turnId]}
                  turn={turn}
                />
              ))}
              {conversation.pendingInteraction ? (
                <ResearchInteractionCard
                  interaction={conversation.pendingInteraction}
                  onAnswer={conversation.answerInteraction}
                />
              ) : null}
              <div ref={endRef} />
            </div>
          ) : (
            <EmptyResearchConversation onSelect={setPrompt} />
          )}
        </div>

        <div className="ms-chat-composer-dock">
          <ResearchComposer
            action={(
              conversation.isRunning ? (
                <button
                  aria-label="현재 연구 중지"
                  className="ms-composer-action"
                  disabled={!activeTurnId || cancellationRequested}
                  onClick={() => {
                    if (activeTurnId) void conversation.cancelTurn(activeTurnId);
                  }}
                  title={cancellationRequested ? "중지 요청을 확인하고 있습니다." : "현재 연구 중지"}
                  type="button"
                >
                  <StopIcon />
                </button>
              ) : (
                <button
                  aria-label="연구 질문 보내기"
                  className="ms-composer-action"
                  disabled={!prompt.trim()}
                  title="연구 질문 보내기"
                  type="submit"
                >
                  <ArrowUpIcon />
                </button>
              )
            )}
            disabled={conversation.isRunning}
            error={conversation.composerError}
            helper={conversation.isRunning
              ? `${runtimeLabel} · ${latestProgress ?? "자료 수집과 검증을 진행하고 있습니다."}`
              : `${runtimeLabel} · 준비된 출처 ${sourceCount}개 · Enter는 줄바꿈입니다.`}
            id="research-question"
            label={hasConversation ? "후속 질문" : "연구 질문"}
            onChange={(event) => setPrompt(event.target.value)}
            onSubmit={submitPrompt}
            placeholder="무엇을 조사하고 검증할까요?"
            rows={1}
            state={conversation.isRunning ? "loading" : "default"}
            value={prompt}
          />
        </div>
    </main>
  );
}

function EmptyResearchConversation({
  onSelect,
}: {
  readonly onSelect: (prompt: string) => void;
}) {
  return (
    <section className="ms-chat-empty">
      <h2>무엇을 연구할까요?</h2>
      <p className="ms-chat-empty__description">
        질문을 입력하면 문헌을 찾고 근거와 검증 과정을 대화 안에 정리합니다.
      </p>
      <div className="ms-chat-starters" aria-label="연구 질문 예시">
        {STARTER_QUESTIONS.map((question) => (
          <button key={question} onClick={() => onSelect(question)} type="button">
            {question}
          </button>
        ))}
      </div>
    </section>
  );
}
