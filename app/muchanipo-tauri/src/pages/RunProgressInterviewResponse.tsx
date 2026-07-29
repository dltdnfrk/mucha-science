import type { Dispatch, SetStateAction } from "react";
import type { InterviewPrompt } from "./runProgressInteractionTypes";

type InterviewResponseProps = {
  readonly prompt: InterviewPrompt;
  readonly answer: string;
  readonly selections: readonly string[];
  readonly submitting: boolean;
  readonly activeDeepInterviewPrompt: boolean;
  readonly error: string | null;
  readonly setAnswer: Dispatch<SetStateAction<string>>;
  readonly setSelections: Dispatch<SetStateAction<string[]>>;
  readonly clearError: () => void;
  readonly onAnswer: (answer: string, selected?: string, isOther?: boolean) => void;
  readonly onSelectedOptions: () => void;
};

export function RunProgressInterviewResponse(props: InterviewResponseProps) {
  const {
    prompt,
    answer,
    selections,
    submitting,
    activeDeepInterviewPrompt,
    error,
    setAnswer,
    setSelections,
    clearError,
    onAnswer,
    onSelectedOptions,
  } = props;
  return (
    <>
      {prompt.allowOther && (
        <div className="mb-3 rounded-xl border border-white/10 bg-black/20 p-3">
          <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wider text-tertiary">
            Socratic answer
          </label>
          <textarea
            value={answer}
            disabled={submitting}
            onChange={(event) => setAnswer(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                onAnswer(answer, "OTHER", true);
              }
            }}
            placeholder="자연어로 답변하세요. 보존하려는 개체, 행위자, 트리거, 제외 의미, 제약, 또는 근거 경계를 적어주세요."
            rows={4}
            className="min-h-24 w-full resize-y rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm leading-relaxed text-white placeholder-tertiary outline-none transition focus:border-white/30 focus:bg-black/40"
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-tertiary">⌘/Ctrl + Enter로 전송 · 답변이 정리되어 리서치가 계속됩니다</p>
            <button
              type="button"
              disabled={submitting || !answer.trim()}
              onClick={() => onAnswer(answer, "OTHER", true)}
              className="rounded-full bg-white px-4 py-2 text-sm font-medium text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "전송 중" : "답변 전송"}
            </button>
          </div>
        </div>
      )}
      {!activeDeepInterviewPrompt && prompt.options.length > 0 && (
        <div className="mb-3 rounded-xl border border-white/5 bg-white/[0.02] p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-tertiary">
            추천 답변 초안
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {prompt.options.map((option) => (
              <button
                key={`${option.key}:${option.value}`}
                type="button"
                disabled={submitting}
                onClick={() => {
                  if (prompt.multiSelect) {
                    setSelections((previous) =>
                      previous.includes(option.value)
                        ? previous.filter((item) => item !== option.value)
                        : [...previous, option.value],
                    );
                  } else {
                    setSelections([option.value]);
                    setAnswer(
                      option.description
                        ? `${option.label}\n${option.description}`
                        : option.label || option.value,
                    );
                    clearError();
                  }
                }}
                className={`rounded-lg border px-3 py-2 text-left text-xs transition disabled:cursor-not-allowed disabled:opacity-50 ${
                  selections.includes(option.value)
                    ? "border-white/30 bg-white/10 text-white"
                    : "border-white/10 bg-black/20 text-secondary hover:border-white/25 hover:bg-white/5 hover:text-white"
                }`}
              >
                <span className="mr-2 font-mono text-white">{option.key}</span>
                <span className="font-medium">{option.label}</span>
                {option.description && (
                  <span className="mt-1 block text-[11px] leading-relaxed text-tertiary">
                    {option.description}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
      {prompt.multiSelect && (
        <div className="mb-3 flex justify-end">
          <button
            type="button"
            disabled={submitting || selections.length === 0}
            onClick={onSelectedOptions}
            className="rounded-full bg-white px-4 py-2 text-sm font-medium text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "전송 중" : "선택 완료"}
          </button>
        </div>
      )}
      {error && <p className="mt-2 break-all text-xs text-red-300">{error}</p>}
    </>
  );
}
