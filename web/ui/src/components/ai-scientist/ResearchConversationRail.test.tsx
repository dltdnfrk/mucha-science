import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { ResearchConversationController } from "../../lib/researchConversationController";
import { ResearchConversationRail } from "./ResearchConversationRail";

const conversation = {
  activeTurnId: undefined,
  answerInteraction: async () => undefined,
  cancelTurn: async () => undefined,
  composerError: undefined,
  conversationSummaries: [
    {
      preview: "장내 미생물과 우울증의 인과 근거",
      sessionId: "session-active",
      title: "장내 미생물과 우울증의 인과 근거",
      updatedAt: 2,
    },
    {
      preview: "해조류 기반 탄소 포집이 연안 생태계와 지역 탄소 회계에 미치는 장기 영향을 검토합니다.",
      sessionId: "session-older",
      title: "해조류 기반 탄소 포집",
      updatedAt: 1,
    },
  ],
  exportTurn: () => undefined,
  isRunning: false,
  newConversation: () => true,
  pendingInteraction: undefined,
  runtimeByTurn: {},
  session: { sessionId: "session-active", turns: [] },
  submit: async () => false,
  switchConversation: () => true,
} satisfies ResearchConversationController;

describe("ResearchConversationRail", () => {
  it("renders named conversation navigation with active and utility routes", () => {
    // Given
    const currentPath = "/scientific";

    // When
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={[currentPath]}>
        <ResearchConversationRail
          compact={false}
          conversation={conversation}
          onToggleCompact={() => undefined}
          sourceCount={3}
          view="chat"
        />
      </MemoryRouter>,
    );

    // Then
    expect(html).toContain('<aside class="ms-conversation-rail"');
    expect(html).toContain('aria-labelledby="research-conversation-rail-heading"');
    expect(html).toContain('aria-label="새 연구 대화 만들기"');
    expect(html).toContain('aria-current="page"');
    expect(html).toContain('href="/scientific/sources"');
    expect(html).toContain('href="/scientific/validation"');
    expect(html).toContain('href="/settings"');
  });

  it("omits a duplicate preview while preserving a distinct preview and marking the current utility", () => {
    // Given
    const currentPath = "/scientific/sources";

    // When
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={[currentPath]}>
        <ResearchConversationRail
          compact={false}
          conversation={conversation}
          onToggleCompact={() => undefined}
          sourceCount={3}
          view="sources"
        />
      </MemoryRouter>,
    );

    // Then
    expect(html).not.toContain('<small>장내 미생물과 우울증의 인과 근거</small>');
    expect(html).toContain(
      '<small>해조류 기반 탄소 포집이 연안 생태계와 지역 탄소 회계에 미치는 장기 영향을 검토합니다.</small>',
    );
    expect(html).toContain('aria-current="page" href="/scientific/sources"');
    expect(html).not.toContain('aria-current="page" href="/scientific/validation"');
  });

  it("disables new and conversation switches while research is running", () => {
    // Given
    const runningConversation = { ...conversation, isRunning: true };

    // When
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/scientific"]}>
        <ResearchConversationRail
          compact={false}
          conversation={runningConversation}
          onToggleCompact={() => undefined}
          sourceCount={1}
          view="chat"
        />
      </MemoryRouter>,
    );

    // Then
    expect(html.match(/disabled=""/g)).toHaveLength(3);
  });

  it("keeps icon controls and hides labels through compact-mode styling", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/scientific"]}>
        <ResearchConversationRail
          compact
          conversation={conversation}
          onToggleCompact={() => undefined}
          sourceCount={3}
          view="chat"
        />
      </MemoryRouter>,
    );

    expect(html).toContain('data-compact="true"');
    expect(html).toContain('aria-label="대화 목록 펼치기"');
  });
});
