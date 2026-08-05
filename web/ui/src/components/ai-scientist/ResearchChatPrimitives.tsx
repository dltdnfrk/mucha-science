import {
  useState,
  type FormEventHandler,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "../../lib/utils";

export type ConversationState = "default" | "loading" | "error" | "complete";

interface ResearchChatAppBarProps {
  readonly runtimeLabel: string;
  readonly sourceCount: number;
}

export function ResearchChatAppBar({
  runtimeLabel,
  sourceCount,
}: ResearchChatAppBarProps) {
  return (
    <header className="ms-chat-appbar">
      <a
          aria-label="MUNI lab AI 과학자 홈"
        className="ms-wordmark"
        href="#/scientific"
      >
          MUNI lab
      </a>
      <div className="ms-chat-appbar__utility">
        <span className="ms-chat-appbar__runtime">{runtimeLabel}</span>
        <a className="ms-text-link" href="#/scientific/sources">
          <span className="ms-chat-appbar__source-label--full">
            출처 설정 · {sourceCount}
          </span>
          <span aria-hidden="true" className="ms-chat-appbar__source-label--compact">
            출처 {sourceCount}
          </span>
        </a>
      </div>
    </header>
  );
}

type ChatMessageRole = "assistant" | "user";

interface ChatMessageProps {
  readonly children: ReactNode;
  readonly id?: string;
  readonly label: string;
  readonly meta?: string;
  readonly role: ChatMessageRole;
  readonly state?: ConversationState;
}

export function ChatMessage({
  children,
  id,
  label,
  meta,
  role,
  state = "default",
}: ChatMessageProps) {
  return (
    <article
      aria-label={`${label}${meta ? ` · ${meta}` : ""}`}
      className="ms-chat-message"
      data-role={role}
      data-state={state}
      id={id}
    >
      <div className="ms-chat-message__mark" aria-hidden="true">
        {role === "assistant" ? "M" : "나"}
      </div>
      <div className="ms-chat-message__content">
        <header className="ms-chat-message__header">
          <strong>{label}</strong>
          {meta ? <span>{meta}</span> : null}
        </header>
        <div className="ms-chat-message__body">{children}</div>
      </div>
    </article>
  );
}

interface ResearchComposerProps extends Omit<
  TextareaHTMLAttributes<HTMLTextAreaElement>,
  "aria-describedby" | "id" | "onSubmit"
> {
  readonly action: ReactNode;
  readonly error?: string;
  readonly helper: string;
  readonly id: string;
  readonly label: string;
  readonly onSubmit?: FormEventHandler<HTMLFormElement>;
  readonly state?: ConversationState;
}

export function ResearchComposer({
  action,
  className,
  error,
  helper,
  id,
  label,
  onSubmit,
  state = "default",
  ...props
}: ResearchComposerProps) {
  const messageId = `${id}-helper`;
  return (
    <form
      className={cn("ms-research-composer", error && "is-error", className)}
      data-state={state}
      onSubmit={onSubmit}
    >
      <label htmlFor={id}>{label}</label>
      <textarea
        {...props}
        aria-describedby={messageId}
        aria-invalid={error ? "true" : undefined}
        id={id}
      />
      <div className="ms-research-composer__footer">
        <p id={messageId} role={error ? "alert" : undefined}>
          {error ?? helper}
        </p>
        {action}
      </div>
    </form>
  );
}

interface ProcessDisclosureProps {
  readonly children: ReactNode;
  readonly className?: string;
  readonly defaultOpen?: boolean;
  readonly summary: string;
  readonly title: string;
}

export function ProcessDisclosure({
  children,
  className,
  defaultOpen = false,
  summary,
  title,
}: ProcessDisclosureProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <details
      className={cn("ms-process-disclosure", className)}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      open={isOpen}
    >
      <summary>
        <span>{title}</span>
        <small>{summary}</small>
      </summary>
      <div>{children}</div>
    </details>
  );
}
