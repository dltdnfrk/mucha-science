import { normalizeResearchPrompt } from "./researchConversationPresentation";
import {
  sanitizeExternalReference,
  sanitizeMarkdownExternalReferences,
} from "./safeExternalUrl";

export {
  createResearchAssistantMessage,
  createThreadLabel,
  formatResearchArtifactLabel,
  formatResearchDuration,
  normalizeResearchPrompt,
  ResearchPromptError,
} from "./researchConversationPresentation";
export type {
  ResearchAssistantMessage,
  ResearchAssistantMessageInput,
  ResearchAssistantState,
} from "./researchConversationPresentation";

export interface ResearchConversationTurn {
  readonly turnId: string;
  readonly runId: string;
  readonly prompt: string;
  readonly progress: readonly string[];
  readonly reportChunks: readonly string[];
  readonly finalReport: string | null;
  readonly sourceIds: readonly string[];
  readonly artifactIds: readonly string[];
  readonly eventIds?: readonly string[];
}

export interface ResearchConversationSession {
  readonly sessionId: string;
  readonly turns: readonly ResearchConversationTurn[];
}

export interface StartedResearchTurn {
  readonly turnId: string;
  readonly runId: string;
  readonly prompt: string;
}

export interface ResearchConversationExport {
  readonly sessionId: string;
  readonly turnId: string;
  readonly runId: string;
  readonly sourceIds: readonly string[];
  readonly artifactIds: readonly string[];
  readonly reportBody: string;
}

export function createResearchConversationSession(
  sessionId: string,
): ResearchConversationSession {
  const normalizedId = requiredText(sessionId);
  if (!normalizedId) throw new ResearchConversationDataError("세션 ID가 필요합니다.");
  return { sessionId: normalizedId, turns: [] };
}

export function startResearchConversationTurn(
  session: ResearchConversationSession,
  input: StartedResearchTurn,
): ResearchConversationSession {
  const turnId = requiredText(input.turnId);
  const runId = requiredText(input.runId);
  const prompt = sanitizeMarkdownExternalReferences(
    normalizeResearchPrompt(input.prompt),
  );
  if (!turnId || !runId) throw new ResearchConversationDataError("턴과 실행 ID가 필요합니다.");
  if (session.turns.some((turn) => turn.turnId === turnId || turn.runId === runId)) {
    throw new ResearchConversationDataError("이미 존재하는 턴 또는 실행 ID입니다.");
  }
  return {
    ...session,
    turns: [...session.turns, {
      turnId,
      runId,
      prompt,
      progress: [],
      reportChunks: [],
      finalReport: null,
      sourceIds: [],
      artifactIds: [],
      eventIds: [],
    }],
  };
}

export function recordResearchConversationEvent(
  session: ResearchConversationSession,
  value: unknown,
): ResearchConversationSession {
  const event = readConversationEvent(value);
  if (!event) return session;
  const turnIndex = session.turns.findIndex(
    (turn) => turn.turnId === event.turnId && turn.runId === event.runId,
  );
  if (turnIndex < 0) return session;
  const turn = session.turns[turnIndex];
  if (turn.eventIds?.includes(event.eventId)) return session;
  const safeBody = sanitizeMarkdownExternalReferences(event.body);

  const updated: ResearchConversationTurn = {
    ...turn,
    progress: event.event === "research_progress"
      ? appendUnique(turn.progress, safeBody)
      : turn.progress,
    reportChunks: event.event === "report_chunk"
      ? [...turn.reportChunks, safeBody]
      : turn.reportChunks,
    finalReport: event.event === "final_report" ? safeBody : turn.finalReport,
    sourceIds: appendUnique(turn.sourceIds, ...sanitizeReferences(event.sourceIds)),
    artifactIds: appendUnique(turn.artifactIds, ...sanitizeReferences(event.artifactIds)),
    eventIds: [...(turn.eventIds ?? []), event.eventId],
  };
  const turns = [...session.turns];
  turns[turnIndex] = updated;
  return { ...session, turns };
}

export function serializeResearchConversationSession(
  session: ResearchConversationSession,
): string {
  return JSON.stringify({
    ...session,
    turns: session.turns.map(sanitizeTurnReferences),
  });
}

export function replayResearchConversationSession(
  serializedSession: string,
): ResearchConversationSession {
  let parsed: unknown;
  try {
    parsed = JSON.parse(serializedSession);
  } catch {
    throw new ResearchConversationDataError("저장된 연구 대화를 읽을 수 없습니다.");
  }
  const session = readConversationSession(parsed);
  if (!session) throw new ResearchConversationDataError("저장된 연구 대화 형식이 올바르지 않습니다.");
  return session;
}

