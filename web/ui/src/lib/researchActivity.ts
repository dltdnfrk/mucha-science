import type { ResearchRuntimeContext } from "./researchExecution";
import { toResearchProviderProjection } from "./researchProviderProjection";
import { sanitizeExternalReference } from "./safeExternalUrl";
import type { BackendEvent } from "./tauriClient";

// allow: SIZE_OK — This module owns the single typed boundary from backend research events to activity projections.
export type ResearchStance = "supports" | "refutes" | "mixed" | "inconclusive";
export type OrdinalUncertainty = "low" | "moderate" | "high" | "unknown";
export type ResearchQualityReadiness = "ready" | "needs_review" | "blocked";
export type ResearchProcessCompleteness = "complete" | "partial" | "blocked";

export type ResearchActivityProjection =
  | {
      readonly kind: "provider";
      readonly attemptId: string;
      readonly provider: string;
      readonly providerKind: "model" | "academic_source";
      readonly routeId: string;
      readonly outcome: "success" | "empty" | "failed";
      readonly count: number;
      readonly failure?: string;
    }
  | {
      readonly kind: "route";
      readonly routeId: string;
      readonly outcome: "success" | "empty" | "failed" | "partial";
      readonly count: number;
    }
  | {
      readonly kind: "evidence";
      readonly accepted: boolean;
      readonly citationId: string;
      readonly locator: string;
      readonly sourceId: string;
      readonly title?: string;
    }
  | {
      readonly kind: "source_counts";
      readonly acceptedCount: number;
      readonly candidateCount: number;
    }
  | {
      readonly kind: "claim";
      readonly claim: string;
      readonly claimId: string;
      readonly stance: ResearchStance;
      readonly uncertainty: OrdinalUncertainty;
    }
  | {
      readonly kind: "quality";
      readonly processCompleteness?: ResearchProcessCompleteness;
      readonly readiness: ResearchQualityReadiness;
      readonly reasons: readonly string[];
    }
  | {
      readonly kind: "counter_started";
      readonly batchSize: number;
    }
  | { readonly kind: "counter_executed" }
  | { readonly kind: "counter_evaluated" }
  | {
      readonly kind: "counter_completed";
      readonly noNovelty: boolean;
      readonly stopReason: string;
    }
  | { readonly kind: "cancellation_acknowledged" };

export type ResearchCounterSearch = {
  readonly batchSize: number;
  readonly evaluated: number;
  readonly executed: number;
  readonly noNovelty: boolean;
  readonly status: "running" | "completed";
  readonly stopReason?: string;
};

export type ResearchActivity = {
  readonly cancellationAcknowledged: boolean;
  readonly claims: readonly Extract<ResearchActivityProjection, { kind: "claim" }>[];
  readonly counterSearch?: ResearchCounterSearch;
  readonly evidence: readonly Extract<ResearchActivityProjection, { kind: "evidence" }>[];
  readonly providers: readonly Extract<ResearchActivityProjection, { kind: "provider" }>[];
  readonly quality?: Extract<ResearchActivityProjection, { kind: "quality" }>;
  readonly routes: readonly Extract<ResearchActivityProjection, { kind: "route" }>[];
  readonly sourceCounts?: {
    readonly acceptedCount: number;
    readonly candidateCount: number;
  };
};

export function emptyResearchActivity(): ResearchActivity {
  return {
    cancellationAcknowledged: false,
    claims: [],
    evidence: [],
    providers: [],
    routes: [],
  };
}

export function sanitizeResearchActivityReferences(
  activity: ResearchActivity,
): ResearchActivity {
  return {
    ...activity,
    evidence: activity.evidence.map((item) => ({
      ...item,
      citationId: sanitizeExternalReference(item.citationId),
      locator: sanitizeExternalReference(item.locator),
      sourceId: sanitizeExternalReference(item.sourceId),
    })),
  };
}

export function toResearchActivityProjections(
  event: BackendEvent,
  context: ResearchRuntimeContext,
): readonly ResearchActivityProjection[] {
  if (!isCurrent(event, context)) return [];
  if (event.event === "execution_cancelled") {
    return event["termination_observed"] === true && event["reaped"] === true
      ? [{ kind: "cancellation_acknowledged" }]
      : [];
  }
  if (
    event.event === "done"
    || event.event === "research_quality_ready"
    || event.event === "research_quality_needs_review"
  ) {
    return optionalProjection(qualityProjection(event));
  }
  if (event.event === "provider_attempt" || event.event === "academic_route_summary") {
    return providerProjections(event);
  }
  if (event.event !== "research_progress") return [];
  switch (event["status"]) {
    case "source_decision":
      return optionalProjection(evidenceProjection(event));
    case "source_decision_ledger_built":
      return optionalProjection(sourceCountsProjection(event));
    case "claim_evidence_gate":
      return claimProjections(event["rows"]);
    case "refutation_pass_started":
      return optionalProjection(counterStarted(event["task_count"]));
    case "refutation_query_executed":
      return [{ kind: "counter_executed" }];
    case "refutation_source_evaluated":
      return [{ kind: "counter_evaluated" }];
    case "refutation_pass_completed":
      return optionalProjection(counterCompleted(event["reason"]));
    default:
      return [];
  }
}

