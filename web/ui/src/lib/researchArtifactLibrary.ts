import {
  loadAllResearchSessions,
  type PersistedResearchSession,
} from "./researchConversationStorage";
import type { ResearchConversationTurn } from "./researchConversation";
import type { PersistedTurnRuntime } from "./researchConversationStorage";
import { createThreadLabel } from "./researchConversationPresentation";

export type ArtifactKind =
  | "report"
  | "report-draft"
  | "source-audit"
  | "quality-summary";

export type ArtifactContentType = "markdown" | "json" | "list";

export type ResearchArtifact = {
  readonly committedAt: number;
  readonly content: string;
  readonly contentType: ArtifactContentType;
  readonly id: string;
  readonly kind: ArtifactKind;
  readonly runId?: string;
  readonly sessionId: string;
  readonly sessionTitle: string;
  readonly title: string;
  readonly turnId?: string;
  readonly version: number;
};

export type ArtifactFilter = {
  readonly runId?: string;
  readonly sessionId?: string;
};

const KIND_LABELS: Readonly<Record<ArtifactKind, string>> = {
  "quality-summary": "품질 요약",
  report: "최종 보고서",
  "report-draft": "보고서 초안",
  "source-audit": "출처 검토",
};

export function artifactKindLabel(kind: ArtifactKind): string {
  return KIND_LABELS[kind];
}

function artifactId(kind: ArtifactKind, sessionId: string, turnId: string): string {
  return `artifact:${kind}:${sessionId}:${turnId}`;
}

function recordsForTurn(
  session: PersistedResearchSession["session"],
  runtimeByTurn: Readonly<Record<string, PersistedTurnRuntime>>,
  turn: ResearchConversationTurn,
): readonly ResearchArtifact[] {
  const runtime = runtimeByTurn[turn.turnId];
  const committedAt = runtime?.completedAt ?? Date.now();
  const sessionTitle = createThreadLabel(session.turns[0]?.prompt ?? "새 연구 대화");
  const records: ResearchArtifact[] = [];

  const reportContent = turn.finalReport?.trim();
  if (reportContent) {
    records.push({
      committedAt,
      content: reportContent,
      contentType: "markdown",
      id: artifactId("report", session.sessionId, turn.turnId),
      kind: "report",
      runId: turn.runId,
      sessionId: session.sessionId,
      sessionTitle,
      title: "최종 보고서",
      turnId: turn.turnId,
      version: 1,
    });
  }

  const draftContent = turn.reportChunks.join("\n\n").trim();
  if (draftContent) {
    records.push({
      committedAt,
      content: draftContent,
      contentType: "markdown",
      id: artifactId("report-draft", session.sessionId, turn.turnId),
      kind: "report-draft",
      runId: turn.runId,
      sessionId: session.sessionId,
      sessionTitle,
      title: "보고서 초안",
      turnId: turn.turnId,
      version: turn.reportChunks.length,
    });
  }

  if (turn.sourceIds.length > 0) {
    records.push({
      committedAt,
      content: JSON.stringify(turn.sourceIds, null, 2),
      contentType: "json",
      id: artifactId("source-audit", session.sessionId, turn.turnId),
      kind: "source-audit",
      runId: turn.runId,
      sessionId: session.sessionId,
      sessionTitle,
      title: `출처 검토 · ${turn.sourceIds.length}건`,
      turnId: turn.turnId,
      version: 1,
    });
  }

  const readiness = runtime?.activity?.quality?.readiness;
  if (readiness !== undefined) {
    const reasons = runtime.activity?.quality?.reasons ?? [];
    records.push({
      committedAt,
      content: JSON.stringify({ readiness, reasons }, null, 2),
      contentType: "json",
      id: artifactId("quality-summary", session.sessionId, turn.turnId),
      kind: "quality-summary",
      runId: turn.runId,
      sessionId: session.sessionId,
      sessionTitle,
      title: `품질 요약 · ${readiness}`,
      turnId: turn.turnId,
      version: 1,
    });
  }

  return records;
}

export function listArtifacts(filter: ArtifactFilter = {}): readonly ResearchArtifact[] {
  return loadAllResearchSessions()
    .flatMap(({ session, runtimeByTurn }) => session.turns.flatMap((turn) => (
      recordsForTurn(session, runtimeByTurn, turn)
    )))
    .filter((record) => (
      (filter.sessionId === undefined || record.sessionId === filter.sessionId)
      && (filter.runId === undefined || record.runId === filter.runId)
    ))
    .sort((left, right) => right.committedAt - left.committedAt);
}

export function getArtifact(id: string): ResearchArtifact | undefined {
  return listArtifacts().find((record) => record.id === id);
}

export function listVersions(artifactId: string): readonly ResearchArtifact[] {
  const target = getArtifact(artifactId);
  if (!target) return [];
  return listArtifacts({
    runId: target.runId,
    sessionId: target.sessionId,
  }).filter((record) => record.kind === target.kind);
}
