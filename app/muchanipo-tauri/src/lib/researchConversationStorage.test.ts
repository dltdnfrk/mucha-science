import { afterEach, describe, expect, it, vi } from "vitest";
import {
  recordResearchConversationEvent,
  startResearchConversationTurn,
} from "./researchConversation";
import {
  loadResearchWorkspace,
  persistResearchWorkspace,
} from "./researchConversationStorage";

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

describe("research conversation workspace storage", () => {
  it("reopens a persisted multi-turn conversation with reports and runtime state", () => {
    const storage = new MemoryStorage();
    vi.stubGlobal("window", { localStorage: storage });
    const initial = loadResearchWorkspace();
    const firstTurn = {
      prompt: "첫 연구 질문",
      runId: "run-1",
      turnId: "turn-1",
    };
    const secondTurn = {
      prompt: "후속 연구 질문",
      runId: "run-2",
      turnId: "turn-2",
    };
    let session = startResearchConversationTurn(initial.session, firstTurn);
    session = recordResearchConversationEvent(session, {
      artifactIds: ["artifact:report:run-1"],
      body: "# 첫 보고서",
      event: "final_report",
      eventId: "event-1",
      runId: firstTurn.runId,
      sourceIds: ["https://doi.org/10.1000/first"],
      turnId: firstTurn.turnId,
    });
    session = startResearchConversationTurn(session, secondTurn);
    session = recordResearchConversationEvent(session, {
      artifactIds: ["/tmp/report-2.md"],
      body: "# 후속 보고서",
      event: "final_report",
      eventId: "event-2",
      runId: secondTurn.runId,
      sourceIds: ["https://doi.org/10.1000/second"],
      turnId: secondTurn.turnId,
    });

    persistResearchWorkspace(session, {
      "turn-1": { completedAt: 1100, startedAt: 1000, status: "complete" },
      "turn-2": { completedAt: 2200, startedAt: 2000, status: "complete" },
    });
    const reopened = loadResearchWorkspace();

    expect(reopened.session).toEqual(session);
    expect(reopened.session.turns).toHaveLength(2);
    expect(reopened.session.turns[1]?.artifactIds).toEqual(["/tmp/report-2.md"]);
    expect(reopened.runtimeByTurn["turn-2"]?.status).toBe("complete");
  });

  it("does not persist transient API credentials with the conversation", () => {
    const storage = new MemoryStorage();
    vi.stubGlobal("window", { localStorage: storage });
    const workspace = loadResearchWorkspace();

    persistResearchWorkspace(workspace.session, {});

    expect(storage.serialized()).not.toContain("SEMANTIC_SCHOLAR_API_KEY");
    expect(storage.serialized()).not.toContain("session-only-secret");
  });

  it("recovers with a new valid conversation when stored data is malformed", () => {
    const storage = new MemoryStorage();
    storage.setItem("muchanipo.research-conversation.active.v1", "broken-session");
    storage.setItem("muchanipo.research-conversation.v1.broken-session", "{bad-json");
    vi.stubGlobal("window", { localStorage: storage });

    const workspace = loadResearchWorkspace();

    expect(workspace.session.sessionId).toBe("broken-session");
    expect(workspace.session.turns).toEqual([]);
    expect(workspace.runtimeByTurn).toEqual({});
  });
});