export function createResearchConversationExport(
  session: ResearchConversationSession,
  turnId: string,
): ResearchConversationExport {
  const turn = session.turns.find((candidate) => candidate.turnId === turnId);
  if (!turn) throw new ResearchConversationDataError("내보낼 연구 턴을 찾을 수 없습니다.");
  return {
    sessionId: session.sessionId,
    turnId: turn.turnId,
    runId: turn.runId,
    sourceIds: [...turn.sourceIds],
    artifactIds: [...turn.artifactIds],
    reportBody: turn.finalReport ?? turn.reportChunks.join("\n\n"),
  };
}

export class ResearchConversationDataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ResearchConversationDataError";
  }
}

type ConversationEvent = {
  readonly event: "research_progress" | "report_chunk" | "final_report";
  readonly eventId: string;
  readonly runId: string;
  readonly turnId: string;
  readonly body: string;
  readonly sourceIds: readonly string[];
  readonly artifactIds: readonly string[];
};

function readConversationEvent(value: unknown): ConversationEvent | undefined {
  if (!isRecord(value)) return undefined;
  const event = value.event;
  if (event !== "research_progress" && event !== "report_chunk" && event !== "final_report") {
    return undefined;
  }
  const eventId = requiredText(value.eventId);
  const runId = requiredText(value.runId);
  const turnId = requiredText(value.turnId);
  const body = requiredText(event === "research_progress" ? value.stage : value.body);
  const sourceIds = readStringList(value.sourceIds);
  const artifactIds = readStringList(value.artifactIds);
  if (!eventId || !runId || !turnId || !body || !sourceIds || !artifactIds) return undefined;
  return { event, eventId, runId, turnId, body, sourceIds, artifactIds };
}

function readConversationSession(value: unknown): ResearchConversationSession | undefined {
  if (!isRecord(value) || !requiredText(value.sessionId) || !Array.isArray(value.turns)) return undefined;
  const turns = value.turns.map(readConversationTurn);
  if (turns.some((turn) => turn === undefined)) return undefined;
  return {
    sessionId: requiredText(value.sessionId) as string,
    turns: turns.filter((turn): turn is ResearchConversationTurn => turn !== undefined),
  };
}

function readConversationTurn(value: unknown): ResearchConversationTurn | undefined {
  if (!isRecord(value)) return undefined;
  const turnId = requiredText(value.turnId);
  const runId = requiredText(value.runId);
  const prompt = requiredText(value.prompt);
  const progress = readStringList(value.progress);
  const reportChunks = readStringList(value.reportChunks);
  const sourceIds = readStringList(value.sourceIds);
  const artifactIds = readStringList(value.artifactIds);
  const eventIds = readStringList(value.eventIds);
  const finalReport = value.finalReport;
  if (!turnId || !runId || !prompt || !progress || !reportChunks || !sourceIds ||
      !artifactIds || !eventIds || (finalReport !== null && typeof finalReport !== "string")) {
    return undefined;
  }
  return sanitizeTurnReferences({
    turnId,
    runId,
    prompt,
    progress,
    reportChunks,
    finalReport,
    sourceIds,
    artifactIds,
    eventIds,
  });
}

function readStringList(value: unknown): readonly string[] | undefined {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((item) => !requiredText(item))) return undefined;
  return value.map((item) => (item as string).trim());
}

function requiredText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function appendUnique(values: readonly string[], ...additions: readonly string[]): readonly string[] {
  return [...new Set([...values, ...additions])];
}

function sanitizeTurnReferences(
  turn: ResearchConversationTurn,
): ResearchConversationTurn {
  return {
    ...turn,
    artifactIds: sanitizeReferences(turn.artifactIds),
    finalReport: turn.finalReport === null
      ? null
      : sanitizeMarkdownExternalReferences(turn.finalReport),
    progress: turn.progress.map(sanitizeMarkdownExternalReferences),
    prompt: sanitizeMarkdownExternalReferences(turn.prompt),
    reportChunks: turn.reportChunks.map(sanitizeMarkdownExternalReferences),
    sourceIds: sanitizeReferences(turn.sourceIds),
  };
}

function sanitizeReferences(values: readonly string[]): readonly string[] {
  return values.map(sanitizeExternalReference);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
