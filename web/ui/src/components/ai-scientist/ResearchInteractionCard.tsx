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

  return (
    <section
      aria-labelledby={`interaction-${prompt.id}`}
      className="ms-inline-interaction"
    >
      <p>{prompt.title}</p>
      <h3 id={`interaction-${prompt.id}`}>{prompt.prompt}</h3>
      {prompt.options.length > 0 ? (
        <div className="ms-inline-interaction__options">
          {prompt.options.map((option) => (
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
