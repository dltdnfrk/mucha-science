import { Link, useNavigate } from "react-router-dom";
import type { ResearchConversationController } from "../../lib/researchConversationController";
import type { AiScientistWorkspaceView } from "../../pages/AiScientistWorkspace";
import {
  CheckIcon,
  ComposeIcon,
  LibraryIcon,
  SettingsIcon,
  SidebarIcon,
  SourcesIcon,
} from "./MuchaWorkspaceIcons";

interface ResearchConversationRailProps {
  readonly compact: boolean;
  readonly conversation: ResearchConversationController;
  readonly onToggleCompact: () => void;
  readonly sourceCount: number;
  readonly view: AiScientistWorkspaceView;
}

export function ResearchConversationRail({
  compact,
  conversation,
  onToggleCompact,
  sourceCount,
  view,
}: ResearchConversationRailProps) {
  const navigate = useNavigate();
  const locked = conversation.isRunning;

  const createConversation = () => {
    if (conversation.newConversation()) navigate("/scientific");
  };

  const selectConversation = (sessionId: string) => {
    if (conversation.switchConversation(sessionId)) navigate("/scientific");
  };

  return (
    <aside
      className="ms-conversation-rail"
      aria-labelledby="research-conversation-rail-heading"
      data-compact={compact}
    >
      <header className="ms-conversation-rail__header">
        <a aria-label="MUNI lab 연구 대화 홈" className="ms-conversation-rail__brand" href="#/scientific">
          <img alt="" aria-hidden="true" className="ms-brand-icon" src="/muni-lab-icon.svg" />
          <strong id="research-conversation-rail-heading">MUNI lab</strong>
        </a>
        <button
          aria-label={compact ? "대화 목록 펼치기" : "대화 목록 접기"}
          className="ms-conversation-rail__collapse"
          onClick={onToggleCompact}
          type="button"
        >
          <SidebarIcon />
        </button>
      </header>

      <button
        aria-label="새 연구 대화 만들기"
        className="ms-conversation-rail__new"
        disabled={locked}
        onClick={createConversation}
        title={locked ? "현재 연구가 끝난 뒤 새 대화를 만들 수 있습니다." : undefined}
        type="button"
      >
        <ComposeIcon />
        <span>새 대화</span>
      </button>

      <nav className="ms-conversation-rail__history" aria-label="저장된 연구 대화">
        <ul className="ms-conversation-rail__list">
          {conversation.conversationSummaries.map((summary) => {
            const active = summary.sessionId === conversation.session.sessionId;
            return (
              <li key={summary.sessionId}>
                <button
                  aria-current={active ? "page" : undefined}
                  aria-label={`${summary.title} 대화 열기`}
                  className={active
                    ? "ms-conversation-rail__item ms-conversation-rail__item--active"
                    : "ms-conversation-rail__item"}
                  data-session-id={summary.sessionId}
                  disabled={locked}
                  onClick={() => selectConversation(summary.sessionId)}
                  type="button"
                >
                  <span className="ms-conversation-rail__conversation-mark" aria-hidden="true">
                  {[...summary.title.trim()][0] ?? "R"}
                  </span>
                  <span className="ms-conversation-rail__item-copy">
                    <span>{summary.title}</span>
                    {summary.preview === summary.title ? null : <small>{summary.preview}</small>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <nav className="ms-conversation-rail__nav ms-conversation-rail__utility" aria-label="연구 도구">
        <Link aria-current={view === "sources" ? "page" : undefined} to="/scientific/sources">
          <SourcesIcon />
          <span>출처 설정 · {sourceCount}</span>
        </Link>
        <Link aria-current={view === "validation" ? "page" : undefined} to="/scientific/validation">
          <CheckIcon />
          <span>검증 기록</span>
        </Link>
        <Link aria-current={view === "library" ? "page" : undefined} to="/scientific/library">
          <LibraryIcon />
          <span>Library</span>
        </Link>
        <Link to="/settings">
          <SettingsIcon />
          <span>실행 설정</span>
        </Link>
      </nav>
    </aside>
  );
}
