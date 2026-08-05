import type { ResearchActivity } from "../../lib/researchRuntime";
import type { SkippedSource } from "../../lib/sourceConnections";
import { isSafeExternalHttpUrl } from "../../lib/safeExternalUrl";

interface ResearchActivitySummaryProps {
  readonly activity?: ResearchActivity;
  readonly cancellationRequested?: boolean;
  readonly emptyMessage?: string;
  readonly skippedSources: readonly SkippedSource[];
}

export function ResearchActivitySummary({
  activity,
  cancellationRequested = false,
  emptyMessage = "실행 투영을 기다리는 중입니다.",
  skippedSources,
}: ResearchActivitySummaryProps) {
  const hasProjection = Boolean(
    activity
    && (
      activity.providers.length
      || activity.routes.length
      || activity.evidence.length
      || activity.sourceCounts
      || activity.claims.length
      || activity.quality
      || activity.counterSearch
      || activity.cancellationAcknowledged
    ),
  );
  return (
    <div aria-live="polite" className="ms-activity-projection" role="status">
      {!hasProjection && skippedSources.length === 0 && !cancellationRequested
        ? <p>{emptyMessage}</p>
        : null}
      {activity?.providers.length ? (
        <ActivityGroup label="제공자 실행">
          {activity.providers.map((provider) => (
            <li key={provider.attemptId}>
              <strong>{provider.provider}</strong>
              <span>{provider.routeId} · {outcomeLabel(provider.outcome)} · {provider.count}건</span>
              {provider.failure ? <small>제공자 응답을 받지 못했습니다.</small> : null}
            </li>
          ))}
        </ActivityGroup>
      ) : null}
      {activity?.routes.length ? (
        <ActivityGroup label="검색 경로">
          {activity.routes.map((route) => (
            <li key={route.routeId}>
              <strong>{route.routeId}</strong>
              <span>{outcomeLabel(route.outcome)} · {route.count}건</span>
            </li>
          ))}
        </ActivityGroup>
      ) : null}
      {activity?.sourceCounts || activity?.evidence.length ? (
        <ActivityGroup label="근거 위치와 인용">
          {activity.sourceCounts ? (
            <li
              data-accepted-count={activity.sourceCounts.acceptedCount}
              data-candidate-count={activity.sourceCounts.candidateCount}
            >
              <strong>후보 {activity.sourceCounts.candidateCount}</strong>
              <span>채택 {activity.sourceCounts.acceptedCount}</span>
            </li>
          ) : null}
          {activity.evidence.map((evidence) => (
            <li key={evidence.sourceId}>
              <strong>{evidence.citationId}</strong>
              {isSafeExternalHttpUrl(evidence.locator) ? (
                <a href={evidence.locator} rel="noreferrer" target="_blank">
                  {evidence.title ?? evidence.locator}
                </a>
              ) : <span>{evidence.title ?? evidence.locator}</span>}
              <span>{evidence.accepted ? "채택" : "제외"}</span>
            </li>
          ))}
        </ActivityGroup>
      ) : null}
      {activity?.claims.length ? (
        <ActivityGroup label="주장 판정">
          {activity.claims.map((claim) => (
            <li key={claim.claimId}>
              <strong>{researchClaimLabel(claim.claim)}</strong>
              <span>{stanceLabel(claim.stance)} · 불확실성 {uncertaintyLabel(claim.uncertainty)}</span>
            </li>
          ))}
        </ActivityGroup>
      ) : null}
      {activity?.quality ? (
        <section className="ms-activity-projection__group">
          <h4>근거 검증</h4>
          <p>
            <strong>{qualityReadinessLabel(activity.quality.readiness)}</strong>
            {activity.quality.processCompleteness
              ? ` · 과정 기록 ${processCompletenessLabel(activity.quality.processCompleteness)}`
              : ""}
          </p>
          {activity.quality.reasons.length ? (
            <ul>
              {[...new Set(activity.quality.reasons.map(qualityReasonLabel))]
                .map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          ) : null}
        </section>
      ) : null}
      {activity?.counterSearch ? (
        <section className="ms-activity-projection__counter">
          <h4>반증 검색</h4>
          <p>
            반증 검색 {activity.counterSearch.evaluated}/{activity.counterSearch.batchSize}
            {" · "}질의 {activity.counterSearch.executed}건
            {" · "}{activity.counterSearch.status === "completed" ? "완료" : "진행 중"}
          </p>
          {activity.counterSearch.noNovelty ? <p>새 근거 없음</p> : null}
          {activity.counterSearch.stopReason ? (
            <p>
              <strong>중단 사유</strong>
              {" · "}{counterStopReasonLabel(activity.counterSearch.stopReason)}
            </p>
          ) : null}
        </section>
      ) : null}
      {skippedSources.length ? (
        <ActivityGroup label="실행하지 않은 출처">
          {skippedSources.map((source) => (
            <li key={source.id}>
              <strong>{source.name}</strong>
              <span>{source.reason}</span>
            </li>
          ))}
        </ActivityGroup>
      ) : null}
      {cancellationRequested && !activity?.cancellationAcknowledged
        ? <p className="ms-activity-projection__notice">종료 확인 중</p>
        : null}
      {activity?.cancellationAcknowledged
        ? <p className="ms-activity-projection__notice">실행 종료 확인됨</p>
        : null}
    </div>
  );
}

function ActivityGroup({
  children,
  label,
}: {
  readonly children: React.ReactNode;
  readonly label: string;
}) {
  return (
    <section className="ms-activity-projection__group">
      <h4>{label}</h4>
      <ul>{children}</ul>
    </section>
  );
}

function outcomeLabel(outcome: "success" | "empty" | "failed" | "partial"): string {
  switch (outcome) {
    case "success": return "성공";
    case "empty": return "결과 없음";
    case "failed": return "실패";
    case "partial": return "부분 성공";
  }
}

function stanceLabel(stance: "supports" | "refutes" | "mixed" | "inconclusive"): string {
  switch (stance) {
    case "supports": return "지지";
    case "refutes": return "반박";
    case "mixed": return "혼합";
    case "inconclusive": return "결론 불충분";
  }
}

function uncertaintyLabel(uncertainty: "low" | "moderate" | "high" | "unknown"): string {
  switch (uncertainty) {
    case "low": return "낮음";
    case "moderate": return "보통";
    case "high": return "높음";
    case "unknown": return "미확인";
  }
}

export function qualityReadinessLabel(readiness: "ready" | "needs_review" | "blocked"): string {
  switch (readiness) {
    case "ready": return "근거 검증 완료";
    case "needs_review": return "검토 필요";
    case "blocked": return "근거 불충분";
  }
}

function processCompletenessLabel(readiness: "complete" | "partial" | "blocked"): string {
  switch (readiness) {
    case "complete": return "완료";
    case "partial": return "부분 확인";
    case "blocked": return "차단";
  }
}

export function qualityReasonLabel(reason: string): string {
  const unresolvedCount = diagnosticCount(
    reason,
    "source_decision_summary.blocking_unresolved_canonical_count=",
  );
  if (unresolvedCount !== undefined) return `확인되지 않은 필수 출처 ${unresolvedCount}건`;
  const reviewCount = diagnosticCount(
    reason,
    "source_decision_summary.needs_review_count=",
  );
  if (reviewCount !== undefined) return `사람이 검토해야 할 출처 ${reviewCount}건`;
  switch (reason) {
    case "claim_evidence_summary.passed=false":
      return "주장과 근거의 연결을 추가로 검토해야 합니다.";
    case "evidence_ledger_readiness=needs_review":
      return "근거 장부 검토 필요";
    case "refutation_loop_readiness=needs_review":
      return "반증 검색 검토 필요";
    case "refutation_loop_summary.stop_allowed=false":
      return "반증 검색 종료 조건을 충족하지 못했습니다.";
    default:
      return /[가-힣]/u.test(reason) && !reason.includes("=")
        ? reason
        : "추가 검토가 필요한 검증 항목이 있습니다.";
  }
}

function diagnosticCount(reason: string, prefix: string): number | undefined {
  if (!reason.startsWith(prefix)) return undefined;
  const value = Number(reason.slice(prefix.length));
  return Number.isInteger(value) && value >= 0 ? value : undefined;
}

function counterStopReasonLabel(reason: string): string {
  switch (reason) {
    case "completed all assessed with no novelty":
      return "평가한 모든 주장에 새 근거가 없어 종료했습니다.";
    case "counter-search requires review":
      return "반증 검색 결과를 검토해야 합니다.";
    case "no_refutation_tasks":
      return "반증 검색이 필요한 주장이 없어 종료했습니다.";
    default:
      return "상세 검토가 필요한 사유로 종료했습니다.";
  }
}

function researchClaimLabel(claim: string): string {
  return claim
    .replace("Initial research direction for:", "초기 연구 방향:")
    .replaceAll("counter evidence limitations", "반증 근거와 한계")
    .replaceAll("failure cases", "실패 사례")
    .replaceAll("recent advances", "최근 연구 동향")
    .replaceAll(" review", " 검토");
}
