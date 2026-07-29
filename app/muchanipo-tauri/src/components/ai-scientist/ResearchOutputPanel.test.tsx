import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ResearchConversationController } from "../../lib/researchConversationController";
import {
  buildSourceExecutionProfile,
  getDefaultSourceConnections,
} from "../../lib/sourceConnections";
import type { SourceConnectionsState } from "../../hooks/useSourceConnections";
import { ResearchOutputPanel } from "./ResearchOutputPanel";

const sources = getDefaultSourceConnections().slice(0, 2).map(
  (source) => ({ ...source, status: "connected" as const }),
);

const sourceConnections = {
  addSource: () => undefined,
  buildExecutionProfile: () => buildSourceExecutionProfile(sources, () => undefined),
  connectedSources: sources,
  hasSessionCredential: () => false,
  saveSessionCredential: () => true,
  setSourceStatus: () => undefined,
  sources,
} satisfies SourceConnectionsState;

const conversation = {
  activeTurnId: undefined,
  answerInteraction: async () => undefined,
  cancelTurn: async () => undefined,
  composerError: undefined,
  conversationSummaries: [],
  exportTurn: () => undefined,
  isRunning: false,
  newConversation: () => true,
  pendingInteraction: undefined,
  runtimeByTurn: {},
  session: { sessionId: "output-panel", turns: [] },
  submit: async () => false,
  switchConversation: () => true,
} satisfies ResearchConversationController;

describe("ResearchOutputPanel", () => {
  it("summarizes honest empty output state and connected source count", () => {
    const html = renderToStaticMarkup(
      <ResearchOutputPanel
        conversation={conversation}
        mode="summary"
        onClose={() => undefined}
        sourceConnections={sourceConnections}
      />,
    );

    expect(html).toContain('aria-label="연구 출력"');
    expect(html).toContain("연구를 시작하면 근거, 산출물, 품질 판정이 이곳에 정리됩니다.");
    expect(html).toContain("<dd>2개</dd>");
    expect(html).toContain("품질 판정 미확인");
  });

  it("renders sources and validation as compact panel content", () => {
    const sourcesHtml = renderToStaticMarkup(
      <ResearchOutputPanel
        conversation={conversation}
        mode="sources"
        onClose={() => undefined}
        sourceConnections={sourceConnections}
      />,
    );
    const validationHtml = renderToStaticMarkup(
      <ResearchOutputPanel
        conversation={conversation}
        mode="validation"
        onClose={() => undefined}
        sourceConnections={sourceConnections}
      />,
    );

    expect(sourcesHtml).toContain("ms-sources--compact");
    expect(validationHtml).toContain("ms-validation-workspace--compact");
    expect(validationHtml).not.toContain("연구 대화로 돌아가기");
  });
});
