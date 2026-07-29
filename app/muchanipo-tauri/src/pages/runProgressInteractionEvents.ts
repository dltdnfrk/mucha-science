import type { Dispatch, SetStateAction } from "react";
import {
  normalizePlanReviewEditState,
  type PlanReviewEditState,
} from "../components/PlannotatorPlanEditor";
import {
  normalizePersonaPoolSummary,
  type PersonaPoolSummary,
} from "../components/PersonaPoolCard";
import type { BackendEvent } from "../lib/tauriClient";
import {
  artifactKeyList,
  parseJsonRecord,
  stringList,
} from "./runProgressEventValues";
import {
  normalizeDeepInterviewArtifacts,
  normalizeDeepInterviewProgress,
  normalizeHitlPrompt,
  normalizeInterviewPrompt,
} from "./runProgressInteractionParsing";
import type {
  DeepInterviewArtifacts,
  HitlPrompt,
  InterviewClarity,
  InterviewPrompt,
} from "./runProgressInteractionTypes";
import { isStage, PHASE_TO_STAGE, STAGES } from "./runProgressStages";
import type { Stage, StageState } from "./runProgressTypes";

export type InteractionEventContext = {
  readonly setStages: Dispatch<SetStateAction<Record<Stage, StageState>>>;
  readonly setInterviewPrompt: Dispatch<SetStateAction<InterviewPrompt | null>>;
  readonly setInterviewClarity: Dispatch<SetStateAction<InterviewClarity | null>>;
  readonly setInterviewArtifacts: Dispatch<SetStateAction<DeepInterviewArtifacts | null>>;
  readonly setInterviewAnswer: Dispatch<SetStateAction<string>>;
  readonly setInterviewSelections: Dispatch<SetStateAction<string[]>>;
  readonly setInterviewError: Dispatch<SetStateAction<string | null>>;
  readonly setInterviewSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setHitlPrompt: Dispatch<SetStateAction<HitlPrompt | null>>;
  readonly setPlanReviewEdits: Dispatch<SetStateAction<PlanReviewEditState | null>>;
  readonly setHitlError: Dispatch<SetStateAction<string | null>>;
  readonly setHitlSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setPersonaPool: Dispatch<SetStateAction<PersonaPoolSummary | null>>;
};

