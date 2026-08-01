import type { ReactNode } from "react";
import type { ConversationState } from "./ResearchChatPrimitives";

export {
  ChatMessage,
  ProcessDisclosure,
  ResearchChatAppBar,
  ResearchComposer,
} from "./ResearchChatPrimitives";

export interface ThreadRailItem {
  readonly href: string;
  readonly id: string;
  readonly label: string;
  readonly meta: string;
}

interface ThreadRailProps {
  readonly currentId: string;
  readonly items: readonly ThreadRailItem[];
  readonly label?: string;
}

export function ThreadRail({
  currentId,
  items,
  label = "연구 대화 목록",
}: ThreadRailProps) {
  return (
    <nav aria-label={label} className="ms-thread-rail">
      <p className="ms-thread-rail__label">연구 기록</p>
      <ol>
        {items.map((item) => {
          const isCurrent = item.id === currentId;
          return (
            <li key={item.id}>
              <a aria-current={isCurrent ? "page" : undefined} href={item.href}>
                <span>{item.label}</span>
                <small>{item.meta}</small>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

interface ResearchConversationShellProps {
  readonly children: ReactNode;
  readonly rail: ReactNode;
  readonly title: string;
}

export function ResearchConversationShell({
  children,
  rail,
  title,
}: ResearchConversationShellProps) {
  return (
    <section aria-label={title} className="ms-conversation-shell">
      {rail}
      <div className="ms-conversation-shell__transcript">{children}</div>
    </section>
  );
}

interface TranscriptRowProps {
  readonly children: ReactNode;
  readonly index: string;
  readonly speaker: string;
  readonly state?: ConversationState;
  readonly time: string;
}

export function TranscriptRow({
  children,
  index,
  speaker,
  state = "default",
  time,
}: TranscriptRowProps) {
  return (
    <article className="ms-transcript-row" data-state={state}>
      <div className="ms-transcript-row__meta">
        <span>{index}</span>
        <span>{speaker}</span>
        <time>{time}</time>
      </div>
      <div className="ms-transcript-row__body">{children}</div>
    </article>
  );
}

interface ConnectorRowProps {
  readonly action?: ReactNode;
  readonly detail: string;
  readonly label: string;
  readonly state?: ConversationState;
}

export function ConnectorRow({
  action,
  detail,
  label,
  state = "default",
}: ConnectorRowProps) {
  return (
    <div className="ms-connector-row" data-state={state}>
      <div>
        <strong>{label}</strong>
        <span>{detail}</span>
      </div>
      {action ? <div className="ms-connector-row__action">{action}</div> : null}
    </div>
  );
}

interface ConnectorEditorProps {
  readonly children: ReactNode;
  readonly description: string;
  readonly title: string;
}

export function ConnectorEditor({
  children,
  description,
  title,
}: ConnectorEditorProps) {
  return (
    <fieldset className="ms-connector-editor">
      <legend>{title}</legend>
      <p>{description}</p>
      <div>{children}</div>
    </fieldset>
  );
}
