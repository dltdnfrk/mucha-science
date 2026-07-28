import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ReportViewer } from "./ReportViewer";

describe("ReportViewer", () => {
  it("uses the fail-closed report link renderer", () => {
    const unsafeUrl = "https://example.test/report?authorization=Bearer-secret";
    const html = renderToStaticMarkup(
      <ReportViewer markdown={`[민감 보고서](${unsafeUrl})`} />,
    );

    expect(html).toContain("<span>민감 보고서</span>");
    expect(html).not.toContain(`href="${unsafeUrl}"`);
  });
});
