import {
  createResearchConversationExport,
  createResearchConversationSession,
  replayResearchConversationSession,
  serializeResearchConversationSession,
} from "./researchConversation";
import type {
  ResearchConversationExport,
  ResearchConversationSession,
} from "./researchConversation";
import type {
  ResearchActivity,
} from "./researchActivity";
import { sanitizeResearchActivityReferences } from "./researchActivity";
import { researchConversationStorageKey } from "./researchRuntime";
import { sanitizeExternalReference } from "./safeExternalUrl";
import type { SkippedSource } from "./sourceConnections";

const ACTIVE_SESSION_KEY = "muchanipo.research-conversation.active.v1";
const CONVERSATION_INDEX_KEY = "muchanipo.research-conversation.index.v1";
const EMPTY_CONVERSATION_LABEL = "새 연구 대화";

export type PersistedTurnStatus = "running" | "complete" | "error" | "canceled" | "preview" | "resumable";

export type PersistedTurnRuntime = {
  readonly activity?: ResearchActivity;
  readonly completedAt?: number;
  readonly generation?: number;
  readonly skippedSources?: readonly SkippedSource[];
  readonly startedAt: number;
  readonly status: PersistedTurnStatus;
};

export type PersistedResearchWorkspace = {
  readonly runtimeByTurn: Readonly<Record<string, PersistedTurnRuntime>>;
  readonly session: ResearchConversationSession;
};

export type ResearchConversationSummary = {
  readonly preview: string;
  readonly sessionId: string;
  readonly title: string;
  readonly updatedAt: number;
};

type ResearchConversationIndexEntry = {
  readonly sessionId: string;
  readonly updatedAt: number;
};

export function loadResearchWorkspace(): PersistedResearchWorkspace {
  const storage = localBrowserStorage();
  const sessionId = readText(storage, ACTIVE_SESSION_KEY) ?? createIdentifier("session");
  const storageKey = sessionStorageKey(sessionId);
  const session = readSession(storage, storageKey) ?? createResearchConversationSession(sessionId);
  const runtimeByTurn = readRuntime(storage, `${storageKey}.runtime`);
  return { session, runtimeByTurn };
}

export function createResearchWorkspace(): PersistedResearchWorkspace {
  const session = createResearchConversationSession(createIdentifier("session"));
  const workspace = { runtimeByTurn: {}, session };
  persistResearchWorkspace(session, workspace.runtimeByTurn);
  return workspace;
}

export function listResearchConversationSummaries(): readonly ResearchConversationSummary[] {
  const storage = localBrowserStorage();
  return readConversationIndex(storage)
    .flatMap((entry) => {
      const session = readSession(storage, sessionStorageKey(entry.sessionId));
      return session?.sessionId === entry.sessionId
        ? [createConversationSummary(session, entry.updatedAt)]
        : [];
    })
    .sort((left, right) => (
      right.updatedAt - left.updatedAt || left.sessionId.localeCompare(right.sessionId)
    ));
}

export function switchResearchWorkspace(sessionId: string): PersistedResearchWorkspace | undefined {
  const normalizedSessionId = readStoredText(sessionId);
  if (!normalizedSessionId) return undefined;
  const storage = localBrowserStorage();
  if (!storage) return undefined;
  const storageKey = sessionStorageKey(normalizedSessionId);
  const session = readSession(storage, storageKey);
  if (!session || session.sessionId !== normalizedSessionId) return undefined;
  write(storage, ACTIVE_SESSION_KEY, normalizedSessionId);
  return { session, runtimeByTurn: readRuntime(storage, `${storageKey}.runtime`) };
}

export function persistResearchWorkspace(
  session: ResearchConversationSession,
  runtimeByTurn: Readonly<Record<string, PersistedTurnRuntime>>,
): void {
  const storage = localBrowserStorage();
  if (!storage) return;
  const storageKey = sessionStorageKey(session.sessionId);
  write(storage, ACTIVE_SESSION_KEY, session.sessionId);
  write(storage, storageKey, serializeResearchConversationSession(session));
  write(storage, `${storageKey}.runtime`, JSON.stringify(
    sanitizeRuntimeReferences(runtimeByTurn),
  ));
  writeConversationIndex(storage, session);
}

export function createResearchIdentifier(prefix: "run" | "turn"): string {
  return createIdentifier(prefix);
}