function sourceCountsProjection(
  event: BackendEvent,
): Extract<ResearchActivityProjection, { kind: "source_counts" }> | undefined {
  const acceptedCount = event["accepted_count"];
  const candidateCount = event["decision_count"];
  if (!isNonNegativeInteger(acceptedCount) || !isNonNegativeInteger(candidateCount)) {
    return undefined;
  }
  return { kind: "source_counts", acceptedCount, candidateCount };
}

function providerProjections(event: BackendEvent): readonly ResearchActivityProjection[] {
  if (event["schema_version"] !== "research-event.v1") return [];
  const projection = toResearchProviderProjection(event);
  if (!projection) return [];
  if (projection.kind === "academic_route_summary") {
    return [{
      count: projection.count,
      kind: "route",
      outcome: projection.outcome,
      routeId: projection.routeId,
    }];
  }
  return [{
    attemptId: projection.attemptId,
    count: projection.count,
    ...(projection.failure ? { failure: projection.failure.message } : {}),
    kind: "provider",
    outcome: projection.outcome,
    provider: projection.provider,
    providerKind: projection.kind === "model_attempt" ? "model" : "academic_source",
    routeId: projection.routeId,
  }];
}

function evidenceProjection(
  event: BackendEvent,
): Extract<ResearchActivityProjection, { kind: "evidence" }> | undefined {
  const sourceId = requiredText(event["source_id"]);
  const citationId = requiredText(event["canonical_id"]) ?? sourceId;
  const locator = requiredText(event["canonical_url"]) ?? requiredText(event["source_url"]);
  const accepted = event["accepted"];
  const title = requiredText(event["source_title"]);
  if (!sourceId || !citationId || !locator || typeof accepted !== "boolean") return undefined;
  return {
    accepted,
    citationId: sanitizeExternalReference(citationId),
    kind: "evidence",
    locator: sanitizeExternalReference(locator),
    sourceId: sanitizeExternalReference(sourceId),
    ...(title ? { title } : {}),
  };
}

function qualityProjection(
  event: BackendEvent,
): Extract<ResearchActivityProjection, { kind: "quality" }> | undefined {
  const readiness = readQualityReadiness(event["research_quality_readiness"]);
  const reasons = readReasons(event["research_readiness_reasons"]);
  const rawProcessCompleteness = event["research_process_completeness"];
  const processCompleteness = readProcessCompleteness(rawProcessCompleteness);
  if (
    !readiness
    || !reasons
    || (rawProcessCompleteness !== undefined && !processCompleteness)
    || !matchesQualityEvent(event.event, readiness)
  ) return undefined;
  return {
    kind: "quality",
    ...(processCompleteness ? { processCompleteness } : {}),
    readiness,
    reasons,
  };
}

function claimProjections(value: unknown): readonly ResearchActivityProjection[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((row) => optionalProjection(claimProjection(row)));
}

function claimProjection(
  value: unknown,
): Extract<ResearchActivityProjection, { kind: "claim" }> | undefined {
  if (!isRecord(value)) return undefined;
  const claimId = requiredText(value["claim_id"]);
  const claim = requiredText(value["claim"]);
  const stance = readStance(value["stance"]);
  const uncertainty = readUncertainty(value["uncertainty"]);
  return claimId && claim && stance
    ? { claim, claimId, kind: "claim", stance, uncertainty }
    : undefined;
}

function counterStarted(
  value: unknown,
): Extract<ResearchActivityProjection, { kind: "counter_started" }> | undefined {
  return isNonNegativeInteger(value) ? { batchSize: value, kind: "counter_started" } : undefined;
}

function counterCompleted(
  value: unknown,
): Extract<ResearchActivityProjection, { kind: "counter_completed" }> | undefined {
  const stopReason = requiredText(value);
  return stopReason
    ? {
        kind: "counter_completed",
        noNovelty: stopReason === "completed all assessed with no novelty",
        stopReason,
      }
    : undefined;
}

function optionalProjection(
  value: ResearchActivityProjection | undefined,
): readonly ResearchActivityProjection[] {
  return value ? [value] : [];
}

function readStance(value: unknown): ResearchStance | undefined {
  if (value === "supports_claim") return "supports";
  if (value === "refutes_claim") return "refutes";
  return value === "mixed" || value === "inconclusive" ? value : undefined;
}

function readUncertainty(value: unknown): OrdinalUncertainty {
  return value === "low" || value === "moderate" || value === "high" ? value : "unknown";
}

function readQualityReadiness(value: unknown): ResearchQualityReadiness | undefined {
  return value === "ready" || value === "needs_review" || value === "blocked" ? value : undefined;
}

function readProcessCompleteness(value: unknown): ResearchProcessCompleteness | undefined {
  if (!isRecord(value)) return undefined;
  const readiness = value["readiness"];
  return readiness === "complete" || readiness === "partial" || readiness === "blocked"
    ? readiness
    : undefined;
}

function readReasons(value: unknown): readonly string[] | undefined {
  if (value === undefined) return [];
  if (!Array.isArray(value)) return undefined;
  return value.flatMap((reason) => {
    const text = requiredText(reason);
    return text ? [text] : [];
  });
}

function matchesQualityEvent(eventName: string, readiness: ResearchQualityReadiness): boolean {
  if (eventName === "done") return true;
  return eventName === "research_quality_ready"
    ? readiness === "ready"
    : eventName === "research_quality_needs_review" && readiness !== "ready";
}

function isCurrent(event: BackendEvent, context: ResearchRuntimeContext): boolean {
  return requiredText(event["app_run_id"]) === context.runId
    && event["generation"] === context.generation;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function requiredText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
