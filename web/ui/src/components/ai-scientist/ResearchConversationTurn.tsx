import type { ResearchConversationTurn as ConversationTurn } from "../../lib/researchConversation";
import type { ResearchQualityReadiness } from "../../lib/researchActivity";
import {
  formatResearchArtifactLabel,
  formatResearchDuration,
} from "../../lib/researchConversation";
import type { ResearchTurnRuntime } from "../../hooks/useResearchConversation";
import { isSafeExternalHttpUrl } from "../../lib/safeExternalUrl";
import {
  ChatMessage,
  ProcessDisclosure,
} from "./ResearchChatPrimitives";
import { RuleButton } from "./AiScientistPrimitives";
import { ResearchActivitySummary, qualityReadinessLabel } from "./ResearchActivitySummary";
import { SafeReportMarkdown } from "../SafeReportMarkdown";

interface ResearchConversationTurnProps {
  readonly now: number;
  readonly onCancel?: (turnId: string) => void;
  readonly onExport: (turnId: string) => void;
  readonly runtime?: ResearchTurnRuntime;
  readonly turn: ConversationTurn;
}

export function ResearchConversationTurn({
  now,
  onCancel,
  onExport,
  runtime,
  turn,
}: ResearchConversationTurnProps) {
  const isRunning = runtime?.status === "running";
  const isError = runtime?.status === "error";
  const activityEmptyMessage = isError
    ? "실행이 중단되었습니다."
    : runtime?.status === "canceled"
      ? "실행이 종료되었습니다."
      : runtime?.status === "complete"
        ? "기록된 실행 투영이 없습니다."
        : "실행 투영을 기다리는 중입니다.";
  const reportBody = turn.finalReport ?? turn.reportChunks.join("\n\n");
  const duration = runtime
    ? formatResearchDuration(((runtime.completedAt ?? now) - runtime.startedAt) / 1000)
    : "기록 없음";
  const activityTitle = isRunning
    ? `${duration} 동안 작업 중입니다`
    : `${duration} 동안 작업했습니다`;
  const qualityReadiness = runtime?.activity?.quality?.readiness;
  const qualityStopNotice = reportQualityStopNotice(
    qualityReadiness,
    Boolean(reportBody) && runtime?.status === "complete",
  );
  const canRenderReport = Boolean(reportBody)
    && (qualityReadiness === "ready" || qualityReadiness === "needs_review");

  return (
    <section className="ms-research-turn" id={turn.turnId}>
      <ChatMessage label="나" role="user">
        <p>{turn.prompt}</p>
      </ChatMessage>

      <div className="ms-chat-activity">
        <ProcessDisclosure
          defaultOpen={Boolean(isRunning || isError || runtime?.cancellationRequested)}
          summary={`${turn.progress.length}개 로그 · 출처 ${turn.sourceIds.length} · 산출물 ${turn.artifactIds.length}`}
          title={activityTitle}
        >
          <ResearchActivitySummary
            activity={runtime?.activity}
            cancellationRequested={runtime?.cancellationRequested}
            emptyMessage={activityEmptyMessage}
            skippedSources={runtime?.skippedSources ?? []}
          />
          <ProcessDisclosure
            className="ms-verification-records"
            summary="원시 이벤트 · 프로토콜 · 생명주기"
            title="세부 검증 기록 및 제어"
          >
            <ResearchEvidence
              turn={turn}
            />
          </ProcessDisclosure>
        </ProcessDisclosure>
      </div>

      <ChatMessage
        label="MUNI lab"
        meta={assistantMeta(runtime)}
        role="assistant"
        state={isRunning ? "loading" : isError ? "error" : "complete"}
      >
        {qualityStopNotice ? <p role="alert">{qualityStopNotice}</p> : null}
        {canRenderReport ? (
          <div className="ms-report-markdown">
            <SafeReportMarkdown markdown={reportBody} />
          </div>
        ) : qualityStopNotice ? null : (
          <p>{isError
            ? runtime?.error ?? "연구 실행을 완료하지 못했습니다. 실행 환경을 확인한 뒤 새 질문으로 다시 시도하세요."
            : runtime?.status === "canceled"
              ? "실행 종료를 확인했습니다. 종료 뒤 도착한 답변과 산출물은 반영하지 않았습니다."
              : runtime?.status === "complete"
                ? "최종 보고서를 받지 못했습니다. 저장된 검증 기록을 확인하세요."
                : "자료를 찾고 근거를 비교하고 있습니다."}</p>
        )}
        {canRenderReport ? (
          <RuleButton onClick={() => onExport(turn.turnId)} variant="text">
            연구 기록 내보내기
          </RuleButton>
        ) : null}
        {isRunning && onCancel ? (
          <RuleButton
            disabled={runtime?.cancellationRequested}
            onClick={() => onCancel(turn.turnId)}
            variant="text"
          >
            {runtime?.cancellationRequested ? "종료 확인 중" : "실행 종료"}
          </RuleButton>
        ) : null}
      </ChatMessage>
    </section>
  );
}

