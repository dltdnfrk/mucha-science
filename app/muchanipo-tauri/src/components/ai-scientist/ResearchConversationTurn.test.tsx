import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ResearchConversationTurn } from "./ResearchConversationTurn";

describe("ResearchConversationTurn", () => {
  it("renders the work log between the researcher prompt and Mucha response", () => {
    const html = renderToStaticMarkup(
      <ResearchConversationTurn
        now={2_000}
        onExport={() => undefined}
        runtime={{
          activity: {
            cancellationAcknowledged: false,
            claims: [],
            evidence: [],
            providers: [],
            quality: { kind: "quality", readiness: "ready", reasons: [] },
            routes: [],
          },
          completedAt: 2_000,
          startedAt: 1_000,
          status: "complete",
        }}
        turn={{
          artifactIds: [],
          finalReport: "검증된 최종 답변",
          progress: ["문헌 검색"],
          prompt: "검증할 연구 질문",
          reportChunks: [],
          runId: "run-1",
          sourceIds: [],
          turnId: "turn-1",
        }}
      />,
    );

    const promptIndex = html.indexOf("검증할 연구 질문");
    const activityIndex = html.indexOf("ms-chat-activity");
    const responseIndex = html.indexOf("검증된 최종 답변");
    expect(promptIndex).toBeGreaterThanOrEqual(0);
    expect(activityIndex).toBeGreaterThan(promptIndex);
    expect(responseIndex).toBeGreaterThan(activityIndex);
  });
});
