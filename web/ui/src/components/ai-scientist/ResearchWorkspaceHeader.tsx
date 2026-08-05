import { Link } from "react-router-dom";
import type { AiScientistWorkspaceView } from "../../pages/AiScientistWorkspace";
import { PanelIcon, SourcesIcon, CheckIcon } from "./MuchaWorkspaceIcons";

interface ResearchWorkspaceHeaderProps {
  readonly panelOpen: boolean;
  readonly runtimeLabel: string;
  readonly sourceCount: number;
  readonly title: string;
  readonly view: AiScientistWorkspaceView;
  readonly onTogglePanel: () => void;
}

export function ResearchWorkspaceHeader({
  panelOpen,
  runtimeLabel,
  sourceCount,
  title,
  view,
  onTogglePanel,
}: ResearchWorkspaceHeaderProps) {
  return (
    <header className="ms-workspace-header">
      <div className="ms-workspace-header__title">
        <div>
          <strong>{title}</strong>
          <span>{runtimeLabel}</span>
        </div>
      </div>
      <nav className="ms-workspace-header__tools" aria-label="연구 작업공간 도구">
        <Link aria-current={view === "sources" ? "page" : undefined} to="/scientific/sources">
          <SourcesIcon />
          <span>출처 {sourceCount}</span>
        </Link>
        <Link aria-current={view === "validation" ? "page" : undefined} to="/scientific/validation">
          <CheckIcon />
          <span>검증</span>
        </Link>
        <button
          aria-label={panelOpen ? "연구 출력 패널 닫기" : "연구 출력 패널 열기"}
          aria-pressed={panelOpen}
          onClick={onTogglePanel}
          type="button"
        >
          <PanelIcon />
        </button>
      </nav>
    </header>
  );
}
