import type { BackendEvent } from "../lib/tauriClient";
import type { ResearchContractState } from "./runProgressTypes";

export function parseEventBoolean(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return normalized === "1" || normalized === "true" || normalized === "yes";
  }
  return false;
}

export function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

export function normalizeImportedKnowledgeRefs(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return [];
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (Array.isArray(parsed)) return parsed.map((item) => String(item).trim()).filter(Boolean);
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
    return [trimmed];
  }
  return [];
}

export function updateResearchContractFromEvent(
  previous: ResearchContractState,
  event: BackendEvent,
): ResearchContractState {
  const importedRefs = normalizeImportedKnowledgeRefs(event.imported_knowledge_refs);
  return {
    researchSessionId: String(event.research_session_id ?? previous.researchSessionId ?? "") || undefined,
    appRunId: String(event.app_run_id ?? previous.appRunId ?? "") || undefined,
    memoryPolicy: String(event.memory_policy ?? previous.memoryPolicy ?? "") || undefined,
    importedKnowledgeRefs:
      event.imported_knowledge_refs !== undefined ? importedRefs : previous.importedKnowledgeRefs,
  };
}

export function eventFeedsCurrentSessionEvidenceLedger(event: BackendEvent): boolean {
  return (
    event.event === "research_progress" &&
    (event.status === "source_found" || event.status === "source_evaluated")
  );
}

export function artifactKeyList(value: unknown): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.keys(value).sort();
}

export function optionalNumber(value: unknown): number | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : undefined;
}

export function optionalBoolean(value: unknown): boolean | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  return parseEventBoolean(value);
}

export function parseJsonRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.fromEntries(Object.entries(value));
  }
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? Object.fromEntries(Object.entries(parsed))
      : {};
  } catch (error) {
    if (error instanceof SyntaxError) return {};
    throw error;
  }
}

export function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch (error) {
    if (error instanceof SyntaxError) return value;
    throw error;
  }
}

export function parseStringArray(value: unknown): string[] | undefined {
  const raw = typeof value === "string" ? safeJsonParse(value) : value;
  if (!Array.isArray(raw)) return undefined;
  const items = raw.map((item) => String(item).trim()).filter(Boolean);
  return items.length > 0 ? items : undefined;
}
