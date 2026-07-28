import { describe, expect, it } from "vitest";

import {
  createResearchAssistantMessage,
  createThreadLabel,
  normalizeResearchPrompt,
} from "./researchConversation";

describe("normalizeResearchPrompt", () => {
  it("trims a Korean question without changing its internal spacing", () => {
    const question = "  춘천 농협의 최근 지점 정보를 알려줘  ";

    expect(normalizeResearchPrompt(question)).toBe("춘천 농협의 최근 지점 정보를 알려줘");
  });

  it("rejects an empty or whitespace-only question", () => {
    expect(() => normalizeResearchPrompt(" \t\n ")).toThrow();
  });
});

describe("createResearchAssistantMessage", () => {
  it("describes browser preview without claiming external collection or completed results", () => {
    const result = createResearchAssistantMessage({
      isBrowserPreview: true,
      sourceNames: [],
      startRequested: true,
    });

    expect(result.state).toBe("ready");
    expect(result.mode).toBe("preview");
    expect(result.eventCount).toBe(0);
    expect(result.sourceNames).toEqual([]);
  });

  it("names connected sources in the ready message", () => {
    const result = createResearchAssistantMessage({
      isBrowserPreview: false,
      sourceNames: ["CRM", "공공데이터"],
    });

    expect(result.state).toBe("ready");
    expect(result.mode).toBe("idle");
    expect(result.sourceNames).toEqual(["CRM", "공공데이터"]);
  });

  it("reports loading while an active desktop run is requested", () => {
    const result = createResearchAssistantMessage({
      isBrowserPreview: false,
      sourceNames: ["CRM"],
      startRequested: true,
    });

    expect(result.state).toBe("loading");
    expect(result.mode).toBe("running");
  });

  it("includes stage and event count in the process summary", () => {
    const result = createResearchAssistantMessage({
      isBrowserPreview: false,
      sourceNames: ["CRM"],
      stage: "검색 결과 정리",
      eventCount: 4,
      startRequested: true,
    });

    expect(result.stage).toBe("검색 결과 정리");
    expect(result.eventCount).toBe(4);
  });
});

describe("createThreadLabel", () => {
  it("truncates a long Korean question at a word boundary with an ellipsis", () => {
    const question =
      "강원도 농협 지점별 최근 거래처 방문 기록과 후속 조치 일정 정리 요청";
    const label = createThreadLabel(question);
    const prefix = label.slice(0, -1);

    expect(label.endsWith("…")).toBe(true);
    expect(label.length).toBeLessThanOrEqual(32);
    expect(question.startsWith(prefix)).toBe(true);
    expect(question.charAt(prefix.length)).toBe(" ");
  });
});
