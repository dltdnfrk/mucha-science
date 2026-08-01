import { useState } from "react";
import type { PlanReviewEditState } from "../components/PlannotatorPlanEditor";
import type {
  DeepInterviewArtifacts,
  HitlPrompt,
  InterviewClarity,
  InterviewPrompt,
} from "./runProgressInteractionTypes";

export function useRunProgressInteractionState() {
  const [interviewPrompt, setInterviewPrompt] = useState<InterviewPrompt | null>(null);
  const [interviewClarity, setInterviewClarity] = useState<InterviewClarity | null>(null);
  const [interviewArtifacts, setInterviewArtifacts] = useState<DeepInterviewArtifacts | null>(null);
  const [interviewAnswer, setInterviewAnswer] = useState("");
  const [interviewSelections, setInterviewSelections] = useState<string[]>([]);
  const [interviewSubmitting, setInterviewSubmitting] = useState(false);
  const [interviewError, setInterviewError] = useState<string | null>(null);
  const [hitlPrompt, setHitlPrompt] = useState<HitlPrompt | null>(null);
  const [planReviewEdits, setPlanReviewEdits] = useState<PlanReviewEditState | null>(null);
  const [hitlSubmitting, setHitlSubmitting] = useState(false);
  const [hitlError, setHitlError] = useState<string | null>(null);

  const resetInteractionArtifacts = () => {
    setInterviewPrompt(null);
    setInterviewClarity(null);
    setInterviewArtifacts(null);
    setInterviewAnswer("");
    setInterviewSelections([]);
    setInterviewError(null);
    setHitlPrompt(null);
    setPlanReviewEdits(null);
    setHitlError(null);
    setHitlSubmitting(false);
  };

  return {
    interviewPrompt, setInterviewPrompt, interviewClarity, setInterviewClarity,
    interviewArtifacts, setInterviewArtifacts, interviewAnswer, setInterviewAnswer,
    interviewSelections, setInterviewSelections, interviewSubmitting, setInterviewSubmitting,
    interviewError, setInterviewError, hitlPrompt, setHitlPrompt,
    planReviewEdits, setPlanReviewEdits, hitlSubmitting, setHitlSubmitting,
    hitlError, setHitlError, resetInteractionArtifacts,
  };
}
