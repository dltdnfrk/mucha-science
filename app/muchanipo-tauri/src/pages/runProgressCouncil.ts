import type { BrowserPersonaRow, CouncilActivity } from "./runProgressInteractionTypes";

export const COUNCIL_STAGE_LABEL: Readonly<Record<string, string>> = {
  individual: "독립 의견",
  peer_review: "상호 검토",
  chairman: "의장 종합",
  digest: "요약",
};

const PERSONA_PROVENANCE_LABELS = {
  samplePool: "Persona sample pool",
  fallbackTemplate: "Fallback template",
  diversitySampling: "Diversity sampling",
  councilProtocol: "Council protocol",
  backendSelected: "Backend selected persona",
} as const;

const BROWSER_PERSONA_FALLBACK_ROWS: readonly BrowserPersonaRow[] = [
  {
    id: "layer-1-direct-user",
    name: "Layer 1 · 직접 사용자",
    role: "Goal을 직접 겪는 사용자",
    provenance: PERSONA_PROVENANCE_LABELS.fallbackTemplate,
    note: "pending backend selection",
  },
  {
    id: "layer-2-ecosystem",
    name: "Layer 2 · 생태계 이해관계자",
    role: "도입, 운영, 비용, 규칙 이해관계자",
    provenance: PERSONA_PROVENANCE_LABELS.samplePool,
    note: "pending backend selection",
  },
  {
    id: "layer-3-contrarian",
    name: "Layer 3 · 교차 분야/반대 전문가",
    role: "반례와 다른 분야 기준 검토",
    provenance: PERSONA_PROVENANCE_LABELS.diversitySampling,
    note: "pending backend selection",
  },
  {
    id: "council-protocol",
    name: "Council protocol",
    role: "심의 순서와 발언 규칙",
    provenance: PERSONA_PROVENANCE_LABELS.councilProtocol,
    note: "protocol label; selected persona ids replace fallback rows when available",
  },
];

export function compactPersonaName(value: string | undefined): string {
  if (!value) return "persona";
  return value.replace(/^persona-/, "P-").replace(/^mirofish-entity-/, "M-");
}

export function browserPersonaRows(personas: readonly string[]): BrowserPersonaRow[] {
  const selected = personas.map((persona, index) => ({
    id: `selected-${persona}-${index}`,
    name: compactPersonaName(persona),
    role: index === 0 ? "selected persona" : "selected council persona",
    provenance: PERSONA_PROVENANCE_LABELS.backendSelected,
    note: "received from council active_persona_ids",
  }));
  return selected.length > 0 ? selected : [...BROWSER_PERSONA_FALLBACK_ROWS];
}

export function pushCouncilActivity(
  previous: readonly CouncilActivity[],
  activity: CouncilActivity,
): CouncilActivity[] {
  const withoutDuplicate = previous.filter((item) => item.id !== activity.id);
  return [activity, ...withoutDuplicate].slice(0, 12);
}
