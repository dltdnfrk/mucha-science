import type { BackendEvent } from "../lib/tauriClient";
import { parseJsonRecord, stringList } from "./runProgressEventValues";
import type {
  DeepInterviewArtifacts,
  DeepInterviewDocumentArtifact,
  HitlPrompt,
  InterviewClarity,
  InterviewPrompt,
  PromptOption,
} from "./runProgressInteractionTypes";

function normalizePromptOptions(value: unknown): PromptOption[] {
  if (!Array.isArray(value)) return [];
  return value.map((raw, index) => {
    const item = parseJsonRecord(raw);
    if (Object.keys(item).length > 0) {
      const key = String(item["key"] ?? String.fromCharCode(65 + index));
      const label = String(item["label"] ?? item["text"] ?? item["value"] ?? key);
      return {
        key,
        label,
        value: String(item["value"] ?? label),
        description: String(item["description"] ?? "").trim(),
      };
    }
    const valueText = String(raw);
    const match = valueText.match(/^([A-D])[\).\s-]+(.+)$/i);
    if (match?.[1] && match[2]) {
      return { key: match[1].toUpperCase(), label: match[2], value: valueText };
    }
    return { key: String.fromCharCode(65 + index), label: valueText, value: valueText };
  });
}

export function isDeepInterviewSignal(
  id?: string,
  total?: number,
  clarity?: InterviewClarity,
): boolean {
  return Boolean((id && /^Q[1-6]_/.test(id)) || total === 6 || clarity);
}

function normalizeInterviewClarity(raw: Readonly<Record<string, unknown>>): InterviewClarity {
  return {
    phase: String(raw["phase"] ?? ""),
    mode: String(raw["mode"] ?? ""),
    researchType: String(raw["research_type"] ?? ""),
    rationale: String(raw["rationale"] ?? ""),
    coverageScore: Number(raw["coverage_score"] ?? 0) || 0,
    ambiguityScore: Number(raw["ambiguity_score"] ?? 0) || 0,
    missingDimensions: stringList(raw["missing_dimensions"]),
    focusDimension: String(raw["focus_dimension"] ?? ""),
    focusLabel: String(raw["focus_label"] ?? ""),
    focusQuestion: String(raw["focus_question"] ?? ""),
    round: Number(raw["round"] ?? 0) || undefined,
    total: Number(raw["total"] ?? 0) || undefined,
  };
}

export function normalizeInterviewPrompt(event: BackendEvent): InterviewPrompt | null {
  const data = parseJsonRecord(event.data);
  const id = String(event.q_id ?? event.question_id ?? data["q_id"] ?? data["question_id"] ?? "Q1");
  const text = String(event.text ?? event.prompt ?? data["text"] ?? data["prompt"] ?? "").trim();
  if (!text) return null;
  const index = Number(event.index ?? data["index"] ?? 0) || undefined;
  const total = Number(event.total ?? data["total"] ?? 0) || undefined;
  const clarityRaw = parseJsonRecord(data["deep_interview"]);
  const clarity = Object.keys(clarityRaw).length > 0
    ? normalizeInterviewClarity(clarityRaw)
    : undefined;
  const counsellingRaw = parseJsonRecord(data["counselling"]);
  const isDeepPrompt = isDeepInterviewSignal(id, total, clarity);
  return {
    id,
    header: isDeepPrompt
      ? "Deep Interview"
      : String(event.header ?? data["header"] ?? "Interview input required"),
    text,
    options: normalizePromptOptions(event.options ?? data["options"]),
    allowOther:
      isDeepPrompt || (event.allow_other !== false && data["allow_other"] !== false),
    multiSelect:
      !isDeepPrompt
      && (
        event.multiSelect === true
        || event.multi_select === true
        || data["multiSelect"] === true
        || data["multi_select"] === true
      ),
    preview: String(event.preview ?? data["preview"] ?? "").trim() || undefined,
    index,
    total,
    clarity,
    counselling: Object.keys(counsellingRaw).length > 0
      ? {
          mode: String(counsellingRaw["mode"] ?? event.counselling_mode ?? ""),
          rationale: String(counsellingRaw["rationale"] ?? event.counselling_rationale ?? ""),
          referenceInsights: stringList(
            counsellingRaw["reference_insights"] ?? event.reference_insights,
          ),
          assumptionsToTest: stringList(
            counsellingRaw["assumptions_to_test"] ?? event.assumptions_to_test,
          ),
          prdImpact: String(counsellingRaw["prd_impact"] ?? event.prd_impact ?? ""),
          provider: String(counsellingRaw["provider"] ?? ""),
          model: String(counsellingRaw["model"] ?? ""),
        }
      : undefined,
  };
}

export function normalizeDeepInterviewProgress(event: BackendEvent): InterviewClarity {
  return normalizeInterviewClarity(Object.fromEntries(Object.entries(event)));
}

export function normalizeDeepInterviewArtifacts(
  event: BackendEvent,
): DeepInterviewArtifacts | null {
  const data = parseJsonRecord(event.data);
  const rawManifest = Array.isArray(data["document_manifest"]) ? data["document_manifest"] : [];
  const manifest = rawManifest
    .map((raw): DeepInterviewDocumentArtifact | null => {
      const item = parseJsonRecord(raw);
      const path = String(item["path"] ?? "").trim();
      if (!path) return null;
      return {
        path,
        title: String(item["title"] ?? path),
        chars: Number(item["chars"] ?? 0) || 0,
        preview: String(item["preview"] ?? "").trim(),
      };
    })
    .filter((item): item is DeepInterviewDocumentArtifact => item !== null);
  const outputs = Array.isArray(event.document_outputs)
    ? event.document_outputs.map((item) => String(item)).filter(Boolean)
    : manifest.map((item) => item.path);
  const evidenceMarkers = stringList(event.evidence_markers);
  if (outputs.length === 0 && manifest.length === 0) return null;
  return {
    workflow: String(event.workflow ?? data["workflow"] ?? "show-me-the-prd"),
    commit: String(event.workflow_commit ?? data["commit"] ?? ""),
    documentCount: Number(event.document_count ?? outputs.length) || outputs.length,
    outputs,
    evidenceMarkers,
    manifest,
  };
}

export function normalizeHitlPrompt(event: BackendEvent): HitlPrompt | null {
  const data = parseJsonRecord(event.data);
  const gate = String(event.gate ?? data["gate"] ?? "").trim();
  if (!gate) return null;
  const options = normalizePromptOptions(event.options ?? data["options"]);
  const payload = parseJsonRecord(data["payload"]);
  return {
    gate,
    title: String(event.title ?? data["title"] ?? `${gate} 승인`),
    prompt: String(event.prompt ?? data["prompt"] ?? "계속 진행하려면 승인하세요."),
    preview: String(event.preview ?? data["preview"] ?? "").trim() || undefined,
    payload: Object.keys(payload).length > 0 ? payload : undefined,
    options: options.length > 0
      ? options
      : [{
          key: "approve",
          label: "승인하고 계속",
          value: "approved",
          description: "현재 내용을 승인하고 다음 단계로 진행합니다.",
        }],
  };
}

export function hitlEvidenceRefs(prompt: HitlPrompt): unknown {
  if (prompt.gate !== "evidence") return undefined;
  return prompt.payload?.["evidence_refs"];
}
