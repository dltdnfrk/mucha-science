export type RunTimelineStageId =
  | "targeting"
  | "research"
  | "evidence"
  | "hitl"
  | "council"
  | "report"
  | "eval";

export type RunTimelineStage = {
  readonly id: RunTimelineStageId;
  readonly keyEvents: readonly string[];
  readonly label: string;
  readonly status: "pending" | "completed";
  readonly summary: string;
};

export type RunTimeline = {
  readonly rawEvents: readonly string[];
  readonly stages: readonly RunTimelineStage[];
};

const STAGE_ORDER: readonly RunTimelineStageId[] = [
  "targeting",
  "research",
  "evidence",
  "hitl",
  "council",
  "report",
  "eval",
];

// Classification priority: hitl keywords are specific and must win over
// evidence's broad 근거/증거 keywords (e.g. "근거 승인 게이트 통과" is a
// human-approval event, not an evidence-gathering one).
const CLASSIFY_ORDER: readonly RunTimelineStageId[] = [
  "targeting",
  "research",
  "hitl",
  "evidence",
  "council",
  "report",
  "eval",
];

const STAGE_LABELS: Readonly<Record<RunTimelineStageId, string>> = {
  council: "심의",
  evidence: "근거 검증",
  eval: "품질 평가",
  hitl: "인간 승인",
  report: "보고서",
  research: "리서치",
  targeting: "타겟팅",
};

const STAGE_KEYWORDS: Readonly<Record<RunTimelineStageId, readonly string[]>> = {
  council: ["심의", "전문가", "council", "HACHIMI"],
  evidence: ["근거", "증거", "출처", "주장", "감사", "채택"],
  eval: ["품질", "벤치마크", "평가", "완전성", "추적성"],
  hitl: ["승인", "검토 준비", "게이트"],
  report: ["보고서", "작성"],
  research: ["검색", "검색 계획", "자료", "리서치", "연구 진행", "후속"],
  targeting: ["타겟팅", "타겟"],
};

function stageForEvent(event: string): RunTimelineStageId | undefined {
  const lowered = event.toLowerCase();
  for (const id of CLASSIFY_ORDER) {
    if (STAGE_KEYWORDS[id].some((keyword) => lowered.includes(keyword))) {
      return id;
    }
  }
  return undefined;
}

export function buildRunTimeline(
  progress: readonly string[],
  artifactIds: readonly string[] = [],
): RunTimeline {
  const eventsByStage = new Map<RunTimelineStageId, string[]>();
  progress.forEach((event) => {
    const stage = stageForEvent(event) ?? "research";
    const events = eventsByStage.get(stage) ?? [];
    events.push(event);
    eventsByStage.set(stage, events);
  });

  const stages = STAGE_ORDER.map((id) => {
    const events = eventsByStage.get(id) ?? [];
    return {
      id,
      keyEvents: events.slice(0, 5),
      label: STAGE_LABELS[id],
      status: events.length > 0 ? ("completed" as const) : ("pending" as const),
      summary: events[0] ?? "",
    };
  });

  if (artifactIds.length > 0) {
    const reportStage = stages.find((stage) => stage.id === "report");
    if (reportStage && !reportStage.summary) {
      reportStage.summary = `보고서 산출 · 산출물 ${artifactIds.length}건`;
    }
  }

  return { rawEvents: [...progress], stages };
}