export function downloadResearchTurn(
  session: ResearchConversationSession,
  turnId: string,
): void {
  const exported = createResearchConversationExport(session, turnId);
  const turn = session.turns.find((candidate) => candidate.turnId === turnId);
  if (!turn) return;

  const body = formatMarkdownExport(exported, turn.prompt);
  const blob = new Blob([body], { type: "text/markdown;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = `${safeFileName(turn.prompt)}-${turn.runId.slice(-8)}.md`;
  anchor.click();
  URL.revokeObjectURL(href);
}

function formatMarkdownExport(
  exported: ResearchConversationExport,
  prompt: string,
): string {
  const sources = markdownList(exported.sourceIds, "기록된 출처가 없습니다.");
  const artifacts = markdownList(exported.artifactIds, "기록된 산출물이 없습니다.");
  const report = exported.reportBody || "완성된 보고서가 없습니다.";
  return [
    "# MUNI lab 연구 기록",
    "",
    "## 질문",
    "",
    prompt,
    "",
    "## 답변",
    "",
    report,
    "",
    "## 출처",
    "",
    sources,
    "",
    "## 산출물",
    "",
    artifacts,
    "",
    `실행 ID: ${exported.runId}`,
    `대화 ID: ${exported.sessionId}`,
    "",
  ].join("\n");
}

function sanitizeRuntimeReferences(
  runtimeByTurn: Readonly<Record<string, PersistedTurnRuntime>>,
): Readonly<Record<string, PersistedTurnRuntime>> {
  return Object.fromEntries(Object.entries(runtimeByTurn).map(([turnId, runtime]) => [
    turnId,
    runtime.activity
      ? { ...runtime, activity: sanitizeResearchActivityReferences(runtime.activity) }
      : runtime,
  ]));
}

function markdownList(values: readonly string[], emptyMessage: string): string {
  return values.length > 0 ? values.map((value) => `- ${value}`).join("\n") : emptyMessage;
}

function safeFileName(value: string): string {
  const normalized = value.trim().replaceAll(/[\\/:*?"<>|]+/g, "-").slice(0, 48);
  return normalized || "mucha-research";
}

function sessionStorageKey(sessionId: string): string {
  return researchConversationStorageKey({ runId: sessionId });
}

function writeConversationIndex(storage: Storage, session: ResearchConversationSession): void {
  const updatedAt = Date.now();
  const retained = readConversationIndex(storage).filter((entry) => entry.sessionId !== session.sessionId);
  write(storage, CONVERSATION_INDEX_KEY, JSON.stringify([
    ...retained,
    { sessionId: session.sessionId, updatedAt },
  ]));
}

function readConversationIndex(storage: Storage | undefined): readonly ResearchConversationIndexEntry[] {
  const serialized = readText(storage, CONVERSATION_INDEX_KEY);
  if (!serialized) return [];
  try {
    const value: unknown = JSON.parse(serialized);
    if (!Array.isArray(value)) return [];
    const latestBySession = new Map<string, ResearchConversationIndexEntry>();
    for (const candidate of value) {
      const entry = readConversationIndexEntry(candidate);
      if (!entry) return [];
      const existing = latestBySession.get(entry.sessionId);
      if (!existing || entry.updatedAt > existing.updatedAt) latestBySession.set(entry.sessionId, entry);
    }
    return [...latestBySession.values()];
  } catch {
    return [];
  }
}

function readConversationIndexEntry(value: unknown): ResearchConversationIndexEntry | undefined {
  if (!isRecord(value)) return undefined;
  const sessionId = readStoredText(value.sessionId);
  const updatedAt = value.updatedAt;
  return sessionId
    && typeof updatedAt === "number"
    && Number.isFinite(updatedAt)
    && updatedAt >= 0
    ? { sessionId, updatedAt }
    : undefined;
}

function createConversationSummary(
  session: ResearchConversationSession,
  updatedAt: number,
): ResearchConversationSummary {
  const firstPrompt = session.turns[0]?.prompt ?? EMPTY_CONVERSATION_LABEL;
  return {
    preview: firstPrompt,
    sessionId: session.sessionId,
    title: firstPrompt,
    updatedAt,
  };
}

function readSession(storage: Storage | undefined, key: string): ResearchConversationSession | undefined {
  const serialized = readText(storage, key);
  if (!serialized) return undefined;
  try {
    return replayResearchConversationSession(serialized);
  } catch {
    return undefined;
  }
}

function readRuntime(
  storage: Storage | undefined,
  key: string,
): Readonly<Record<string, PersistedTurnRuntime>> {
  const serialized = readText(storage, key);
  if (!serialized) return {};
  try {
    const value: unknown = JSON.parse(serialized);
    if (!isRecord(value)) return {};
    const runtimes: Record<string, PersistedTurnRuntime> = {};
    for (const [turnId, rawRuntime] of Object.entries(value)) {
      const runtime = readPersistedRuntime(rawRuntime);
      if (runtime) runtimes[turnId] = runtime;
    }
    return runtimes;
  } catch {
    return {};
  }
}

function readPersistedRuntime(value: unknown): PersistedTurnRuntime | undefined {
  if (!isRecord(value) || typeof value.startedAt !== "number") return undefined;
  const status = readPersistedStatus(value.status);
  if (!status) return undefined;
  const completedAtValid = value.completedAt === undefined || typeof value.completedAt === "number";
  const generationValid = value.generation === undefined
    || (
      typeof value.generation === "number"
      && Number.isInteger(value.generation)
      && value.generation >= 0
    );
  const activity = readResearchActivity(value.activity);
  const skippedSources = readSkippedSources(value.skippedSources);
  if (
    !completedAtValid
    || !generationValid
    || (value.activity !== undefined && !activity)
    || (value.skippedSources !== undefined && !skippedSources)
  ) return undefined;
  return {
    ...(activity ? { activity } : {}),
    ...(typeof value.completedAt === "number" ? { completedAt: value.completedAt } : {}),
    ...(typeof value.generation === "number" ? { generation: value.generation } : {}),
    ...(skippedSources ? { skippedSources } : {}),
    startedAt: value.startedAt,
    status,
  };
}

function readPersistedStatus(value: unknown): PersistedTurnStatus | undefined {
  return value === "running"
    || value === "complete"
    || value === "error"
    || value === "canceled"
    || value === "preview"
    || value === "resumable"
    ? value
    : undefined;
}

function readResearchActivity(value: unknown): ResearchActivity | undefined {
  if (!isRecord(value) || typeof value.cancellationAcknowledged !== "boolean") {
    return undefined;
  }
  const providers = readList(value.providers, readProviderActivity);
  const routes = readList(value.routes, readRouteActivity);
  const evidence = readList(value.evidence, readEvidenceActivity);
  const claims = readList(value.claims, readClaimActivity);
  const quality = readQualityActivity(value.quality);
  const counterSearch = readCounterSearch(value.counterSearch);
  if (
    !providers
    || !routes
    || !evidence
    || !claims
    || (value.quality !== undefined && !quality)
    || (value.counterSearch !== undefined && !counterSearch)
  ) return undefined;
  return {
    cancellationAcknowledged: value.cancellationAcknowledged,
    claims,
    ...(counterSearch ? { counterSearch } : {}),
    evidence,
    providers,
    ...(quality ? { quality } : {}),
    routes,
  };
}

function readProviderActivity(
  value: unknown,
): ResearchActivity["providers"][number] | undefined {
  if (!isRecord(value)) return undefined;
  const attemptId = readStoredText(value.attemptId);
  const provider = readStoredText(value.provider);
  const providerKind = readOneOf(value.providerKind, ["model", "academic_source"]);
  const routeId = readStoredText(value.routeId);
  const outcome = readOneOf(value.outcome, ["success", "empty", "failed"]);
  const count = readNonNegativeInteger(value.count);
  const failure = value.failure === undefined ? undefined : readStoredText(value.failure);
  if (
    !attemptId
    || !provider
    || !providerKind
    || !routeId
    || !outcome
    || count === undefined
    || (value.failure !== undefined && !failure)
  ) return undefined;
  return {
    attemptId,
    count,
    ...(failure ? { failure } : {}),
    kind: "provider",
    outcome,
    provider,
    providerKind,
    routeId,
  };
}

function readRouteActivity(
  value: unknown,
): ResearchActivity["routes"][number] | undefined {
  if (!isRecord(value)) return undefined;
  const routeId = readStoredText(value.routeId);
  const outcome = readOneOf(value.outcome, ["success", "empty", "failed", "partial"]);
  const count = readNonNegativeInteger(value.count);
  return routeId && outcome && count !== undefined
    ? { count, kind: "route", outcome, routeId }
    : undefined;
}

function readEvidenceActivity(
  value: unknown,
): ResearchActivity["evidence"][number] | undefined {
  if (!isRecord(value) || typeof value.accepted !== "boolean") return undefined;
  const citationId = readStoredReference(value.citationId);
  const locator = readSafeLocator(value.locator);
  const sourceId = readStoredReference(value.sourceId);
  const title = value.title === undefined ? undefined : readStoredText(value.title);
  if (
    !citationId
    || !locator
    || !sourceId
    || (value.title !== undefined && !title)
  ) return undefined;
  return {
    accepted: value.accepted,
    citationId,
    kind: "evidence",
    locator,
    sourceId,
    ...(title ? { title } : {}),
  };
}

function readClaimActivity(
  value: unknown,
): ResearchActivity["claims"][number] | undefined {
  if (!isRecord(value)) return undefined;
  const claim = readStoredText(value.claim);
  const claimId = readStoredText(value.claimId);
  const stance = readOneOf(value.stance, ["supports", "refutes", "mixed", "inconclusive"]);
  const uncertainty = readOneOf(value.uncertainty, ["low", "moderate", "high", "unknown"]);
  return claim && claimId && stance && uncertainty
    ? { claim, claimId, kind: "claim", stance, uncertainty }
    : undefined;
}

function readQualityActivity(
  value: unknown,
): ResearchActivity["quality"] | undefined {
  if (!isRecord(value)) return undefined;
  const readiness = readOneOf(value.readiness, ["ready", "needs_review", "blocked"]);
  const reasons = readList(value.reasons, readStoredText);
  const processCompleteness = value.processCompleteness === undefined
    ? undefined
    : readOneOf(value.processCompleteness, ["complete", "partial", "blocked"]);
  if (
    !readiness
    || !reasons
    || (value.processCompleteness !== undefined && !processCompleteness)
  ) return undefined;
  return {
    kind: "quality",
    ...(processCompleteness ? { processCompleteness } : {}),
    readiness,
    reasons,
  };
}

function readCounterSearch(
  value: unknown,
): ResearchActivity["counterSearch"] | undefined {
  if (!isRecord(value) || typeof value.noNovelty !== "boolean") return undefined;
  const batchSize = readNonNegativeInteger(value.batchSize);
  const evaluated = readNonNegativeInteger(value.evaluated);
  const executed = readNonNegativeInteger(value.executed);
  const status = readOneOf(value.status, ["running", "completed"]);
  const stopReason = value.stopReason === undefined ? undefined : readStoredText(value.stopReason);
  if (
    batchSize === undefined
    || evaluated === undefined
    || executed === undefined
    || !status
    || (value.stopReason !== undefined && !stopReason)
  ) return undefined;
  return {
    batchSize,
    evaluated,
    executed,
    noNovelty: value.noNovelty,
    status,
    ...(stopReason ? { stopReason } : {}),
  };
}

function readSkippedSources(value: unknown): readonly SkippedSource[] | undefined {
  return readList(value, (candidate) => {
    if (!isRecord(candidate)) return undefined;
    const id = readStoredText(candidate.id);
    const name = readStoredText(candidate.name);
    const reason = readStoredText(candidate.reason);
    return id && name && reason ? { id, name, reason } : undefined;
  });
}

function readList<Item>(
  value: unknown,
  reader: (candidate: unknown) => Item | undefined,
): readonly Item[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const items: Item[] = [];
  for (const candidate of value) {
    const item = reader(candidate);
    if (item === undefined) return undefined;
    items.push(item);
  }
  return items;
}

function readOneOf<const Item extends string>(
  value: unknown,
  options: readonly Item[],
): Item | undefined {
  return typeof value === "string"
    ? options.find((option) => option === value)
    : undefined;
}

function readNonNegativeInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : undefined;
}

function readSafeLocator(value: unknown): string | undefined {
  const text = readStoredText(value);
  return text?.startsWith("https://")
    || text?.startsWith("http://")
    || text?.startsWith("mempalace:")
    ? sanitizeExternalReference(text)
    : undefined;
}

function readStoredReference(value: unknown): string | undefined {
  const text = readStoredText(value);
  return text ? sanitizeExternalReference(text) : undefined;
}

function readStoredText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function createIdentifier(prefix: string): string {
  const randomId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${prefix}-${randomId}`;
}

function localBrowserStorage(): Storage | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

function readText(storage: Storage | undefined, key: string): string | undefined {
  try {
    return storage?.getItem(key)?.trim() || undefined;
  } catch {
    return undefined;
  }
}

function write(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value);
  } catch {
    return;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
