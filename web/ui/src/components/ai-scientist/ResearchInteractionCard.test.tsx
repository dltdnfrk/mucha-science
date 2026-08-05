import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ResearchInteractionCard } from "./ResearchInteractionCard";

describe("ResearchInteractionCard", () => {
  it("collects a required revision comment before submitting changes_requested", () => {
    const html = renderToStaticMarkup(
      <ResearchInteractionCard
        interaction={{
          allowFreeText: false,
          backendEvent: "hitl_gate",
          interaction: {
            id: "evidence",
            kind: "inline",
            prompt: "수집된 근거를 검토하세요.",
            title: "수집 근거 승인",
            options: [
              { key: "approve", label: "승인하고 계속", value: "approved" },
              { key: "changes", label: "수정 필요", value: "changes_requested" },
            ],
          },
          submitting: false,
        }}
        onAnswer={vi.fn(async () => undefined)}
      />,
    );

    expect(html).toContain("<details");
    expect(html).toContain("수정 필요");
    expect(html).toContain("수정 요청 내용");
    expect(html).toContain("수정 요청 보내기");
  });
});
