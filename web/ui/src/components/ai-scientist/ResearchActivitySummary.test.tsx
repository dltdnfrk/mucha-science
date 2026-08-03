import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { emptyResearchActivity } from "../../lib/researchActivity";
import { ResearchActivitySummary } from "./ResearchActivitySummary";

describe("ResearchActivitySummary", () => {
  it("renders candidate and accepted counts even when none are accepted", () => {
    const html = renderToStaticMarkup(
      <ResearchActivitySummary
        activity={{
          ...emptyResearchActivity(),
          sourceCounts: { acceptedCount: 0, candidateCount: 12 },
        }}
        skippedSources={[]}
      />,
    );

    expect(html).toContain('data-candidate-count="12"');
    expect(html).toContain('data-accepted-count="0"');
  });
});
