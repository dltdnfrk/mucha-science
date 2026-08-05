import type { PendingResearchInteraction } from "../hooks/useResearchPipelineBridge";
import type { ResearchConversationSession } from "./researchConversation";
import type { ResearchActivity } from "./researchActivity";
import type { ResearchActivityProjection } from "./researchActivity";
import {
  emptyResearchActivity,
  sanitizeResearchActivityReferences,
} from "./researchActivity";
import { reduceResearchActivity } from "./researchActivityReducer";
import type {
  PersistedTurnRuntime,
  ResearchConversationSummary,
} from "./researchConversationStorage";
import type { SkippedSource, SourceExecutionProfile } from "./sourceConnections";

export type ResearchTurnRuntime = PersistedTurnRuntime & {
  readonly activity?: ResearchActivity;
  readonly cancellationRequested?: boolean;
  readonly error?: string;
  readonly skippedSources?: readonly SkippedSource[];
};

export interface ResearchConversationController {
  readonly activeTurnId?: string;
  readonly composerError?: string;
  readonly conversationSummaries: readonly ResearchConversationSummary[];
  readonly isRunning: boolean;
  readonly pendingInteraction?: PendingResearchInteraction;
  readonly runtimeByTurn: Readonly<Record<string, ResearchTurnRuntime>>;
  readonly session: ResearchConversationSession;
  readonly answerInteraction: (optionKey?: string, freeText?: string) => Promise<void>;
  readonly cancelTurn: (turnId: string) => Promise<void>;
  readonly deleteConversation: (sessionId: string) => boolean;
  readonly exportTurn: (turnId: string) => void;
  readonly newConversation: () => boolean;
  readonly reopenApproval: (turnId: string) => void;
  readonly resumeWithComment: (turnId: string, comment: string) => Promise<boolean>;
  readonly submit: (prompt: string) => Promise<boolean>;
  readonly switchConversation: (sessionId: string) => boolean;
}

export type UseResearchConversationOptions = {
  readonly buildSourceExecutionProfile: () => SourceExecutionProfile;
};

export type ResearchConversationLoadRecovery = {
  readonly composerError?: string;
  readonly runtimeByTurn: Readonly<Record<string, ResearchTurnRuntime>>;
};

const INTERRUPTED_RESEARCH_RECOVERY_MESSAGE =
  "이전 연구 실행의 시작 상태를 복구할 수 없습니다. 새 대화를 만들거나 다른 대화로 전환하세요.";

export function stripTransientRuntime(
  runtimeByTurn: Readonly<Record<string, ResearchTurnRuntime>>,
): Readonly<Record<string, PersistedTurnRuntime>> {
  return Object.fromEntries(Object.entries(runtimeByTurn).map(([turnId, runtime]) => [
    turnId,
    {
      ...(runtime.activity === undefined ? {} : {
        activity: sanitizeResearchActivityReferences(runtime.activity),
      }),
      ...(runtime.completedAt === undefined ? {} : { completedAt: runtime.completedAt }),
      ...(runtime.generation === undefined ? {} : { generation: runtime.generation }),
      ...(runtime.skippedSources === undefined ? {} : { skippedSources: runtime.skippedSources }),
      startedAt: runtime.startedAt,
      status: runtime.status,
    },
  ]));
}

export function projectTurnActivity(
  runtimeByTurn: Readonly<Record<string, ResearchTurnRuntime>>,
  turnId: string,
  projections: readonly ResearchActivityProjection[],
): Readonly<Record<string, ResearchTurnRuntime>> {
  const runtime = runtimeByTurn[turnId];
  if (!runtime) return runtimeByTurn;
  return {
    ...runtimeByTurn,
    [turnId]: {
      ...runtime,
      activity: reduceResearchActivity(
        runtime.activity ?? emptyResearchActivity(),
        projections,
      ),
    },
  };
}

export function setTurnCancellationRequested(
  runtimeByTurn: Readonly<Record<string, ResearchTurnRuntime>>,
  turnId: string,
  cancellationRequested: boolean,
): Readonly<Record<string, ResearchTurnRuntime>> {
  const runtime = runtimeByTurn[turnId];
  return runtime
    ? { ...runtimeByTurn, [turnId]: { ...runtime, cancellationRequested } }
    : runtimeByTurn;
}

export function canChangeResearchConversation(
  activeTurnId: string | undefined,
  runtimeByTurn: Readonly<Record<string, ResearchTurnRuntime>>,
): boolean {
  return activeTurnId === undefined
    && !Object.values(runtimeByTurn).some((runtime) => runtime.status === "running");
}

export function recoverUnresumableResearchTurns(
  runtimeByTurn: Readonly<Record<string, ResearchTurnRuntime>>,
): ResearchConversationLoadRecovery {
  const recoveredAt = Date.now();
  const nextRuntimeByTurn: Record<string, ResearchTurnRuntime> = {};
  let recovered = false;
  for (const [turnId, runtime] of Object.entries(runtimeByTurn)) {
    if (runtime.status === "running" && runtime.generation === undefined) {
      nextRuntimeByTurn[turnId] = {
        ...runtime,
        completedAt: recoveredAt,
        error: INTERRUPTED_RESEARCH_RECOVERY_MESSAGE,
        status: "error",
      };
      recovered = true;
    } else {
      nextRuntimeByTurn[turnId] = runtime;
    }
  }
  return recovered
    ? {
        composerError: INTERRUPTED_RESEARCH_RECOVERY_MESSAGE,
        runtimeByTurn: nextRuntimeByTurn,
      }
    : { runtimeByTurn };
}
