import type { BrowserPersonaRow, RuntimeEvidence } from "./runProgressInteractionTypes";
import type { Stage, StageState } from "./runProgressTypes";

export const STAGES: readonly Stage[] = [
  "intake",
  "interview",
  "targeting",
  "research",
  "evidence",
  "council",
  "report",
  "vault",
  "agents",
  "finalize",
];

export const STAGE_LABEL: Readonly<Record<Stage, string>> = {
  intake: "아이디어 접수",
  interview: "인터뷰",
  targeting: "타겟팅",
  research: "리서치",
  evidence: "증거 수집",
  council: "심의",
  report: "보고서",
  vault: "Vault 저장",
  agents: "에이전트 기록",
  finalize: "완료",
};

export const PHASE_TO_STAGE: Readonly<Record<string, Stage>> = {
  STARTUP: "intake",
  INTERVIEW: "interview",
  COUNCIL: "council",
  REPORT: "report",
};

export function isBackendGoneError(message: string): boolean {
  return /pipeline is not running|failed to write backend action|broken pipe/i.test(message);
}

export function formatElapsed(ms?: number | null): string {
  if (ms === undefined || ms === null) return "";
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

export function signalAge(now: number, lastEventAt?: number): string {
  if (!lastEventAt) return "";
  return formatElapsed(now - lastEventAt);
}

export function isStage(value: unknown): value is Stage {
  return typeof value === "string" && STAGES.some((stage) => stage === value);
}

export function initialStageState(): Record<Stage, StageState> {
  return {
    intake: { status: "pending", message: "" },
    interview: { status: "pending", message: "" },
    targeting: { status: "pending", message: "" },
    research: { status: "pending", message: "" },
    evidence: { status: "pending", message: "" },
    council: { status: "pending", message: "" },
    report: { status: "pending", message: "" },
    vault: { status: "pending", message: "" },
    agents: { status: "pending", message: "" },
    finalize: { status: "pending", message: "" },
  };
}

export function clearRunScopedSessionKeys(runId: string): void {
  const keysToRemove: string[] = [];
  for (let index = 0; index < sessionStorage.length; index += 1) {
    const key = sessionStorage.key(index);
    if (!key) continue;
    if (
      key.startsWith(`muchanipo:auto-answer:${runId}:`)
      || key.startsWith(`muchanipo:auto-approve:${runId}:`)
    ) {
      keysToRemove.push(key);
    }
  }
  for (const key of keysToRemove) sessionStorage.removeItem(key);
}

export function deriveLiveE2eStatus({
  runId,
  runtimeRunId,
  runtimeHeartbeatStage,
  hasVisibleBackendHeartbeat,
}: {
  readonly runId?: string;
  readonly runtimeRunId?: string;
  readonly runtimeHeartbeatStage?: string;
  readonly hasVisibleBackendHeartbeat: boolean;
}): string {
  if ((runtimeRunId === runId && runtimeHeartbeatStage) || hasVisibleBackendHeartbeat) {
    return "Backend run signals observed";
  }
  return "Not proven in this UI session";
}

export type RunProgressSummary = {
  readonly completedCount: number;
  readonly activeStage?: Stage;
  readonly latestStage: Stage;
  readonly latestStageState: StageState;
  readonly totalProgress: number;
  readonly runtimeEvidence?: RuntimeEvidence | null;
  readonly personaRows?: readonly BrowserPersonaRow[];
};