export function handleInteractionEvent(
  event: BackendEvent,
  context: InteractionEventContext,
): boolean {
  if (event.event === "deep_interview_progress") {
    const clarity = normalizeDeepInterviewProgress(event);
    context.setInterviewClarity(clarity);
    context.setStages((previous) => ({
      ...previous,
      interview: {
        ...previous.interview,
        status: previous.interview.status === "completed" ? "completed" : "active",
        startedAt: previous.interview.startedAt ?? Date.now(),
        lastEventAt: Date.now(),
        lastSignal: clarity.focusLabel ? `deep_interview · ${clarity.focusLabel}` : "deep_interview",
        message: clarity.coverageScore !== undefined
          ? `질문 명확화 중 · coverage ${Math.round(clarity.coverageScore * 100)}%`
          : "질문 명확화 중",
      },
    }));
    return true;
  }
  if (event.event === "deep_interview_artifacts") {
    const artifacts = normalizeDeepInterviewArtifacts(event);
    if (artifacts) context.setInterviewArtifacts(artifacts);
    return true;
  }
  if (event.event === "interview_question") {
    const prompt = normalizeInterviewPrompt(event);
    if (!prompt) return true;
    context.setStages((previous) => ({
      ...previous,
      interview: {
        ...previous.interview,
        status: previous.interview.status === "completed" ? "completed" : "active",
        startedAt: previous.interview.startedAt ?? Date.now(),
        lastEventAt: Date.now(),
        lastSignal: `interview_question · ${prompt.id}`,
        message: "사용자 답변 대기",
      },
    }));
    context.setInterviewPrompt(prompt);
    if (prompt.clarity) context.setInterviewClarity(prompt.clarity);
    context.setInterviewAnswer("");
    context.setInterviewSelections([]);
    context.setInterviewError(null);
    context.setInterviewSubmitting(false);
    return true;
  }
  if (event.event === "hitl_gate") {
    const prompt = normalizeHitlPrompt(event);
    if (!prompt) return true;
    const gateStage: Stage = prompt.gate === "plan" ? "targeting" : "evidence";
    context.setStages((previous) => ({
      ...previous,
      [gateStage]: {
        ...previous[gateStage],
        status: previous[gateStage].status === "completed" ? "completed" : "active",
        startedAt: previous[gateStage].startedAt ?? Date.now(),
        lastEventAt: Date.now(),
        lastSignal: `hitl_gate · ${prompt.gate}`,
        message: "사용자 검토 대기",
      },
    }));
    context.setHitlPrompt(prompt);
    context.setPlanReviewEdits(normalizePlanReviewEditState(prompt));
    context.setHitlError(null);
    context.setHitlSubmitting(false);
    return true;
  }
  if (event.event === "phase_change" && typeof event.phase === "string") {
    const stage = PHASE_TO_STAGE[event.phase.toUpperCase()];
    if (!stage) return true;
    if (stage !== "interview") {
      context.setInterviewPrompt(null);
      context.setInterviewSubmitting(false);
    }
    context.setHitlPrompt(null);
    context.setPlanReviewEdits(null);
    context.setHitlSubmitting(false);
    const phaseData = parseJsonRecord(event.data);
    const phaseArtifacts = parseJsonRecord(phaseData["artifacts"]);
    const eventArtifacts = parseJsonRecord(event.artifacts);
    const artifacts = Object.keys(phaseArtifacts).length > 0 ? phaseArtifacts : eventArtifacts;
    const summary = normalizePersonaPoolSummary(
      Object.keys(artifacts).length > 0 ? artifacts : null,
    );
    if (summary) context.setPersonaPool(summary);
    context.setStages((previous) => {
      const next = { ...previous };
      const currentIndex = STAGES.indexOf(stage);
      STAGES.forEach((candidate, index) => {
        if (index < currentIndex && next[candidate].status !== "completed") {
          next[candidate] = {
            ...next[candidate],
            status: "completed",
            completedAt: Date.now(),
            message: "완료",
          };
        }
      });
      next[stage] = {
        ...next[stage],
        status: "active",
        startedAt: next[stage].startedAt ?? Date.now(),
        lastEventAt: Date.now(),
        lastSignal: `phase_change · ${event.phase}`,
        message: "진행 중 · phase event 수신",
      };
      return next;
    });
    return true;
  }
  if (
    (event.event !== "stage_started" && event.event !== "stage_completed")
    || !isStage(event.stage)
  ) return false;
  const stage = event.stage;
  if (event.event === "stage_started" && stage !== "interview") {
    context.setInterviewPrompt(null);
    context.setInterviewSubmitting(false);
  }
  if (event.event === "stage_started") {
    context.setHitlPrompt(null);
    context.setHitlSubmitting(false);
  }
  context.setStages((previous) => {
    const next = { ...previous };
    const current = { ...next[stage] };
    const referenceProjects = stringList(event.reference_projects);
    const artifactKeys = artifactKeyList(event.artifacts);
    if (event.event === "stage_started") {
      Object.assign(current, {
        status: "active",
        startedAt: Date.now(),
        lastEventAt: Date.now(),
        lastSignal: "stage_started",
        message: "실행 시작 · backend event 수신",
      });
    } else {
      current.status = "completed";
      current.completedAt = Date.now();
      if (current.startedAt) current.durationMs = current.completedAt - current.startedAt;
      current.lastEventAt = Date.now();
      current.lastSignal = "stage_completed";
      current.message = "완료 · backend event 수신";
    }
    if (referenceProjects.length > 0) current.referenceProjects = referenceProjects;
    if (artifactKeys.length > 0) current.artifactKeys = artifactKeys;
    next[stage] = current;
    return next;
  });
  return true;
}
