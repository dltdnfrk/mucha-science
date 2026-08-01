import { useCallback, useEffect, type Dispatch, type SetStateAction } from "react";
import { planReviewAnnotations, type PlanReviewEditState } from "../components/PlannotatorPlanEditor";
import { sendAction } from "../lib/tauriClient";
import type { HitlPrompt, InterviewPrompt } from "./runProgressInteractionTypes";
import { isBackendGoneError } from "./runProgressStages";

type InteractionProps = {
  readonly runId?: string;
  readonly topic: string;
  readonly interviewPrompt: InterviewPrompt | null;
  readonly interviewSelections: string[];
  readonly interviewSubmitting: boolean;
  readonly hitlPrompt: HitlPrompt | null;
  readonly planReviewEdits: PlanReviewEditState | null;
  readonly hitlSubmitting: boolean;
  readonly failRun: (message: string) => void;
  readonly setInterviewAnswer: Dispatch<SetStateAction<string>>;
  readonly setInterviewSelections: Dispatch<SetStateAction<string[]>>;
  readonly setInterviewSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setInterviewError: Dispatch<SetStateAction<string | null>>;
  readonly setHitlSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setHitlError: Dispatch<SetStateAction<string | null>>;
};

export function autostartInterviewAnswer(
  questionId: string,
  topic: string,
): string {
  return questionId === "Q1_research_question"
    ? topic
    : `${topic} 기준으로 핵심 정의와 범위, 현장 검증, 가격/채택, 이해관계자와 규제 맥락, 한계와 검증 가능한 근거를 균형 있게 종합해줘.`;
}

export function useRunProgressInteractions(props: InteractionProps): {
  readonly submitInterviewAnswer: (
    answer: string,
    selected?: string,
    isOther?: boolean,
  ) => Promise<void>;
  readonly submitSelectedOptions: () => Promise<void>;
  readonly submitHitlDecision: (status: "approved" | "changes_requested") => Promise<void>;
} {
  const submitInterviewAnswer = useCallback(async (
    answer: string,
    selected?: string,
    isOther = false,
  ) => {
    if (!props.interviewPrompt || props.interviewSubmitting) return;
    const trimmed = answer.trim();
    if (!trimmed) {
      props.setInterviewError("답변을 입력하거나 선택하세요.");
      return;
    }
    props.setInterviewSubmitting(true);
    props.setInterviewError(null);
    try {
      await sendAction({
        action: "interview_answer",
        q_id: props.interviewPrompt.id,
        answer: trimmed,
        choice: selected ?? trimmed,
        selected: selected ?? trimmed,
        other_text: isOther ? trimmed : undefined,
      });
      props.setInterviewAnswer("");
      props.setInterviewSelections([]);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (isBackendGoneError(message)) props.failRun(message);
      props.setInterviewError(message);
      props.setInterviewSubmitting(false);
    }
  }, [props.interviewPrompt, props.interviewSubmitting, props.failRun]);

  const submitSelectedOptions = useCallback(async () => {
    if (!props.interviewPrompt || props.interviewSelections.length === 0) {
      props.setInterviewError("선택지를 하나 이상 골라주세요.");
      return;
    }
    await submitInterviewAnswer(
      props.interviewSelections.join(", "),
      props.interviewSelections.join(","),
      false,
    );
  }, [props.interviewPrompt, props.interviewSelections, submitInterviewAnswer]);

  const submitHitlDecision = useCallback(async (
    status: "approved" | "changes_requested",
  ) => {
    if (!props.hitlPrompt || props.hitlSubmitting) return;
    props.setHitlSubmitting(true);
    props.setHitlError(null);
    const annotations = props.hitlPrompt.gate === "plan"
      ? planReviewAnnotations(props.planReviewEdits)
      : [];
    try {
      await sendAction({
        action: "hitl_decision",
        gate: props.hitlPrompt.gate,
        status,
        annotations,
        comment: annotations.length > 0
          ? `inline plan review edits: ${annotations.length}`
          : undefined,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (isBackendGoneError(message)) props.failRun(message);
      props.setHitlError(message);
      props.setHitlSubmitting(false);
    }
  }, [props.hitlPrompt, props.hitlSubmitting, props.planReviewEdits, props.failRun]);

  useEffect(() => {
    if (
      !import.meta.env.VITE_MUCHANIPO_AUTOSTART_TOPIC
      || !props.interviewPrompt
      || props.interviewSubmitting
      || !props.runId
    ) return;
    const currentTopic = (
      props.topic || localStorage.getItem(`run:${props.runId}:topic`) || ""
    ).trim();
    if (!currentTopic) return;
    const key = `muchanipo:auto-answer:${props.runId}:${props.interviewPrompt.id}`;
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "1");
    const answer = autostartInterviewAnswer(
      props.interviewPrompt.id,
      currentTopic,
    );
    void submitInterviewAnswer(answer, "OTHER", true);
  }, [
    props.interviewPrompt,
    props.interviewSubmitting,
    props.runId,
    props.topic,
    submitInterviewAnswer,
  ]);

  useEffect(() => {
    if (
      !import.meta.env.VITE_MUCHANIPO_AUTOSTART_TOPIC
      || !props.hitlPrompt
      || props.hitlSubmitting
    ) return;
    const key = `muchanipo:auto-approve:${props.runId}:${props.hitlPrompt.gate}`;
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "1");
    void submitHitlDecision("approved");
  }, [props.hitlPrompt, props.hitlSubmitting, props.runId, submitHitlDecision]);

  return { submitInterviewAnswer, submitSelectedOptions, submitHitlDecision };
}
