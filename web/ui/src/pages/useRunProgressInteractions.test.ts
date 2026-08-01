import { describe, expect, it } from "vitest";
import { autostartInterviewAnswer } from "./useRunProgressInteractions";

describe("autostartInterviewAnswer", () => {
  const topic = "해조류 기반 바이오플라스틱의 상용화 가능성";

  it("uses the current run topic as the first research-question answer", () => {
    expect(autostartInterviewAnswer("Q1_research_question", topic)).toBe(topic);
  });

  it("anchors later interview answers to the same current run topic", () => {
    const answer = autostartInterviewAnswer("Q2_scope", topic);
    expect(answer).toContain(topic);
    expect(answer).toContain("검증 가능한 근거");
  });
});
