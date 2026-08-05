import { afterEach, describe, expect, it, vi } from "vitest";
import { startResearchConversationTurn } from "./researchConversation";
import { persistResearchWorkspace } from "./researchConversationStorage";
import {
  artifactKindLabel,
  getArtifact,
  listArtifacts,
  listVersions,
} from "./researchArtifactLibrary";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  serialized(): string {
    return JSON.stringify(Object.fromEntries(this.values));
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function seedCompletedSession(
  storage: MemoryStorage,
  sessionId: string,
  prompt: string,
): void {
  const session = startResearchConversationTurn(
    { sessionId, turns: [] },
    {
      prompt,
      runId: `run-${sessionId}`,
      turnId: `turn-${sessionId}`,
    },
  );
  const finished = {
    ...session,
    turns: session.turns.map((turn) => ({
      ...turn,
      artifactIds: ["artifact:report", "artifact:source-audit"],
      finalReport: "# 검증된 최종 보고서\n\n근거 기반 결론입니다.",
      reportChunks: ["# 초안 1", "## 초안 2"],
      sourceIds: ["https://doi.org/10.1000/example", "https://doi.org/10.1000/example2"],
    })),
  };
  persistResearchWorkspace(finished, {
    [`turn-${sessionId}`]: {
      completedAt: 1_700_000_000_000,
      generation: 1,
      startedAt: 1_699_999_900_000,
      status: "complete",
      activity: {
        cancellationAcknowledged: false,
        claims: [],
        evidence: [],
        providers: [],
        quality: {
          kind: "quality",
          readiness: "ready",
          reasons: [],
        },
        routes: [],
      },
    },
  });
}

describe("research artifact library", () => {
  it("lists committed artifacts across sessions with kinds and content", () => {
    const storage = new MemoryStorage();
    vi.stubGlobal("window", { localStorage: storage });
    seedCompletedSession(storage, "session-lib-a", "첫 번째 연구 질문");

    const artifacts = listArtifacts();

    const kinds = artifacts.map((artifact) => artifact.kind).sort();
    expect(kinds).toEqual(["quality-summary", "report", "report-draft", "source-audit"]);
    const report = artifacts.find((artifact) => artifact.kind === "report");
    expect(report?.content).toContain("검증된 최종 보고서");
    expect(report?.contentType).toBe("markdown");
    expect(report?.version).toBe(1);
    expect(report?.sessionTitle).toBe("첫 번째 연구 질문");
    const sourceAudit = artifacts.find((artifact) => artifact.kind === "source-audit");
    expect(sourceAudit?.content).toContain("10.1000/example");
  });

  it("filters by session and run", () => {
    const storage = new MemoryStorage();
    vi.stubGlobal("window", { localStorage: storage });
    seedCompletedSession(storage, "session-lib-a", "첫 번째 연구 질문");
    seedCompletedSession(storage, "session-lib-b", "두 번째 연구 질문");

    expect(listArtifacts({ sessionId: "session-lib-a" })).toHaveLength(4);
    expect(listArtifacts({ runId: "run-session-lib-b" })).toHaveLength(4);
    expect(listArtifacts({ sessionId: "session-lib-a", runId: "run-session-lib-b" })).toHaveLength(0);
  });

  it("returns an artifact by id and its versions", () => {
    const storage = new MemoryStorage();
    vi.stubGlobal("window", { localStorage: storage });
    seedCompletedSession(storage, "session-lib-a", "첫 번째 연구 질문");

    const report = listArtifacts().find((artifact) => artifact.kind === "report");
    expect(report).toBeDefined();

    const fetched = getArtifact(report!.id);
    expect(fetched?.id).toBe(report!.id);
    expect(fetched?.kind).toBe("report");

    const versions = listVersions(report!.id);
    expect(versions.map((version) => version.id)).toContain(report!.id);
    expect(versions.every((version) => version.kind === "report")).toBe(true);
  });

  it("returns empty for missing artifacts and empty library", () => {
    const storage = new MemoryStorage();
    vi.stubGlobal("window", { localStorage: storage });

    expect(listArtifacts()).toEqual([]);
    expect(getArtifact("artifact:missing")).toBeUndefined();
    expect(listVersions("artifact:missing")).toEqual([]);
  });

  it("labels artifact kinds for the UI", () => {
    expect(artifactKindLabel("report")).toBe("최종 보고서");
    expect(artifactKindLabel("source-audit")).toBe("출처 검토");
    expect(artifactKindLabel("report-draft")).toBe("보고서 초안");
    expect(artifactKindLabel("quality-summary")).toBe("품질 요약");
  });
});
