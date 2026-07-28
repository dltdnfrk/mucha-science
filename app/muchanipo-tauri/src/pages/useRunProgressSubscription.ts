import { useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";
import {
  getBufferedEvents,
  getPipelineRuntimeStatus,
  onBackendEvent,
  type BackendEvent,
} from "../lib/tauriClient";
import { listRuns, markRunDone } from "../lib/runsIndex";
import { clearPendingRun, getPendingRunAutostartDecision } from "../lib/pendingRun";
import { hasReadyStoredReport } from "./runProgressStorage";
import {
  handleCouncilEvent,
  type CouncilEventContext,
} from "./runProgressCouncilEvents";
import {
  handleInteractionEvent,
  type InteractionEventContext,
} from "./runProgressInteractionEvents";
import {
  handleReportEvent,
  type ReportEventContext,
} from "./runProgressReportEvents";
import {
  handleRuntimeEvent,
  updateResearchContract,
  type RuntimeEventContext,
} from "./runProgressRuntimeEvents";
import type { RuntimeEvidence } from "./runProgressInteractionTypes";
import type { ResearchContractState } from "./runProgressTypes";

type SubscriptionProps = {
  readonly runId?: string;
  readonly navigate: NavigateFunction;
  readonly failRun: (message: string) => void;
  readonly startRunFromTopic: (topic: string) => Promise<boolean>;
  readonly setResearchContract: Dispatch<SetStateAction<ResearchContractState>>;
  readonly setRuntimeEvidence: Dispatch<SetStateAction<RuntimeEvidence | null>>;
  readonly runtimeContext: RuntimeEventContext;
  readonly interactionContext: InteractionEventContext;
  readonly councilContext: CouncilEventContext;
  readonly reportContext: Omit<
    ReportEventContext,
    "runId" | "navigationTimers" | "isMounted" | "navigate"
  >;
  readonly chunkKeysRef: MutableRefObject<Set<string>>;
  readonly finalReportReceivedRef: MutableRefObject<boolean>;
};

function runtimeEvidencePatch(
  status: Awaited<ReturnType<typeof getPipelineRuntimeStatus>>,
): Partial<RuntimeEvidence> {
  return {
    runId: status.app_run_id ?? undefined,
    childPid: status.child_pid ?? null,
    appBinaryPath: status.app_binary_path ?? null,
    workspaceRoot: status.workspace_root,
    runtimeAgeMs: status.runtime_age_ms ?? null,
    lastEventElapsedMs: status.last_event_elapsed_ms ?? null,
  };
}

export function useRunProgressSubscription(props: SubscriptionProps): void {
  const unlistenRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let mounted = true;
    const navigationTimers = new Set<number>();
    props.chunkKeysRef.current.clear();
    props.finalReportReceivedRef.current = false;

    const handleEvent = (event: BackendEvent) => {
      if (!mounted) return;
      updateResearchContract(event, props.setResearchContract);
      if (handleRuntimeEvent(event, props.runtimeContext)) return;
      if (handleInteractionEvent(event, props.interactionContext)) return;
      if (handleCouncilEvent(event, props.councilContext)) return;
      handleReportEvent(event, {
        ...props.reportContext,
        runId: props.runId,
        navigationTimers,
        isMounted: () => mounted,
        navigate: props.navigate,
      });
    };

    onBackendEvent(handleEvent, props.runId).then(async (unlisten) => {
      if (!mounted) {
        unlisten();
        return;
      }
      unlistenRef.current = unlisten;
      let replayedEventCount = 0;
      try {
        const history = await getBufferedEvents(props.runId);
        replayedEventCount = history.length;
        for (const event of history) handleEvent(event);
      } catch (error) {
        if (!(error instanceof Error)) throw error;
      }

      if (!props.runId) return;
      try {
        const pendingDecision = getPendingRunAutostartDecision(props.runId);
        const topic = localStorage.getItem(`run:${props.runId}:topic`) || "";
        if (pendingDecision.pending) {
          clearPendingRun(props.runId);
          if (!pendingDecision.canStart) {
            props.failRun(
              pendingDecision.reason === "stale"
                ? "이전 세션의 미완료 실행은 오래되어 자동 시작하지 않았습니다. 다시 시작을 눌러주세요."
                : "이전 세션의 미완료 실행은 안전을 위해 자동 시작하지 않았습니다. 다시 시작을 눌러주세요.",
            );
            return;
          }
          await props.startRunFromTopic(topic);
          return;
        }

        const hasReadyReport = hasReadyStoredReport(props.runId);
        const isRunningEntry = listRuns().some(
          (entry) => entry.runId === props.runId && entry.status === "running",
        );
        let hasRuntimeEvidence = replayedEventCount > 0;
        try {
          const status = await getPipelineRuntimeStatus();
          hasRuntimeEvidence = Boolean(status.running && status.app_run_id === props.runId);
          props.setRuntimeEvidence((previous) => ({
            ...(previous ?? {}),
            ...runtimeEvidencePatch(status),
            runId: status.app_run_id ?? previous?.runId,
          }));
        } catch (error) {
          if (!(error instanceof Error)) throw error;
        }
        if (isRunningEntry && !hasRuntimeEvidence && hasReadyReport) {
          markRunDone(props.runId);
          props.navigate(`/browser/${props.runId}/report`);
          return;
        }
        if (!hasRuntimeEvidence && isRunningEntry && topic.trim()) {
          props.failRun(
            "이전 실행의 백엔드가 종료되었습니다. 자동 재시작하지 않았으니 다시 시작을 눌러주세요.",
          );
        } else if (isRunningEntry && !hasRuntimeEvidence && !hasReadyReport) {
          props.failRun(
            "이전 실행의 백엔드가 종료되어 실행을 계속할 수 없습니다. 다시 시작하세요.",
          );
        }
      } catch (error) {
        props.failRun(error instanceof Error ? error.message : String(error));
      }
    });

    return () => {
      mounted = false;
      navigationTimers.forEach((timerId) => window.clearTimeout(timerId));
      unlistenRef.current?.();
      unlistenRef.current = null;
    };
  }, [props.failRun, props.navigate, props.runId, props.startRunFromTopic]);
}
