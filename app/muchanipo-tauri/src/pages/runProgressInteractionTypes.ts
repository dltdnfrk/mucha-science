export type CouncilActivity = {
  readonly id: string;
  readonly kind:
    | "round_start"
    | "turn"
    | "token"
    | "round_done"
    | "provider_call_start"
    | "provider_call_done"
    | "provider_call_timeout"
    | "provider_call_error";
  readonly round?: number;
  readonly layer?: string;
  readonly persona?: string;
  readonly councilStage?: string;
  readonly text?: string;
  readonly provider?: string;
  readonly providerRoute?: string;
  readonly model?: string;
  readonly score?: number;
  readonly responseChars?: number;
  readonly activePersonaCount?: number;
  readonly activePersonaIds?: readonly string[];
  readonly visualizationSource?: string;
  readonly visualizerModel?: string;
  readonly timeoutSec?: number;
  readonly elapsedSec?: number;
  readonly errorClass?: string;
  readonly blocksProductPass?: boolean;
};

export type StudioProvenance = {
  readonly studioId?: string;
  readonly studioModel?: string;
  readonly studioBrief?: string;
};

export type InterviewCounselling = {
  readonly mode?: string;
  readonly rationale?: string;
  readonly referenceInsights: readonly string[];
  readonly assumptionsToTest: readonly string[];
  readonly prdImpact?: string;
  readonly provider?: string;
  readonly model?: string;
};

export type PromptOption = {
  readonly key: string;
  readonly label: string;
  readonly value: string;
  readonly description?: string;
};

export type InterviewPrompt = {
  readonly id: string;
  readonly header: string;
  readonly text: string;
  readonly options: readonly PromptOption[];
  readonly allowOther: boolean;
  readonly multiSelect: boolean;
  readonly preview?: string;
  readonly index?: number;
  readonly total?: number;
  readonly clarity?: InterviewClarity;
  readonly counselling?: InterviewCounselling;
};

export type HitlPrompt = {
  readonly gate: string;
  readonly title: string;
  readonly prompt: string;
  readonly preview?: string;
  readonly options: readonly PromptOption[];
  readonly payload?: Readonly<Record<string, unknown>>;
};

export type InterviewClarity = {
  readonly phase?: string;
  readonly mode?: string;
  readonly researchType?: string;
  readonly rationale?: string;
  readonly coverageScore?: number;
  readonly ambiguityScore?: number;
  readonly missingDimensions: readonly string[];
  readonly focusDimension?: string;
  readonly focusLabel?: string;
  readonly focusQuestion?: string;
  readonly round?: number;
  readonly total?: number;
};

export type DeepInterviewDocumentArtifact = {
  readonly path: string;
  readonly title: string;
  readonly chars: number;
  readonly preview: string;
};

export type DeepInterviewArtifacts = {
  readonly workflow: string;
  readonly commit: string;
  readonly documentCount: number;
  readonly outputs: readonly string[];
  readonly evidenceMarkers: readonly string[];
  readonly manifest: readonly DeepInterviewDocumentArtifact[];
};

export type RuntimeEvidence = {
  readonly runId?: string;
  readonly startedAt?: string;
  readonly pythonPid?: number;
  readonly pythonExecutable?: string;
  readonly cwd?: string;
  readonly heartbeatStage?: string;
  readonly heartbeatDetail?: string;
  readonly heartbeatElapsedSec?: number;
  readonly childPid?: number | null;
  readonly appBinaryPath?: string | null;
  readonly workspaceRoot?: string;
  readonly runtimeAgeMs?: number | null;
  readonly lastEventElapsedMs?: number | null;
  readonly stalled?: boolean;
};

export type BrowserPersonaRow = {
  readonly id: string;
  readonly name: string;
  readonly role: string;
  readonly provenance: string;
  readonly note: string;
};
