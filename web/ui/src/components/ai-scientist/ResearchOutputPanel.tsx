import type { ResearchConversationController } from "../../lib/researchConversationController";
import type { SourceConnectionsState } from "../../hooks/useSourceConnections";
import { AiScientistValidationWorkspace } from "../../pages/AiScientistValidationWorkspace";
import { SourceConnectionsPage } from "../../pages/SourceConnectionsPage";
import {
  qualityReadinessLabel,
  qualityReasonLabel,
} from "./ResearchActivitySummary";
import { CloseIcon } from "./MuchaWorkspaceIcons";

export type ResearchOutputPanelMode = "summary" | "sources" | "validation";

interface ResearchOutputPanelProps {
  readonly conversation: ResearchConversationController;
  readonly mode: ResearchOutputPanelMode;
  readonly onClose: () => void;
  readonly sourceConnections: SourceConnectionsState;
}

export function ResearchOutputPanel({
  conversation,
  mode,
  onClose,
  sourceConnections,
}: ResearchOutputPanelProps) {
  return (
    <aside className="ms-output-panel" aria-label={panelAriaLabel(mode)}>
      <header className="ms-output-panel__header">
        <div>
          <h2>출력</h2>
          <p>{panelContext(mode)}</p>
        </div>
        <button aria-label="연구 출력 패널 닫기" onClick={onClose} type="button">
          <CloseIcon />
        </button>
      </header>
      <div className="ms-output-panel__body">
        {mode === "summary" ? (
          <ResearchOutputSummary
            conversation={conversation}
            sourceConnections={sourceConnections}
          />
        ) : null}
        {mode === "sources" ? (
          <SourceConnectionsPage compact sourceConnections={sourceConnections} />
        ) : null}
        {mode === "validation" ? (
          <AiScientistValidationWorkspace compact conversation={conversation} />
        ) : null}
      </div>
    </aside>
  );
}

function ResearchOutputSummary({
  conversation,
  sourceConnections,
}: {
  readonly conversation: ResearchConversationController;
  readonly sourceConnections: SourceConnectionsState;
}) {
  const turns = conversation.session.turns;
  const latestTurn = turns[turns.length - 1];
  const runtime = latestTurn ? conversation.runtimeByTurn[latestTurn.turnId] : undefined;
  const quality = runtime?.activity?.quality;
  const reasons = quality
    ? [...new Set(quality.reasons.map(qualityReasonLabel))]
    : [];

  return (
    <div className="ms-output-summary">
      <section>
        <h3>현재 작업</h3>
        <dl>
          <div><dt>상태</dt><dd>{runtimeStatusLabel(runtime?.status)}</dd></div>
          <div><dt>출처 준비</dt><dd>{sourceConnections.connectedSources.length}개</dd></div>
          <div><dt>연구 턴</dt><dd>{turns.length}개</dd></div>
        </dl>
      </section>

      {latestTurn ? (
        <section>
          <h3>최근 연구</h3>
          <p className="ms-output-summary__prompt">{latestTurn.prompt}</p>
          <dl>
            <div><dt>작업 로그</dt><dd>{latestTurn.progress.length}개</dd></div>
            <div><dt>근거 출처</dt><dd>{latestTurn.sourceIds.length}개</dd></div>
            <div><dt>산출물</dt><dd>{latestTurn.artifactIds.length}개</dd></div>
          </dl>
        </section>
      ) : (
        <section className="ms-output-summary__empty">
          <h3>출력</h3>
          <p>연구를 시작하면 근거, 산출물, 품질 판정이 이곳에 정리됩니다.</p>
        </section>
      )}

      <section>
        <h3>품질 판정</h3>
        <p className="ms-output-summary__readiness">
          {quality ? qualityReadinessLabel(quality.readiness) : "품질 판정 미확인"}
        </p>
        {reasons.length ? (
          <ul>{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        ) : (
          <p>아직 서버가 품질 판정 사유를 기록하지 않았습니다.</p>
        )}
      </section>

      <section>
        <h3>연결된 출처</h3>
        <ul className="ms-output-summary__sources">
          {sourceConnections.connectedSources.slice(0, 6).map((source) => (
            <li key={source.id}><span aria-hidden="true" />{source.name}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function panelContext(mode: ResearchOutputPanelMode): string {
  if (mode === "sources") return "출처 설정";
  if (mode === "validation") return "검증 기록";
  return "근거와 산출물";
}

function panelAriaLabel(mode: ResearchOutputPanelMode): string {
  if (mode === "sources") return "연구 출처 설정";
  if (mode === "validation") return "연구 검증 기록";
  return "연구 출력";
}

function runtimeStatusLabel(
  status: ResearchConversationController["runtimeByTurn"][string]["status"] | undefined,
): string {
  switch (status) {
    case "running": return "작업 중";
    case "complete": return "작업 완료";
    case "error": return "실행 중단";
    case "canceled": return "종료 확인";
    case "resumable": return "승인 대기";
    case "preview": return "브라우저 미리보기";
    case undefined: return "대기 중";
  }
}
