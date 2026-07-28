export type Stage =
  | "intake"
  | "interview"
  | "targeting"
  | "research"
  | "evidence"
  | "council"
  | "report"
  | "vault"
  | "agents"
  | "finalize";

export type StageState = {
  readonly status: "pending" | "active" | "completed" | "error";
  readonly message: string;
  readonly startedAt?: number;
  readonly completedAt?: number;
  readonly durationMs?: number;
  readonly lastEventAt?: number;
  readonly lastSignal?: string;
  readonly referenceProjects?: readonly string[];
  readonly artifactKeys?: readonly string[];
};

export type TokenCard = {
  readonly persona: string;
  readonly text: string;
  readonly layer?: string;
  readonly round?: number;
};

export type ResearchQueryRoute = {
  readonly query?: string;
  readonly facetId?: string;
  readonly purpose?: string;
  readonly sourceClass?: string;
  readonly intent?: string;
  readonly backend?: string;
  readonly continueReason?: string;
  readonly authorityRequirement?: string;
  readonly acceptanceRules?: readonly string[];
};

export type ResearchActivity = {
  readonly id: string;
  readonly status:
    | "research_plan_ready"
    | "searching"
    | "source_found"
    | "source_evaluated"
    | "knowledge_gap"
    | "facet_summary"
    | "source_audit_gate"
    | "claim_evidence_gate"
    | "max_plus_benchmark_scored"
    | "research_quality_ready"
    | "done";
  readonly query?: string;
  readonly queryIndex?: number;
  readonly queryCount?: number;
  readonly backends?: readonly string[];
  readonly sourceTitle?: string;
  readonly sourceUrl?: string;
  readonly sourceGrade?: string;
  readonly sourceKind?: string;
  readonly accessStatus?: string;
  readonly accepted?: boolean;
  readonly facetIds?: readonly string[];
  readonly relevanceScore?: number;
  readonly reason?: string;
  readonly facetId?: string;
  readonly message?: string;
  readonly acceptedCount?: number;
  readonly minAcceptedSources?: number;
  readonly gapCount?: number;
  readonly acceptedSourceCount?: number;
  readonly rejectedSourceCount?: number;
  readonly passed?: boolean;
  readonly decision?: string;
  readonly supportedClaimCount?: number;
  readonly partialClaimCount?: number;
  readonly unsupportedClaimCount?: number;
  readonly supportedRatio?: number;
  readonly benchmarkId?: string;
  readonly metrics?: Readonly<Record<string, number>>;
  readonly queries?: readonly string[];
  readonly queryRoutes?: readonly ResearchQueryRoute[];
  readonly topicAnchor?: string;
  readonly purpose?: string;
  readonly sourceClass?: string;
  readonly intent?: string;
  readonly backend?: string;
  readonly continueReason?: string;
  readonly authorityRequirement?: string;
  readonly acceptanceRules?: readonly string[];
};

export type ResearchPlanDisplayRow = {
  readonly query: string;
  readonly routeDetails: readonly string[];
  readonly continueReason?: string;
  readonly authorityRequirement?: string;
  readonly acceptanceRules: readonly string[];
};

export type ResearchContractState = {
  readonly researchSessionId?: string;
  readonly appRunId?: string;
  readonly memoryPolicy?: string;
  readonly importedKnowledgeRefs: readonly string[];
};

export const EMPTY_RESEARCH_CONTRACT: ResearchContractState = {
  importedKnowledgeRefs: [],
};
