import { planReviewAnnotations, type PlanReviewEditState } from "../components/PlannotatorPlanEditor";
import { browserPersonaRows } from "./runProgressCouncil";
import { isDeepInterviewSignal } from "./runProgressInteractionParsing";
import type {
  InterviewClarity,
  InterviewPrompt,
  RuntimeEvidence,
} from "./runProgressInteractionTypes";
import { deriveLiveE2eStatus, signalAge, STAGES } from "./runProgressStages";
import type { ResearchContractState, Stage, StageState } from "./runProgressTypes";

type ViewModelInput = {
  readonly runId?: string;
  readonly stages: Record<Stage, StageState>;
  readonly now: number;
  readonly runError: string | null;
  readonly runtimeEvidence: RuntimeEvidence | null;
  readonly hasReceivedHeartbeat: boolean;
  readonly sourceCount: number;
  readonly researchContract: ResearchContractState;
  readonly councilPersonas: string[];
  readonly interviewPrompt: InterviewPrompt | null;
  readonly interviewClarity: InterviewClarity | null;
  readonly planReviewEdits: PlanReviewEditState | null;
};

export function deriveRunProgressViewModel(input: ViewModelInput) {
  const completedCount = STAGES.filter(
    (stage) => input.stages[stage].status === "completed",
  ).length;
  const activeStage = STAGES.find((stage) => input.stages[stage].status === "active");
  const latestStage = activeStage
    ?? [...STAGES].reverse().find(
      (stage) => input.stages[stage].lastEventAt || input.stages[stage].status === "completed",
    )
    ?? "intake";
  const latestStageState = input.stages[latestStage];
  const activeStageState = activeStage ? input.stages[activeStage] : undefined;
  const unknownDimensions =
    input.interviewClarity?.missingDimensions.filter(Boolean).slice(0, 6) ?? [];
  const ontologyNodes = Array.from(new Set([
    input.interviewClarity?.focusLabel,
    input.interviewClarity?.focusDimension,
    ...unknownDimensions.slice(0, 3),
  ].map((item) => item?.trim()).filter((item): item is string => Boolean(item))));
  const importedCount = input.researchContract.importedKnowledgeRefs.length;

  return {
    completedCount,
    activeStage,
    latestStage,
    latestStageState,
    liveSignalAge: signalAge(input.now, latestStageState.lastEventAt),
    liveStatusLabel: input.runError
      ? "실행 중단"
      : activeStage
        ? "실시간 진행 중"
        : completedCount === STAGES.length ? "완료" : "첫 백엔드 신호 대기",
    liveDetail: input.runError
      ?? activeStageState?.message
      ?? latestStageState.message
      ?? "백엔드 이벤트를 기다리는 중입니다.",
    totalProgress: (completedCount / STAGES.length) * 100,
    selectedPersonaRows: browserPersonaRows(input.councilPersonas),
    desktopRuntimeStatus: input.runtimeEvidence ? "Observed" : "Not observed yet",
    liveE2eStatus: deriveLiveE2eStatus({
      runId: input.runId,
      runtimeRunId: input.runtimeEvidence?.runId,
      runtimeHeartbeatStage: input.runtimeEvidence?.heartbeatStage,
      hasVisibleBackendHeartbeat: input.hasReceivedHeartbeat,
    }),
    sourceAccessEvidenceStatus: input.sourceCount > 0
      ? `${input.sourceCount} source event${input.sourceCount === 1 ? "" : "s"}`
      : "Not observed yet",
    researchSessionLabel: input.researchContract.researchSessionId?.slice(-10) ?? "pending",
    memoryPolicyLabel: input.researchContract.memoryPolicy || "pending",
    importedRefsLabel: importedCount > 0
      ? `${importedCount} explicit imported ref${importedCount === 1 ? "" : "s"}`
      : "0 explicit imports",
    planReviewEditCount: planReviewAnnotations(input.planReviewEdits).length,
    activeDeepInterviewPrompt: input.interviewPrompt
      ? isDeepInterviewSignal(
        input.interviewPrompt.id,
        input.interviewPrompt.total,
        input.interviewPrompt.clarity,
      )
      : false,
    unknownDimensions,
    ontologyNodes,
  };
}
