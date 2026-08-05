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

  it("renders a pipeline configuration failure detail", () => {
    const html = renderToStaticMarkup(
      <ResearchConversationTurn
        now={2_000}
        onExport={() => undefined}
        runtime={{
          completedAt: 2_000,
          error: "MiMo API Key를 실행 설정에서 저장한 뒤 다시 시작하세요.",
          startedAt: 1_000,
          status: "error",
        }}
        turn={{
          artifactIds: [],
          finalReport: "",
          progress: [],
          prompt: "실행 설정 오류를 확인할 질문",
          reportChunks: [],
          runId: "run-2",
          sourceIds: [],
          turnId: "turn-2",
        }}
      />,
    );

    expect(html).toContain("MiMo API Key를 실행 설정에서 저장한 뒤 다시 시작하세요.");
    expect(html).toContain("실행이 중단되었습니다.");
    expect(html).not.toContain("실행 투영을 기다리는 중입니다.");
  });

  it("renders a completed report with reviewable gaps and an explicit warning", () => {
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
            quality: {
              kind: "quality",
              readiness: "needs_review",
              reasons: ["evidence_ledger_readiness=needs_review"],
            },
            routes: [],
          },
          completedAt: 2_000,
          startedAt: 1_000,
          status: "complete",
        }}
        turn={{
          artifactIds: ["artifact:final-report"],
          finalReport: "# 검토 가능한 최종 보고서",
          progress: [],
          prompt: "검토 가능한 근거로 보고서 작성",
          reportChunks: [],
          runId: "run-reviewable",
          sourceIds: ["https://doi.org/10.1056/NEJMoa2309676"],
          turnId: "turn-reviewable",
        }}
      />,
    );

    expect(html).toContain("검토 가능한 최종 보고서");
    expect(html).toContain("추가 검토가 필요한 보고서");
    expect(html).toContain("연구 기록 내보내기");
    expect(html).not.toContain("표시하지 않습니다");
  });

  it("renders the HITL recovery card with all four resume actions", () => {
    const html = renderToStaticMarkup(
      <ResearchConversationTurn
        now={2_000}
        onExport={() => undefined}
        onFork={() => undefined}
        onResumeGate={() => undefined}
        onResumeWithComment={() => undefined}
        runtime={{
          completedAt: 2_000,
          error: "근거 승인이 필요합니다.",
          startedAt: 1_000,
          status: "resumable",
        }}
        turn={{
          artifactIds: [],
          finalReport: "",
          progress: ["evidence gate"],
          prompt: "근거 보강이 필요한 연구 질문",
          reportChunks: [],
          runId: "run-resumable",
          sourceIds: [],
          turnId: "turn-resumable",
        }}
      />,
    );

    expect(html).toContain("근거 승인이 필요합니다.");
    expect(html).toContain("다시 승인 UI 열기");
    expect(html).toContain("수정 의견 보내며 재개");
    expect(html).toContain("여기까지 Artifact 저장");
    expect(html).toContain("새 Run으로 포크");
    expect(html).not.toContain("실행이 중단되었습니다.");
    expect(html).toContain("근거 승인 대기 중입니다.");
  });
});