function ResearchEvidence({
  turn,
}: {
  readonly turn: ConversationTurn;
}) {
  return (
    <div className="ms-turn-evidence">
      {turn.progress.length > 0 ? (
        <ol className="ms-activity-log">
          {turn.progress.map((stage, index) => (
            <li key={`${stage}-${index}`}>
              <span className="ms-activity-log__marker" aria-hidden="true" />
              <span>{stage}</span>
            </li>
          ))}
        </ol>
      ) : <p>파이프라인 로그를 기다리고 있습니다.</p>}

      <EvidenceList label="근거 출처" values={turn.sourceIds} links />
      <EvidenceList
        formatValue={formatResearchArtifactLabel}
        label="산출물"
        values={turn.artifactIds}
      />

      <a className="ms-text-link" href="#/scientific/validation">
        저장된 검증 기록 열기
      </a>
    </div>
  );
}

function EvidenceList({
  formatValue,
  label,
  links = false,
  values,
}: {
  readonly formatValue?: (value: string) => string;
  readonly label: string;
  readonly links?: boolean;
  readonly values: readonly string[];
}) {
  if (values.length === 0) return null;
  return (
    <section className="ms-evidence-list">
      <h4>{label}</h4>
      <ul>
        {values.map((value) => (
          <li key={value}>
            {links && isSafeExternalHttpUrl(value)
              ? <a href={value} rel="noreferrer" target="_blank">{value}</a>
              : (
                  <span title={formatValue ? value : undefined}>
                    {formatValue?.(value) ?? value}
                  </span>
                )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function assistantMeta(runtime?: ResearchTurnRuntime): string {
  if (!runtime) return "저장된 연구";
  if (runtime.status === "running") return "연구 중";
  if (runtime.status === "error") return "실행 중단";
  if (runtime.status === "canceled") return "종료 확인";
  if (runtime.status === "preview") return "브라우저 미리보기";
  return runtime.activity?.quality ? qualityReadinessLabel(runtime.activity.quality.readiness) : "품질 판정 미확인";
}

function reportQualityStopNotice(
  readiness: ResearchQualityReadiness | undefined,
  hasUnconfirmedReport: boolean,
): string | undefined {
  if (readiness === "needs_review") {
    return "추가 검토가 필요한 보고서입니다. 검증 기록의 사유와 근거 공백을 확인하세요.";
  }
  if (readiness === "blocked") {
    return "검증 중단: 근거가 불충분해 최종 보고서를 표시하지 않습니다. 검증 기록에서 부족한 출처를 확인하고 근거를 보강한 뒤 다시 실행하세요.";
  }
  if (hasUnconfirmedReport && readiness === undefined) {
    return "검증 중단: 품질 판정을 확인하지 못해 수신한 보고서를 표시하지 않습니다. 검증 기록을 확인한 뒤 다시 실행하세요.";
  }
  return undefined;
}
