import type { Dispatch, SetStateAction } from "react";
import type { InterviewClarity, InterviewPrompt } from "./runProgressInteractionTypes";
import { RunProgressInterviewContext } from "./RunProgressInterviewContext";
import { RunProgressInterviewResponse } from "./RunProgressInterviewResponse";

type InterviewCardProps = {
  readonly prompt: InterviewPrompt | null;
  readonly clarity: InterviewClarity | null;
  readonly answer: string;
  readonly selections: readonly string[];
  readonly submitting: boolean;
  readonly error: string | null;
  readonly activeDeepInterviewPrompt: boolean;
  readonly unknownDimensions: readonly string[];
  readonly ontologyNodes: readonly string[];
  readonly setAnswer: Dispatch<SetStateAction<string>>;
  readonly setSelections: Dispatch<SetStateAction<string[]>>;
  readonly clearError: () => void;
  readonly onAnswer: (answer: string, selected?: string, isOther?: boolean) => void;
  readonly onSelectedOptions: () => void;
};

export function RunProgressInterviewCard(props: InterviewCardProps) {
  if (!props.prompt) return null;
  return (
    <div className="fade-in mb-6 overflow-hidden rounded-lg border border-white/10 bg-white/[0.03] px-4 py-4">
      <RunProgressInterviewContext
        prompt={props.prompt}
        clarity={props.clarity}
        submitting={props.submitting}
        activeDeepInterviewPrompt={props.activeDeepInterviewPrompt}
        unknownDimensions={props.unknownDimensions}
        ontologyNodes={props.ontologyNodes}
      />
      <RunProgressInterviewResponse
        prompt={props.prompt}
        answer={props.answer}
        selections={props.selections}
        submitting={props.submitting}
        activeDeepInterviewPrompt={props.activeDeepInterviewPrompt}
        error={props.error}
        setAnswer={props.setAnswer}
        setSelections={props.setSelections}
        clearError={props.clearError}
        onAnswer={props.onAnswer}
        onSelectedOptions={props.onSelectedOptions}
      />
    </div>
  );
}
