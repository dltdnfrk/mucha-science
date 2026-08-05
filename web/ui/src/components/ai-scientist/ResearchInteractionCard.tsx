import { useState } from "react";
import type { PendingResearchInteraction } from "../../hooks/useResearchConversation";
import { RuleButton } from "./AiScientistPrimitives";

interface ResearchInteractionCardProps {
  readonly interaction: PendingResearchInteraction;
  readonly onAnswer: (optionKey?: string, freeText?: string) => Promise<void>;
}

export function ResearchInteractionCard({
  interaction,
  onAnswer,
}: ResearchInteractionCardProps) {
  const [freeText, setFreeText] = useState("");
  const { interaction: prompt, submitting } = interaction;
  const revisionOption = interaction.backendEvent === "hitl_gate"
    ? prompt.options.find((option) => option.value === "changes_requested")
    : undefined;
  const immediateOptions = revisionOption
    ? prompt.options.filter((option) => option.key !== revisionOption.key)
    : prompt.options;

  return (
    <section
      aria-labelledby={`interaction-${prompt.id}`}
      className="ms-inline-interaction"
    >
      <p>{prompt.title}</p>
      <h3 id={`interaction-${prompt.id}`}>{prompt.prompt}</h3>
      {immediateOptions.length > 0 ? (
        <div className="ms-inline-interaction__options">
          {immediateOptions.map((option) => (
            <RuleButton
              disabled={submitting}
              key={option.key}
              onClick={() => void onAnswer(option.key)}
            >
              <span>{option.key}</span>
              {option.label}
            </RuleButton>
          ))}
        </div>
      ) : null}
      {revisionOption ? (
        <details className="ms-inline-interaction__revision">
          <summary>
            <span>{revisionOption.key}</span>
            {revisionOption.label}
          </summary>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (freeText.trim()) void onAnswer(revisionOption.key, freeText);
            }}
          >
            <label htmlFor={`interaction-revision-${prompt.id}`}>수정 요청 내용</label>
            <div>
              <input
                disabled={submitting}
                id={`interaction-revision-${prompt.id}`}
                onChange={(event) => setFreeText(event.target.value)}
                value={freeText}
              />
              <RuleButton
                disabled={!freeText.trim()}
                loading={submitting}
                type="submit"
                variant="primary"
              >
                수정 요청 보내기
              </RuleButton>
            </div>
          </form>
        </details>
      ) : null}
      {interaction.allowFreeText ? (
        <form
          className="ms-inline-interaction__other"
          onSubmit={(event) => {
            event.preventDefault();
            if (freeText.trim()) void onAnswer(undefined, freeText);
          }}
        >
          <label htmlFor={`interaction-other-${prompt.id}`}>직접 답하기</label>
          <div>
            <input
              disabled={submitting}
              id={`interaction-other-${prompt.id}`}
              onChange={(event) => setFreeText(event.target.value)}
              value={freeText}
            />
            <RuleButton
              disabled={!freeText.trim()}
              loading={submitting}
              type="submit"
              variant="primary"
            >
              답변 보내기
            </RuleButton>
          </div>
        </form>
      ) : null}
    </section>
  );
}
