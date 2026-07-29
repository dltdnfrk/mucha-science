import "../styles/ai-scientist-research.css";
import { Link } from "react-router-dom";
import {
  qualityReadinessLabel,
  qualityReasonLabel,
} from "../components/ai-scientist/ResearchActivitySummary";
import type { ResearchConversationController } from "../lib/researchConversationController";

interface AiScientistValidationWorkspaceProps {
  readonly compact?: boolean;
  readonly conversation: ResearchConversationController;
}

export function AiScientistValidationWorkspace({
  compact = false,
  conversation,
}: AiScientistValidationWorkspaceProps) {
  const turns = conversation.session.turns;

  return (
    <section
      className={compact
        ? "ms-validation-workspace ms-validation-workspace--compact"
        : "ms-validation-workspace"}
      data-ai-scientist-validation
      aria-labelledby="validation-ledger-heading"
    >
      <header className="ms-validation-ledger__header">
        <div>
          <p className="ms-validation-ledger__kicker">VALIDATION LEDGER</p>
          <h1 id="validation-ledger-heading">검증 기록</h1>
          <p>
            단계별 세부 내용은 각 대화의 “N초 동안 작업” 기록에 접어 두었습니다. 이 화면은
            품질 판정만 요약하며 최종 보고서를 대신하지 않습니다.
          </p>
        </div>
        {compact ? null : (
          <Link className="ms-text-link" to="/scientific">연구 대화로 돌아가기</Link>
        )}
      </header>

      {turns.length === 0 ? (
        <section className="ms-validation-ledger__empty" aria-labelledby="validation-empty-heading">
          <h2 id="validation-empty-heading">아직 검증 기록이 없습니다.</h2>
          <p>연구 대화에서 질문을 시작하면 턴별 품질 판정이 여기에 쌓입니다.</p>
        </section>
      ) : (
        <ol className="ms-validation-ledger__records">
          {turns.map((turn, index) => {
            const runtime = conversation.runtimeByTurn[turn.turnId];
            const quality = runtime?.activity?.quality;
            const recordHeadingId = `validation-record-${turn.turnId}`;
            return (
              <li key={turn.turnId}>
                <article aria-labelledby={recordHeadingId}>
                  <header>
                    <p>기록 {index + 1}</p>
                    <h2 id={recordHeadingId}>{turn.prompt}</h2>
                  </header>
                  <dl>
                    <div>
                      <dt>작업 상태</dt>
                      <dd>{runtimeStatusLabel(runtime?.status)}</dd>
                    </div>
                    <div>
                      <dt>품질 준비</dt>
                      <dd>{quality ? qualityReadinessLabel(quality.readiness) : "품질 판정 미확인"}</dd>
                    </div>
                    <div>
                      <dt>판정 사유</dt>
                      <dd>{quality?.reasons.length ? (
                        <ul>
                          {[...new Set(quality.reasons.map(qualityReasonLabel))]
                            .map((reason) => <li key={reason}>{reason}</li>)}
                        </ul>
                      ) : "품질 판정 사유가 기록되지 않았습니다."}</dd>
                    </div>
                  </dl>
                </article>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function runtimeStatusLabel(status: ResearchConversationController["runtimeByTurn"][string]["status"] | undefined): string {
  switch (status) {
    case "running": return "작업 중";
    case "complete": return "작업 완료";
    case "error": return "실행 중단";
    case "canceled": return "종료 확인";
    case "preview": return "브라우저 미리보기";
    case undefined: return "기록 없음";
  }
}
