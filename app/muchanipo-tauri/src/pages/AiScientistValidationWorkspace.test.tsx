import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { ResearchConversationController } from "../lib/researchConversationController";
import { AiScientistValidationWorkspace } from "./AiScientistValidationWorkspace";

const emptyConversation = {
  activeTurnId: undefined,
  answerInteraction: async () => undefined,
  cancelTurn: async () => undefined,
  composerError: undefined,
  conversationSummaries: [],
  exportTurn: () => undefined,
  isRunning: false,
  newConversation: () => true,
  pendingInteraction: undefined,
  runtimeByTurn: {},
  session: { sessionId: "validation-empty", turns: [] },
  submit: async () => false,
  switchConversation: () => true,
} satisfies ResearchConversationController;

describe("AiScientistValidationWorkspace", () => {
  it("renders an empty in-shell validation ledger without a research composer", () => {
    // Given
    const conversation = emptyConversation;

    // When
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <AiScientistValidationWorkspace conversation={conversation} />
      </MemoryRouter>,
    );

    // Then
    expect(html).toContain('data-ai-scientist-validation="true"');
    expect(html).toContain("아직 검증 기록이 없습니다.");
    expect(html).toContain('href="/scientific"');
    expect(html).not.toContain("<textarea");
    expect(html).not.toContain("ms-research-composer");
    expect(html).not.toContain("6단계");
  });

  it("renders needs-review and blocked records with readiness and reason visibility", () => {
    // Given
    const conversation = {
      ...emptyConversation,
      runtimeByTurn: {
        "turn-review": {
          activity: {
            cancellationAcknowledged: false,
            claims: [],
            evidence: [],
            providers: [],
            quality: {
              kind: "quality",
              readiness: "needs_review",
              reasons: ["검토자가 확인할 출처가 남아 있습니다."],
            },
            routes: [],
          },
          completedAt: 2_000,
          startedAt: 1_000,
          status: "complete",
        },
        "turn-blocked": {
          activity: {
            cancellationAcknowledged: false,
            claims: [],
            evidence: [],
            providers: [],
            quality: { kind: "quality", readiness: "blocked", reasons: [] },
            routes: [],
          },
          completedAt: 4_000,
          startedAt: 3_000,
          status: "complete",
        },
      },
      session: {
        sessionId: "validation-records",
        turns: [
          {
            artifactIds: [],
            finalReport: "표시하면 안 되는 보고서",
            progress: ["문헌 검색"],
            prompt: "추가 검토가 필요한 질문",
            reportChunks: [],
            runId: "run-review",
            sourceIds: [],
            turnId: "turn-review",
          },
          {
            artifactIds: [],
            finalReport: "표시하면 안 되는 보고서",
            progress: ["근거 비교"],
            prompt: "근거가 불충분한 질문",
            reportChunks: [],
            runId: "run-blocked",
            sourceIds: [],
            turnId: "turn-blocked",
          },
        ],
      },
    } satisfies ResearchConversationController;

    // When
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <AiScientistValidationWorkspace conversation={conversation} />
      </MemoryRouter>,
    );

    // Then
    expect(html).toContain("추가 검토가 필요한 질문");
    expect(html).toContain("근거가 불충분한 질문");
    expect(html).toContain("검토 필요");
    expect(html).toContain("근거 불충분");
    expect(html).toContain("검토자가 확인할 출처가 남아 있습니다.");
    expect(html).toContain("품질 판정 사유가 기록되지 않았습니다.");
    expect(html).not.toContain("표시하면 안 되는 보고서");
  });
});
