import { describe, expect, it } from "vitest";

import {
  COMPLETE_FINAL_BUNDLE_FIXTURE,
  FINAL_BUNDLE_FIELDS,
  FINAL_BUNDLE_HIDDEN_FIELDS,
  FINAL_BUNDLE_RENDERED_FIELDS,
  extractFinalBundleFromEvent,
  finalBundleDegradationCopy,
  finalBundleListSections,
  parseFinalBundle,
} from "./finalBundle";

describe("bundle field accounting (issue #46)", () => {
  it("renders or intentionally hides every field of the bundle contract", () => {
    const accounted = [...FINAL_BUNDLE_RENDERED_FIELDS, ...FINAL_BUNDLE_HIDDEN_FIELDS].sort();
    expect(accounted).toEqual([...FINAL_BUNDLE_FIELDS].sort());
  });

  it("the complete fixture carries every contract field and parses complete", () => {
    for (const field of FINAL_BUNDLE_FIELDS) {
      expect(COMPLETE_FINAL_BUNDLE_FIXTURE).toHaveProperty(field);
    }
    const view = parseFinalBundle(COMPLETE_FINAL_BUNDLE_FIXTURE);
    expect(view.status).toBe("complete");
    expect(view.missingFields).toEqual([]);
    expect(view.invalidFields).toEqual([]);
    expect(finalBundleDegradationCopy(view)).toBe("");
  });
});

describe("parseFinalBundle — complete payloads", () => {
  it("maps every rendered field into the view", () => {
    const view = parseFinalBundle(COMPLETE_FINAL_BUNDLE_FIXTURE);

    expect(view.reportId).toBe("brief-fixture");
    expect(view.title).toBe("Fixture decision report");
    expect(view.verdict).toBe("PASS");
    expect(view.centralClaims).toEqual(["Council-backed final claim", "Follow-on claim"]);
    expect(view.sourceIds).toEqual(["https://example.test/ev-1"]);
    expect(view.evidenceIds).toEqual(["ev-1"]);
    expect(view.openGaps).toEqual(["Quantify pricing sensitivity."]);
    expect(view.blockers).toEqual([]);
  });

  it("normalizes structured blockers with code, message, and required action", () => {
    const view = parseFinalBundle({
      ...COMPLETE_FINAL_BUNDLE_FIXTURE,
      verdict: "BLOCKED",
      blockers: [
        {
          code: "blocked_final_gate_pending",
          message: "A required review gate is still pending.",
          required_action: "wait_for_required_review_gate",
          severity: "blocker",
        },
        "bare_string_code",
      ],
    });

    expect(view.verdict).toBe("BLOCKED");
    expect(view.blockers).toEqual([
      {
        code: "blocked_final_gate_pending",
        message: "A required review gate is still pending.",
        requiredAction: "wait_for_required_review_gate",
      },
      { code: "bare_string_code", message: "", requiredAction: "" },
    ]);
  });
});

describe("parseFinalBundle — partial payloads", () => {
  it("lists missing fields, keeps safe defaults, and degrades with copy", () => {
    const view = parseFinalBundle({
      schema_version: 1,
      contract: "final_report_html_yaml_bundle.v1",
      report_id: "brief-partial",
      title: "Partial report",
      verdict: "PASS",
      central_claims: ["only claim"],
      // source_ids / evidence_ids / open_gaps / blockers missing
    });

    expect(view.status).toBe("partial");
    expect(view.missingFields.sort()).toEqual(
      ["blockers", "evidence_ids", "open_gaps", "source_ids"].sort(),
    );
    expect(view.centralClaims).toEqual(["only claim"]);
    expect(view.sourceIds).toEqual([]);
    const copy = finalBundleDegradationCopy(view);
    expect(copy).toContain("불완전");
    expect(copy).toContain("source_ids");
  });

  it("flags wrong-shaped fields as invalid instead of crashing", () => {
    const view = parseFinalBundle({
      ...COMPLETE_FINAL_BUNDLE_FIXTURE,
      central_claims: "not-a-list",
      blockers: 42,
      verdict: "MAYBE",
    });

    expect(view.status).toBe("partial");
    expect(view.invalidFields.sort()).toEqual(["blockers", "central_claims", "verdict"].sort());
    expect(view.centralClaims).toEqual([]);
    expect(view.blockers).toEqual([]);
    expect(view.verdict).toBe("");
    expect(finalBundleDegradationCopy(view)).toContain("형식 이상");
  });
});

describe("parseFinalBundle — malformed payloads", () => {
  it.each([null, undefined, "text", 7, true, ["list"]])(
    "degrades %p to an explicit malformed view",
    (payload) => {
      const view = parseFinalBundle(payload);
      expect(view.status).toBe("malformed");
      expect(finalBundleDegradationCopy(view)).toContain("해석할 수 없습니다");
    },
  );
});

describe("extractFinalBundleFromEvent", () => {
  it("reads the normalized metadata.final_bundle from final-report lifecycle events", () => {
    const bundle = extractFinalBundleFromEvent({
      event: "stage_completed",
      stage: "final_report_html_yaml",
      stage_id: "final_report_html_yaml",
      metadata: { final_bundle: COMPLETE_FINAL_BUNDLE_FIXTURE },
    });
    expect(bundle).toEqual(COMPLETE_FINAL_BUNDLE_FIXTURE);
  });

  it("falls back to a top-level final_bundle for pre-normalization events", () => {
    const bundle = extractFinalBundleFromEvent({
      event: "stage_blocked",
      stage: "final_report_html_yaml",
      final_bundle: COMPLETE_FINAL_BUNDLE_FIXTURE,
    });
    expect(bundle).toEqual(COMPLETE_FINAL_BUNDLE_FIXTURE);
  });

  it("ignores events from other stages and events without a bundle", () => {
    expect(
      extractFinalBundleFromEvent({
        event: "stage_completed",
        stage: "llm_council",
        metadata: { final_bundle: COMPLETE_FINAL_BUNDLE_FIXTURE },
      }),
    ).toBeNull();
    expect(
      extractFinalBundleFromEvent({ event: "stage_completed", stage: "final_report_html_yaml" }),
    ).toBeNull();
  });
});

describe("finalBundleListSections", () => {
  it("keeps every list field visible with explicit empty copy", () => {
    const sections = finalBundleListSections(parseFinalBundle({ ...COMPLETE_FINAL_BUNDLE_FIXTURE, central_claims: [], source_ids: [], evidence_ids: [], open_gaps: [] }));

    expect(sections.map((section) => section.field).sort()).toEqual(
      ["central_claims", "evidence_ids", "open_gaps", "source_ids"].sort(),
    );
    for (const section of sections) {
      expect(section.items).toEqual([]);
      expect(section.emptyCopy.length).toBeGreaterThan(0);
    }
  });
});
