import { describe, expect, it } from "vitest";
import { buildRunTimeline } from "./runTimeline";

describe("buildRunTimeline", () => {
  it("classifies progress events into the seven spec stages", () => {
    const timeline = buildRunTimeline([
      "타겟팅 맵 생성",
      "검색 계획",
      "자료 검색 · 쿼리",
      "출처 감사",
      "주장과 근거 검증",
      "근거 승인 게이트 통과",
      "전문가 심의",
      "보고서 작성",
      "품질 벤치마크 평가",
    ]);

    const ids = timeline.stages.map((stage) => stage.id);
    expect(ids).toEqual([
      "targeting",
      "research",
      "evidence",
      "hitl",
      "council",
      "report",
      "eval",
    ]);
    expect(timeline.stages.filter((stage) => stage.status === "completed")).toHaveLength(7);
  });

  it("keeps raw events and caps key events at five per stage", () => {
    const events = [
      "자료 검색 · 1",
      "자료 검색 · 2",
      "자료 검색 · 3",
      "자료 검색 · 4",
      "자료 검색 · 5",
      "자료 검색 · 6",
    ];
    const timeline = buildRunTimeline(events);

    const research = timeline.stages.find((stage) => stage.id === "research");
    expect(research?.keyEvents).toHaveLength(5);
    expect(timeline.rawEvents).toEqual(events);
  });

  it("marks stages without events pending and exposes the report artifact count", () => {
    const timeline = buildRunTimeline(["자료 검색 완료"], ["artifact:report"]);

    const research = timeline.stages.find((stage) => stage.id === "research");
    expect(research?.status).toBe("completed");
    const council = timeline.stages.find((stage) => stage.id === "council");
    expect(council?.status).toBe("pending");
    const report = timeline.stages.find((stage) => stage.id === "report");
    expect(report?.summary).toContain("산출물 1건");
  });

  it("handles empty progress without crashing", () => {
    const timeline = buildRunTimeline([]);

    expect(timeline.rawEvents).toEqual([]);
    expect(timeline.stages.every((stage) => stage.status === "pending")).toBe(true);
  });
});
