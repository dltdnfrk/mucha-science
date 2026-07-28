import type { BackendEvent } from "./tauriClient";
import type {
  AcademicRouteOutcome,
  ResearchProviderAttemptOutcome,
  ResearchProviderFailure,
} from "./types";

export type ResearchProviderProjection =
  | {
      readonly kind: "model_attempt" | "academic_attempt";
      readonly attemptId: string;
      readonly routeId: string;
      readonly provider: string;
      readonly outcome: ResearchProviderAttemptOutcome;
      readonly count: number;
      readonly failure?: ResearchProviderFailure;
    }
  | {
      readonly kind: "academic_route_summary";
      readonly routeId: string;
      readonly attemptIds: readonly string[];
      readonly outcome: AcademicRouteOutcome;
      readonly count: number;
    };

export function toResearchProviderProjection(
  event: BackendEvent,
): ResearchProviderProjection | undefined {
  switch (event.event) {
    case "provider_attempt":
      return providerAttemptProjection(event);
    case "academic_route_summary": {
      const routeId = requiredText(event["route_id"]);
      const attemptIds = readStrictStringArray(event["attempt_ids"]);
      const outcome = readAcademicRouteOutcome(event["outcome"]);
      const count = readNonNegativeInteger(event["count"]);
      if (!routeId || !attemptIds || !outcome || count === undefined) return undefined;
      return {
        kind: "academic_route_summary",
        routeId,
        attemptIds,
        outcome,
        count,
      };
    }
    default:
      return undefined;
  }
}

function providerAttemptProjection(event: BackendEvent): ResearchProviderProjection | undefined {
  const providerKind = event["provider_kind"];
  const attemptId = requiredText(event["attempt_id"]);
  const routeId = requiredText(event["route_id"]);
  const provider = requiredText(event["provider"]);
  const outcome = readProviderAttemptOutcome(event["outcome"]);
  const count = readNonNegativeInteger(event["count"]);
  const failure = readProviderFailure(event["failure"]);
  if (
    (providerKind !== "model" && providerKind !== "academic_source")
    || !attemptId
    || !routeId
    || !provider
    || !outcome
    || count === undefined
    || (outcome === "failed" && !failure)
    || (outcome !== "failed" && failure)
  ) {
    return undefined;
  }
  return {
    kind: providerKind === "model" ? "model_attempt" : "academic_attempt",
    attemptId,
    routeId,
    provider,
    outcome,
    count,
    ...(failure ? { failure } : {}),
  };
}

function readProviderAttemptOutcome(value: unknown): ResearchProviderAttemptOutcome | undefined {
  return value === "success" || value === "empty" || value === "failed" ? value : undefined;
}

function readAcademicRouteOutcome(value: unknown): AcademicRouteOutcome | undefined {
  return value === "success" || value === "empty" || value === "failed" || value === "partial"
    ? value
    : undefined;
}

function readNonNegativeInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : undefined;
}

function readProviderFailure(value: unknown): ResearchProviderFailure | undefined {
  if (!isRecord(value)) return undefined;
  const code = requiredText(value["code"]);
  const message = requiredText(value["message"]);
  return code && message ? { code, message } : undefined;
}

function readStrictStringArray(value: unknown): readonly string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const values = value.map(requiredText);
  return values.every((item): item is string => item !== undefined) ? values : undefined;
}

function requiredText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
