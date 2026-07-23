// Final report bundle consumption for the Run Progress UI (issue #46).
//
// The backend embeds the complete `final_report_html_yaml_bundle.v1` payload in
// every final-report lifecycle event (see src/pipeline/final_artifact.py and the
// event-only replay gate). This module accounts for EVERY field of that
// contract: each field is either rendered by FinalBundlePanel or intentionally
// hidden (technical envelope fields), and missing/partial/malformed payloads
// degrade to explicit user-facing copy instead of blank UI.

export const FINAL_BUNDLE_CONTRACT = "final_report_html_yaml_bundle.v1";
export const FINAL_REPORT_STAGE_ID = "final_report_html_yaml";

/** Every field of the bundle contract, in contract order. */
export const FINAL_BUNDLE_FIELDS = [
  "schema_version",
  "contract",
  "report_id",
  "title",
  "verdict",
  "central_claims",
  "source_ids",
  "evidence_ids",
  "open_gaps",
  "blockers",
] as const;

/**
 * Technical envelope fields that are intentionally NOT rendered: they identify
 * the payload format, not report content. Kept exported so the field-coverage
 * test proves rendered + hidden === the full contract.
 */
export const FINAL_BUNDLE_HIDDEN_FIELDS = ["schema_version", "contract"] as const;

export const FINAL_BUNDLE_RENDERED_FIELDS = [
  "report_id",
  "title",
  "verdict",
  "central_claims",
  "source_ids",
  "evidence_ids",
  "open_gaps",
  "blockers",
] as const;

export interface FinalBundleBlockerView {
  code: string;
  message: string;
  requiredAction: string;
}

export interface FinalBundleView {
  status: "complete" | "partial" | "malformed";
  reportId: string;
  title: string;
  verdict: "PASS" | "BLOCKED" | "";
  centralClaims: string[];
  sourceIds: string[];
  evidenceIds: string[];
  openGaps: string[];
  blockers: FinalBundleBlockerView[];
  /** Contract fields absent from the payload. */
  missingFields: string[];
  /** Contract fields present but with an unusable shape (kept with a safe default). */
  invalidFields: string[];
}

function stringOrInvalid(value: unknown): { text: string; ok: boolean } {
  if (typeof value === "string") return { text: value, ok: true };
  if (typeof value === "number" || typeof value === "boolean") return { text: String(value), ok: true };
  return { text: "", ok: false };
}

function stringListOrInvalid(value: unknown): { items: string[]; ok: boolean } {
  if (!Array.isArray(value)) return { items: [], ok: false };
  const items = value
    .map((item) => (typeof item === "string" ? item : item == null ? "" : String(item)))
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
  return { items, ok: true };
}

function blockerViews(value: unknown): { items: FinalBundleBlockerView[]; ok: boolean } {
  if (!Array.isArray(value)) return { items: [], ok: false };
  const items: FinalBundleBlockerView[] = [];
  for (const raw of value) {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      const record = raw as Record<string, unknown>;
      items.push({
        code: String(record.code ?? "").trim(),
        message: String(record.message ?? "").trim(),
        requiredAction: String(record.required_action ?? "").trim(),
      });
    } else if (typeof raw === "string" && raw.trim()) {
      items.push({ code: raw.trim(), message: "", requiredAction: "" });
    }
  }
  return { items, ok: true };
}

const MALFORMED_VIEW: Omit<FinalBundleView, "missingFields" | "invalidFields"> = {
  status: "malformed",
  reportId: "",
  title: "",
  verdict: "",
  centralClaims: [],
  sourceIds: [],
  evidenceIds: [],
  openGaps: [],
  blockers: [],
};

/**
 * Tolerant parse of a bundle payload into a render-ready view. Never throws:
 * a non-object payload yields a malformed view; per-field problems downgrade
 * the view to partial with the offending fields listed.
 */
