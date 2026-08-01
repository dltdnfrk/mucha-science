import { useEffect, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";
import { getPipelineRuntimeStatus } from "../lib/tauriClient";
import { listRuns, markRunDone } from "../lib/runsIndex";
import { STAGES } from "./runProgressStages";
import type { RuntimeEvidence } from "./runProgressInteractionTypes";
import type { Stage, StageState } from "./runProgressTypes";

type PollingProps = {
  readonly runId?: string;
  readonly runError: string | null;
  readonly runErrorRef: MutableRefObject<string | null>;
  readonly navigate: NavigateFunction;
  readonly failRun: (message: string) => void;
  readonly setRuntimeEvidence: Dispatch<SetStateAction<RuntimeEvidence | null>>;
  readonly setRunWarnings: Dispatch<SetStateAction<string[]>>;
  readonly setStages: Dispatch<SetStateAction<Record<Stage, StageState>>>;
};

export function useRunProgressPolling(props: PollingProps): void {
  useEffect(() => {
    if (!props.runId || props.runError) return;
    const runId = props.runId;
    let cancelled = false;

    const checkRuntime = async () => {
      if (cancelled || props.runErrorRef.current) return;
      const entry = listRuns().find((item) => item.runId === runId);
      if (entry?.status !== "running") return;
      let runtimeRunning = true;
      let lastEventElapsedMs: number | null = null;
      try {
        const status = await getPipelineRuntimeStatus();
        runtimeRunning = Boolean(status.running && status.app_run_id === runId);
        lastEventElapsedMs = status.last_event_elapsed_ms ?? null;
        props.setRuntimeEvidence((previous) => ({
          ...(previous ?? {}),
          runId: status.app_run_id ?? previous?.runId,
          childPid: status.child_pid ?? null,
          appBinaryPath: status.app_binary_path ?? null,
          workspaceRoot: status.workspace_root,
          runtimeAgeMs: status.runtime_age_ms ?? null,
          lastEventElapsedMs,
          stalled: Boolean(
            status.running && lastEventElapsedMs !== null && lastEventElapsedMs > 30000
          ),
        }));
      } catch (error) {
        if (!(error instanceof Error)) throw error;
        return;
      }
      if (runtimeRunning && lastEventElapsedMs !== null && lastEventElapsedMs > 30000) {
        const seconds = Math.round(lastEventElapsedMs / 1000);
        const message = lastEventElapsedMs > 120000
          ? `백엔드 이벤트가 2분 넘게 도착하지 않았습니다. 실행이 멈춘 상태일 수 있으니 필요하면 다시 시작을 눌러주세요. (${seconds}초)`
          : `백엔드 이벤트가 ${seconds}초 동안 도착하지 않았습니다. 실행이 멈췄는지 확인 중입니다.`;
        props.setRunWarnings((previous) =>
          [message, ...previous.filter((item) => item !== message)].slice(0, 3),
        );
        return;
      }
      if (runtimeRunning || cancelled || props.runErrorRef.current) return;
      const report = localStorage.getItem(`run:${runId}:report`);
      const reportPath = localStorage.getItem(`run:${runId}:report_path`);
      if (report && reportPath) {
        markRunDone(runId);
        props.navigate(`/browser/${runId}/report`);
        return;
      }
      const message = "백엔드 프로세스가 종료되어 실행을 계속할 수 없습니다. 다시 시작하세요.";
      props.failRun(message);
      props.setStages((previous) => {
        const next = { ...previous };
        const active = STAGES.find((stage) => next[stage].status === "active");
        if (active) {
          next[active] = { ...next[active], status: "error", completedAt: Date.now(), message };
        }
        return next;
      });
    };

    const timer = window.setInterval(() => void checkRuntime(), 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [props.failRun, props.navigate, props.runError, props.runId]);
}
