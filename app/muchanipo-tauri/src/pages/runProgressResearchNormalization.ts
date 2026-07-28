import type { BackendEvent } from "../lib/tauriClient";
import {
  optionalBoolean,
  optionalNumber,
  parseEventBoolean,
  parseJsonRecord,
  parseStringArray,
  safeJsonParse,
} from "./runProgressEventValues";
import type { ResearchActivity, ResearchQueryRoute } from "./runProgressTypes";

const RESEARCH_ACTIVITY_STATUSES: readonly ResearchActivity["status"][] = [
  "research_plan_ready",
  "searching",
  "source_found",
  "source_evaluated",
  "knowledge_gap",
  "facet_summary",
  "source_audit_gate",
  "claim_evidence_gate",
  "max_plus_benchmark_scored",
  "research_quality_ready",
  "done",
];

function isResearchActivityStatus(value: string): value is ResearchActivity["status"] {
  return RESEARCH_ACTIVITY_STATUSES.some((status) => status === value);
}

function normalizeResearchQueryRoute(value: unknown): ResearchQueryRoute | null {
  const record = parseJsonRecord(value);
  if (Object.keys(record).length === 0) return null;
  const rawAcceptanceRules = record["acceptance_rules"] ?? record["acceptanceRules"];
  const fallbackAcceptanceRule = String(rawAcceptanceRules ?? "").trim();
  const route: ResearchQueryRoute = {
    query: String(record["query"] ?? "").trim() || undefined,
    facetId: String(record["facet_id"] ?? record["facetId"] ?? "").trim() || undefined,
    purpose: String(record["purpose"] ?? "").trim() || undefined,
    sourceClass: String(record["source_class"] ?? record["sourceClass"] ?? "").trim() || undefined,
    intent: String(record["intent"] ?? "").trim() || undefined,
    backend: String(record["backend"] ?? "").trim() || undefined,
    continueReason: String(record["continue_reason"] ?? record["continueReason"] ?? "").trim() || undefined,
    authorityRequirement:
      String(record["authority_requirement"] ?? record["authorityRequirement"] ?? "").trim() || undefined,
    acceptanceRules:
      parseStringArray(rawAcceptanceRules) ?? (fallbackAcceptanceRule ? [fallbackAcceptanceRule] : undefined),
  };
  return Object.values(route).some(Boolean) ? route : null;
}

function normalizeResearchQueryRoutes(value: unknown): ResearchQueryRoute[] | undefined {
  const raw = typeof value === "string" ? safeJsonParse(value) : value;
  if (!Array.isArray(raw)) return undefined;
  const routes = raw
    .map(normalizeResearchQueryRoute)
    .filter((item): item is ResearchQueryRoute => item !== null);
  return routes.length > 0 ? routes : undefined;
}

