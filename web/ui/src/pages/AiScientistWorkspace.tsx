import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "../styles/ai-scientist-research.css";
import "../styles/ai-scientist-chatgpt.css";
import { LibraryPanel } from "../components/ai-scientist/LibraryPanel";
import { ResearchConversationRail } from "../components/ai-scientist/ResearchConversationRail";
import {
  ResearchOutputPanel,
  type ResearchOutputPanelMode,
} from "../components/ai-scientist/ResearchOutputPanel";
import { ResearchWorkspaceHeader } from "../components/ai-scientist/ResearchWorkspaceHeader";
import { useResearchConversation } from "../hooks/useResearchConversation";
import { useSourceConnections } from "../hooks/useSourceConnections";
import { ResearchConversationPage } from "./ResearchConversationPage";
import { readExecutionPresentation } from "./runProgressSettings";

export type AiScientistWorkspaceView = "chat" | "sources" | "validation" | "library";

interface AiScientistWorkspaceProps {
  readonly view: AiScientistWorkspaceView;
}

export function AiScientistWorkspace({ view }: AiScientistWorkspaceProps) {
  const navigate = useNavigate();
  const sourceConnections = useSourceConnections();
  const conversation = useResearchConversation({
    buildSourceExecutionProfile: sourceConnections.buildExecutionProfile,
  });
  const [railCompact, setRailCompact] = useState(false);
  const [panelOpen, setPanelOpen] = useState(view !== "chat");
  const panelMode = panelModeForView(view);
  const activeSummary = conversation.conversationSummaries.find(
    (summary) => summary.sessionId === conversation.session.sessionId,
  );
  const executionPresentation = readExecutionPresentation({
    backendMode: localStorage.getItem("backend_mode"),
    hasMiMoCredential: Boolean(sessionStorage.getItem("mimo_api_key")?.trim()),
    hasOpenCodeGoCredential: Boolean(sessionStorage.getItem("opencode_api_key")?.trim()),
  });

  useEffect(() => {
    if (view !== "chat") setPanelOpen(true);
  }, [view]);

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const focusedDisclosure = document.activeElement?.closest<HTMLDetailsElement>("details[open]");
      if (focusedDisclosure) {
        focusedDisclosure.open = false;
        focusedDisclosure.querySelector<HTMLElement>("summary")?.focus();
        event.preventDefault();
        return;
      }
      if (!panelOpen) return;
      setPanelOpen(false);
      if (view !== "chat") navigate("/scientific");
      event.preventDefault();
    };

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [navigate, panelOpen, view]);

  const closePanel = () => {
    setPanelOpen(false);
    if (view !== "chat") navigate("/scientific");
  };

  return (
    <div
      className="ms-science-shell"
      data-ai-scientist-workspace
      data-panel-open={panelOpen}
      data-rail-compact={railCompact}
      data-theme="dark"
    >
      <ResearchConversationRail
        compact={railCompact}
        conversation={conversation}
        onToggleCompact={() => setRailCompact((current) => !current)}
        sourceCount={sourceConnections.connectedSources.length}
        view={view}
      />
      <ResearchWorkspaceHeader
        onTogglePanel={() => setPanelOpen((current) => !current)}
        panelOpen={panelOpen}
        runtimeLabel={executionPresentation.label}
        sourceCount={sourceConnections.connectedSources.length}
        title={activeSummary?.title ?? "새 연구 대화"}
        view={view}
      />
      <section className="ms-science-main">
        {view === "library" ? (
          <LibraryPanel />
        ) : (
          <ResearchConversationPage
            conversation={conversation}
            runtimeLabel={`${executionPresentation.label} · ${executionPresentation.detail}`}
            sourceCount={sourceConnections.connectedSources.length}
          />
        )}
      </section>
      {panelOpen ? (
        <ResearchOutputPanel
          conversation={conversation}
          mode={panelMode}
          onClose={closePanel}
          sourceConnections={sourceConnections}
        />
      ) : null}
    </div>
  );
}

function panelModeForView(view: AiScientistWorkspaceView): ResearchOutputPanelMode {
  if (view === "sources") return "sources";
  if (view === "validation") return "validation";
  return "summary";
}
