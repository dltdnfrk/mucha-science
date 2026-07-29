import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SafeReportMarkdown } from "./SafeReportMarkdown";

describe("SafeReportMarkdown", () => {
  it.each([
    "https://reader:password@example.test/source",
    "https://example.test/source?key=secret",
    "https://example.test/source?auth=secret",
    "https://example.test/source?authorization=Bearer-secret",
    "https://example.test/source?bearer=secret",
  ])("renders credential-bearing links as text: %s", (url) => {
    const html = renderToStaticMarkup(
      <SafeReportMarkdown markdown={`[민감 링크](${url})`} />,
    );

    expect(html).toContain("<span>민감 링크</span>");
    expect(html).not.toContain(`href="${url}"`);
  });

  it("keeps safe academic links clickable", () => {
    const url = "https://api.openalex.org/works?author=kim";
    const html = renderToStaticMarkup(
      <SafeReportMarkdown markdown={`[OpenAlex](${url})`} />,
    );

    expect(html).toContain(`href="${url.replace("&", "&amp;")}"`);
    expect(html).toContain('rel="noreferrer"');
    expect(html).toContain('target="_blank"');
  });
});