export function normalizeResearchActivity(event: BackendEvent): ResearchActivity | null {
  if (event.event !== "research_progress") return null;
  const status = String(event.status ?? "searching");
  if (!isResearchActivityStatus(status)) return null;
  const query = String(event.query ?? "").trim();
  const sourceTitle = String(event.source_title ?? "").trim();
  const sourceUrl = String(event.source_url ?? "").trim();
  const facetId = String(event.facet_id ?? "").trim();
  const reason = String(event.reason ?? "").trim();
  const queryIndex = Number(event.query_index ?? 0) || undefined;
  const relevanceScore = Number(event.relevance_score ?? Number.NaN);
  const rawAcceptanceRules = event.acceptance_rules ?? event.acceptanceRules;
  const rawMetrics = parseJsonRecord(event.metrics);
  const metrics = Object.keys(rawMetrics).length > 0
    ? Object.fromEntries(
        Object.entries(rawMetrics)
          .map(([key, value]) => [key, Number(value)])
          .filter(([, value]) => Number.isFinite(value)),
      )
    : undefined;
  return {
    id: [status, queryIndex ?? "", query, sourceTitle, sourceUrl, facetId, reason].join("|"),
    status,
    query: query || undefined,
    queryIndex,
    queryCount: Number(event.query_count ?? 0) || undefined,
    backends: parseStringArray(event.backends),
    sourceTitle: sourceTitle || undefined,
    sourceUrl: sourceUrl || undefined,
    sourceGrade: String(event.source_grade ?? "").trim() || undefined,
    sourceKind: String(event.source_kind ?? "").trim() || undefined,
    accessStatus: String(event.access_status ?? "").trim() || undefined,
    accepted: typeof event.accepted === "boolean" ? event.accepted : undefined,
    facetIds: parseStringArray(event.facet_ids),
    relevanceScore: Number.isFinite(relevanceScore) ? relevanceScore : undefined,
    reason: reason || undefined,
    facetId: facetId || undefined,
    message: String(event.message ?? "").trim() || undefined,
    acceptedCount: optionalNumber(event.accepted_count),
    minAcceptedSources: optionalNumber(event.min_accepted_sources),
    gapCount: optionalNumber(event.gap_count),
    acceptedSourceCount: optionalNumber(event.accepted_source_count),
    rejectedSourceCount: optionalNumber(event.rejected_source_count),
    passed: optionalBoolean(event.passed),
    decision: String(event.decision ?? "").trim() || undefined,
    supportedClaimCount: optionalNumber(event.supported_claim_count ?? event.supported_count),
    partialClaimCount: optionalNumber(event.partial_claim_count ?? event.partial_count),
    unsupportedClaimCount: optionalNumber(event.unsupported_claim_count ?? event.unsupported_count),
    supportedRatio: optionalNumber(event.supported_ratio),
    benchmarkId: String(event.benchmark_id ?? "").trim() || undefined,
    metrics,
    queries: parseStringArray(event.queries),
    queryRoutes: normalizeResearchQueryRoutes(event.query_routes),
    topicAnchor: String(event.topic_anchor ?? event.topicAnchor ?? "").trim() || undefined,
    purpose: String(event.purpose ?? "").trim() || undefined,
    sourceClass: String(event.source_class ?? event.sourceClass ?? "").trim() || undefined,
    intent: String(event.intent ?? "").trim() || undefined,
    backend: String(event.backend ?? "").trim() || undefined,
    continueReason: String(event.continue_reason ?? event.continueReason ?? "").trim() || undefined,
    authorityRequirement:
      String(event.authority_requirement ?? event.authorityRequirement ?? "").trim() || undefined,
    acceptanceRules:
      parseStringArray(rawAcceptanceRules)
      ?? (String(rawAcceptanceRules ?? "").trim() ? [String(rawAcceptanceRules).trim()] : undefined),
  };
}

export function normalizeResearchQualityReadyActivity(event: BackendEvent): ResearchActivity | null {
  const isReadyEvent = event.event === "research_quality_ready";
  const isReadyDone =
    event.event === "done"
    && (event.status === "research_quality_ready" || parseEventBoolean(event.research_quality_only));
  if (!isReadyEvent && !isReadyDone) return null;
  const artifacts = parseJsonRecord(event.artifacts);
  const eventSourceAudit = parseJsonRecord(event.source_audit_summary);
  const sourceAudit = eventSourceAudit["accepted_source_count"] !== undefined
    ? eventSourceAudit
    : parseJsonRecord(artifacts["source_audit_summary"]);
  const eventClaimEvidence = parseJsonRecord(event.claim_evidence_matrix_summary);
  const claimEvidence = eventClaimEvidence["supported_count"] !== undefined
    ? eventClaimEvidence
    : parseJsonRecord(artifacts["claim_evidence_matrix_summary"]);
  const metricsValue = parseJsonRecord(
    event.max_plus_benchmark_metrics ?? artifacts["max_plus_benchmark_metrics"],
  );
  const stop = String(event.research_quality_stop ?? event.status ?? "ready_before_council").trim();
  return {
    id: `research_quality_ready|${stop}`,
    status: "research_quality_ready",
    message: "Research quality-first run complete before council",
    reason: stop,
    acceptedSourceCount: optionalNumber(sourceAudit["accepted_source_count"]),
    rejectedSourceCount: optionalNumber(sourceAudit["rejected_source_count"]),
    gapCount: optionalNumber(sourceAudit["gap_count"]),
    passed: optionalBoolean(sourceAudit["passed"]),
    decision:
      String(event.max_plus_benchmark_decision ?? artifacts["max_plus_benchmark_decision"] ?? "").trim()
      || undefined,
    supportedClaimCount: optionalNumber(
      claimEvidence["supported_claim_count"] ?? claimEvidence["supported_count"],
    ),
    partialClaimCount: optionalNumber(
      claimEvidence["partial_claim_count"] ?? claimEvidence["partial_count"],
    ),
    unsupportedClaimCount: optionalNumber(
      claimEvidence["unsupported_claim_count"] ?? claimEvidence["unsupported_count"],
    ),
    supportedRatio: optionalNumber(claimEvidence["supported_ratio"]),
    metrics: Object.keys(metricsValue).length > 0
      ? Object.fromEntries(
          Object.entries(metricsValue)
            .map(([key, value]) => [key, Number(value)])
            .filter(([, value]) => Number.isFinite(value)),
        )
      : undefined,
  };
}