export function parseFinalBundle(value: unknown): FinalBundleView {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { ...MALFORMED_VIEW, missingFields: [...FINAL_BUNDLE_FIELDS], invalidFields: [] };
  }
  const record = value as Record<string, unknown>;
  const missingFields: string[] = [];
  const invalidFields: string[] = [];

  function track<T>(field: (typeof FINAL_BUNDLE_FIELDS)[number], parsed: { ok: boolean } & T): T {
    if (!(field in record)) missingFields.push(field);
    else if (!parsed.ok) invalidFields.push(field);
    return parsed;
  }

  // Hidden envelope fields still count toward completeness.
  for (const field of FINAL_BUNDLE_HIDDEN_FIELDS) {
    if (!(field in record)) missingFields.push(field);
  }

  const reportId = track("report_id", stringOrInvalid(record.report_id));
  const title = track("title", stringOrInvalid(record.title));
  const verdictRaw = track("verdict", stringOrInvalid(record.verdict));
  const centralClaims = track("central_claims", stringListOrInvalid(record.central_claims));
  const sourceIds = track("source_ids", stringListOrInvalid(record.source_ids));
  const evidenceIds = track("evidence_ids", stringListOrInvalid(record.evidence_ids));
  const openGaps = track("open_gaps", stringListOrInvalid(record.open_gaps));
  const blockers = track("blockers", blockerViews(record.blockers));

  const verdictText = verdictRaw.text.trim().toUpperCase();
  const verdict = verdictText === "PASS" ? "PASS" : verdictText === "BLOCKED" ? "BLOCKED" : "";
  if (verdictRaw.ok && verdictText && !verdict) invalidFields.push("verdict");

  return {
    status: missingFields.length === 0 && invalidFields.length === 0 ? "complete" : "partial",
    reportId: reportId.text.trim(),
    title: title.text.trim(),
    verdict,
    centralClaims: centralClaims.items,
    sourceIds: sourceIds.items,
    evidenceIds: evidenceIds.items,
    openGaps: openGaps.items,
    blockers: blockers.items,
    missingFields,
    invalidFields,
  };
}

/**
 * Pull the embedded bundle payload out of a backend event. Only final-report
 * lifecycle events carry it; both normalized (metadata.final_bundle) and
 * pre-normalization (top-level final_bundle) shapes are accepted.
 */
export function extractFinalBundleFromEvent(event: Record<string, unknown>): unknown | null {
  const stage = String(event.stage_id ?? event.stage ?? "").trim();
  if (stage !== FINAL_REPORT_STAGE_ID) return null;
  const metadata = event.metadata;
  if (metadata && typeof metadata === "object" && !Array.isArray(metadata)) {
    const candidate = (metadata as Record<string, unknown>).final_bundle;
    if (candidate !== undefined && candidate !== null) return candidate;
  }
  if (event.final_bundle !== undefined && event.final_bundle !== null) return event.final_bundle;
  return null;
}

/** User-facing degradation copy; empty string for a complete bundle. */
export function finalBundleDegradationCopy(view: FinalBundleView): string {
  if (view.status === "malformed") {
    return "최종 번들 페이로드를 해석할 수 없습니다. 이벤트 스트림의 final_bundle 형식을 확인하세요.";
  }
  if (view.status === "partial") {
    const parts: string[] = [];
    if (view.missingFields.length > 0) parts.push(`누락 필드: ${view.missingFields.join(", ")}`);
    if (view.invalidFields.length > 0) parts.push(`형식 이상 필드: ${view.invalidFields.join(", ")}`);
    return `최종 번들이 불완전하게 수신되었습니다 (${parts.join(" · ")}). 표시 가능한 항목만 렌더링합니다.`;
  }
  return "";
}

export interface FinalBundleListSection {
  field: (typeof FINAL_BUNDLE_RENDERED_FIELDS)[number];
  label: string;
  items: string[];
  emptyCopy: string;
}

/**
 * Render-ready list sections, one per list field of the contract. Empty lists
 * still render with explicit copy so every field stays visibly accounted for.
 */
export function finalBundleListSections(view: FinalBundleView): FinalBundleListSection[] {
  return [
    { field: "central_claims", label: "핵심 주장", items: view.centralClaims, emptyCopy: "핵심 주장이 없습니다." },
    { field: "evidence_ids", label: "근거 ID", items: view.evidenceIds, emptyCopy: "근거 ID가 없습니다." },
    { field: "source_ids", label: "출처", items: view.sourceIds, emptyCopy: "출처가 없습니다." },
    { field: "open_gaps", label: "미해결 갭", items: view.openGaps, emptyCopy: "미해결 갭이 없습니다." },
  ];
}

/** A complete fixture mirroring the backend contract, used by tests and the dev screen. */
export const COMPLETE_FINAL_BUNDLE_FIXTURE: Record<string, unknown> = {
  schema_version: 1,
  contract: FINAL_BUNDLE_CONTRACT,
  report_id: "brief-fixture",
  title: "Fixture decision report",
  verdict: "PASS",
  central_claims: ["Council-backed final claim", "Follow-on claim"],
  source_ids: ["https://example.test/ev-1"],
  evidence_ids: ["ev-1"],
  open_gaps: ["Quantify pricing sensitivity."],
  blockers: [],
};
