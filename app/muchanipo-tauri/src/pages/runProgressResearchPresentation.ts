import type { BackendEvent } from "../lib/tauriClient";
import type {
  ResearchActivity,
  ResearchPlanDisplayRow,
  ResearchQueryRoute,
  Stage,
} from "./runProgressTypes";

export function formatBenchmarkMetricLabel(key: string): string {
  if (key === "source_authority_score") return "authority";
  if (key === "weak_source_penalty") return "weak penalty";
  if (key === "expected_claim_recall") return "claim recall";
  if (key === "evidence_quote_coverage") return "quote coverage";
  if (key === "claim_traceability") return "traceability";
  return key.replaceAll("_", " ");
}

export function formatBenchmarkMetricValue(value: number): string {
  if (!Number.isFinite(value)) return "";
  return `${Math.round(value * 100)}%`;
}

function uniqueStrings(values: readonly (string | undefined)[]): string[] {
  return Array.from(
    new Set(values.map((item) => item?.trim()).filter((item): item is string => Boolean(item))),
  );
}

function queryKey(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

export function researchPlanDisplayRows(activity: ResearchActivity): ResearchPlanDisplayRow[] {
  const routesByQuery = new Map<string, ResearchQueryRoute>();
  for (const route of activity.queryRoutes ?? []) {
    const key = queryKey(route.query);
    if (key && !routesByQuery.has(key)) routesByQuery.set(key, route);
  }
  const orderedQueries = activity.queries && activity.queries.length > 0
    ? activity.queries
    : (activity.queryRoutes ?? [])
        .map((route) => route.query)
        .filter((query): query is string => Boolean(query));
  const rows = orderedQueries.map((query, index): ResearchPlanDisplayRow => {
    const route = routesByQuery.get(queryKey(query)) ?? activity.queryRoutes?.[index];
    return {
      query,
      routeDetails: [
        route?.facetId ? `facet ${route.facetId}` : undefined,
        route?.purpose ? `purpose ${route.purpose}` : undefined,
        route?.sourceClass ? `source class ${route.sourceClass}` : undefined,
        route?.intent ? `intent ${route.intent}` : undefined,
        route?.backend ? `backend ${route.backend}` : undefined,
      ].filter((item): item is string => Boolean(item)),
      continueReason: route?.continueReason,
      authorityRequirement: route?.authorityRequirement,
      acceptanceRules: route?.acceptanceRules ?? [],
    };
  });
  if (rows.length > 0) return rows;
  return (activity.query ? [activity.query] : []).map((query) => ({
    query,
    routeDetails: [],
    acceptanceRules: [],
  }));
}

export function researchPlanSummaryChips(activity: ResearchActivity): string[] {
  const rows = researchPlanDisplayRows(activity);
  const sourceClasses = uniqueStrings((activity.queryRoutes ?? []).map((route) => route.sourceClass));
  const backends = uniqueStrings((activity.queryRoutes ?? []).map((route) => route.backend));
  return [
    `queries ${activity.queryCount ?? rows.length}`,
    sourceClasses.length > 0 ? `source classes ${sourceClasses.join(", ")}` : undefined,
    backends.length > 0 ? `backends ${backends.join(", ")}` : undefined,
    activity.topicAnchor ? `topic anchor ${activity.topicAnchor}` : undefined,
  ].filter((item): item is string => Boolean(item));
}

export function researchProgressStage(
  event: BackendEvent,
  activity?: ResearchActivity | null,
): Stage {
  if (event.stage === "quality_gate") return "evidence";
  if (
    event.event === "research_quality_ready"
    || event.status === "research_quality_ready"
    || event.status === "ready_before_council"
    || event.status === "source_audit_gate"
    || event.status === "claim_evidence_gate"
    || event.status === "max_plus_benchmark_scored"
  ) return "evidence";
  if (
    activity?.status === "source_audit_gate"
    || activity?.status === "claim_evidence_gate"
    || activity?.status === "max_plus_benchmark_scored"
    || activity?.status === "research_quality_ready"
  ) return "evidence";
  return "research";
}

export function researchQualityDetailChips(activity: ResearchActivity): string[] {
  const details: string[] = [];
  if (activity.passed !== undefined) details.push(`passed ${activity.passed ? "yes" : "no"}`);
  if (activity.acceptedSourceCount !== undefined) details.push(`accepted sources ${activity.acceptedSourceCount}`);
  if (activity.rejectedSourceCount !== undefined) details.push(`rejected sources ${activity.rejectedSourceCount}`);
  if (activity.gapCount !== undefined) details.push(`gaps ${activity.gapCount}`);
  if (activity.supportedClaimCount !== undefined) details.push(`supported claims ${activity.supportedClaimCount}`);
  if (activity.partialClaimCount !== undefined) details.push(`partial claims ${activity.partialClaimCount}`);
  if (activity.unsupportedClaimCount !== undefined) {
    details.push(`unsupported claims ${activity.unsupportedClaimCount}`);
  }
  if (activity.supportedRatio !== undefined) {
    details.push(`supported ratio ${formatBenchmarkMetricValue(activity.supportedRatio)}`);
  }
  if (activity.decision) details.push(`decision ${activity.decision}`);
  return details;
}

export function researchActivityCopy(
  activity: ResearchActivity,
): { readonly label: string; readonly message: string; readonly signal: string } {
  if (activity.status === "research_plan_ready") {
    return {
      label: "Research plan ready",
      message: "Research plan prepared with query rationale",
      signal: `research_plan_ready · ${activity.queryCount ?? activity.queries?.length ?? 0} queries`,
    };
  }
  if (activity.status === "source_found") {
    return {
      label: "출처 확인",
      message: "출처 확인 중",
      signal: `source_found · ${activity.sourceTitle || "source"}`,
    };
  }
  if (activity.status === "source_evaluated") {
    return {
      label: activity.accepted === false ? "출처 거절" : "출처 채택",
      message: activity.accepted === false ? "출처 평가 · 거절/보류" : "출처 평가 · 채택",
      signal: `source_evaluated · ${activity.sourceTitle || "source"}`,
    };
  }
  if (activity.status === "knowledge_gap") {
    return {
      label: "근거 gap",
      message: "근거 부족 gap 발견",
      signal: `knowledge_gap · ${activity.facetId || "facet"}`,
    };
  }
  if (activity.status === "facet_summary") {
    return {
      label: "Facet 요약",
      message: "facet별 근거 커버리지 요약",
      signal: `facet_summary · gaps ${activity.gapCount ?? 0}`,
    };
  }
  if (activity.status === "source_audit_gate" || activity.status === "claim_evidence_gate") {
    const sourceAudit = activity.status === "source_audit_gate";
    const details = researchQualityDetailChips(activity);
    return {
      label: sourceAudit ? "출처 감사 gate" : "Claim 근거 gate",
      message:
        activity.message
        || (sourceAudit ? "출처 감사 gate 확인 중" : "claim 근거 matrix 확인 중"),
      signal: `${activity.status} · ${
        details.join(" · ") || activity.reason || activity.message || "quality gate"
      }`,
    };
  }
  if (activity.status === "max_plus_benchmark_scored") {
    const claimRecall = activity.metrics?.["expected_claim_recall"];
    const metricSignal = claimRecall !== undefined
      ? `claim recall ${formatBenchmarkMetricValue(claimRecall)}`
      : "quality gate";
    return {
      label: "Benchmark gate",
      message: activity.message || "명시 선택 benchmark fixture 평가",
      signal: `max_plus_benchmark_scored · ${
        activity.decision ? `decision ${activity.decision}` : activity.benchmarkId || metricSignal
      }`,
    };
  }
  if (activity.status === "research_quality_ready") {
    const details = researchQualityDetailChips(activity);
    return {
      label: "Research quality ready",
      message: activity.message || "Research quality-first run complete before council",
      signal: `research_quality_ready · ${activity.reason || "ready_before_council"}${
        details.length ? ` · ${details.join(" · ")}` : ""
      }`,
    };
  }
  return {
    label: activity.status === "done" ? "검색 완료" : "검색 중",
    message: activity.status === "done" ? "검색 완료" : "검색 쿼리 실행 중",
    signal: `${activity.status} · ${activity.query || "query"}`,
  };
}
