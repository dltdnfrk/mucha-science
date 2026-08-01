import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import {
  buildDiscoveredSourceMap,
  buildKnowledgeGaps,
  type DiscoveredSource,
  type KnowledgeGap,
} from "../components/SourceDiscoveryPanel";
import type { BackendEvent } from "../lib/tauriClient";
import { updateResearchContractFromEvent } from "./runProgressEventValues";
import type { RuntimeEvidence } from "./runProgressInteractionTypes";
import {
  normalizeResearchActivity,
  normalizeResearchQualityReadyActivity,
} from "./runProgressResearchNormalization";
import {
  researchActivityCopy,
  researchProgressStage,
} from "./runProgressResearchPresentation";
import { isStage, STAGES } from "./runProgressStages";
import type {
  ResearchActivity,
  ResearchContractState,
  Stage,
  StageState,
} from "./runProgressTypes";

export type RuntimeEventContext = {
  readonly runErrorRef: MutableRefObject<string | null>;
  readonly failRun: (message: string) => void;
  readonly setStages: Dispatch<SetStateAction<Record<Stage, StageState>>>;
  readonly setRunWarnings: Dispatch<SetStateAction<string[]>>;
  readonly setInterviewSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setHitlSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setRuntimeEvidence: Dispatch<SetStateAction<RuntimeEvidence | null>>;
  readonly setHasReceivedHeartbeat: Dispatch<SetStateAction<boolean>>;
  readonly setResearchActivity: Dispatch<SetStateAction<ResearchActivity[]>>;
  readonly setDiscoveredSources: Dispatch<SetStateAction<Map<string, DiscoveredSource>>>;
  readonly setKnowledgeGaps: Dispatch<SetStateAction<KnowledgeGap[]>>;
};

export function updateResearchContract(
  event: BackendEvent,
  setResearchContract: Dispatch<SetStateAction<ResearchContractState>>,
): void {
  if (
    event.research_session_id !== undefined
    || event.app_run_id !== undefined
    || event.memory_policy !== undefined
    || event.imported_knowledge_refs !== undefined
  ) {
    setResearchContract((previous) => updateResearchContractFromEvent(previous, event));
  }
}

export function handleRuntimeEvent(event: BackendEvent, context: RuntimeEventContext): boolean {
  if (event.event === "error") {
    const message = String(event.message ?? "") || "오류가 발생했어요.";
    if (message.startsWith("python pipeline exited with") && context.runErrorRef.current) {
      context.setRunWarnings((previous) =>
        [message, ...previous.filter((item) => item !== message)].slice(0, 3),
      );
    } else {
      context.failRun(message);
    }
    context.setInterviewSubmitting(false);
    context.setHitlSubmitting(false);
    context.setStages((previous) => {
      const next = { ...previous };
      const active = STAGES.find((stage) => next[stage].status === "active");
      if (active) {
        next[active] = { ...next[active], status: "error", completedAt: Date.now(), message };
      }
      return next;
    });
    return true;
  }
  if (event.event === "warning") {
    const message = String(event.message ?? "") || "경고가 발생했어요.";
    context.setRunWarnings((previous) =>
      [message, ...previous.filter((item) => item !== message)].slice(0, 3),
    );
    return true;
  }
  if (event.event === "run_started") {
    context.setStages((previous) => ({
      ...previous,
      intake: {
        ...previous.intake,
        status: previous.intake.status === "completed" ? "completed" : "active",
        startedAt: previous.intake.startedAt ?? Date.now(),
        lastEventAt: Date.now(),
        lastSignal: "run_started",
        message: "Python backend 시작 확인",
      },
    }));
    context.setRuntimeEvidence((previous) => ({
      ...(previous ?? {}),
      runId: String(event.run_id ?? ""),
      startedAt: String(event.started_at ?? ""),
      pythonPid: Number(event.python_pid ?? 0) || undefined,
      pythonExecutable: String(event.python_executable ?? ""),
      cwd: String(event.cwd ?? ""),
      heartbeatStage: "startup",
      heartbeatDetail: "run_started",
      stalled: false,
    }));
    return true;
  }
  if (event.event === "pipeline_heartbeat") {
    context.setHasReceivedHeartbeat(true);
    const stage = isStage(event.stage) ? event.stage : null;
    if (stage) {
      context.setStages((previous) => {
        const current = previous[stage];
        if (current.status === "completed" || current.status === "error") return previous;
        return {
          ...previous,
          [stage]: {
            ...current,
            status: current.status === "pending" ? "active" : current.status,
            startedAt: current.startedAt ?? Date.now(),
            lastEventAt: Date.now(),
            lastSignal: event.detail ? `heartbeat · ${String(event.detail)}` : "heartbeat",
            message: "실행 중 · heartbeat 수신",
          },
        };
      });
    }
    context.setRuntimeEvidence((previous) => ({
      ...(previous ?? {}),
      runId: String(event.run_id ?? previous?.runId ?? ""),
      pythonPid: Number(event.python_pid ?? previous?.pythonPid ?? 0) || undefined,
      pythonExecutable: String(event.python_executable ?? previous?.pythonExecutable ?? ""),
      heartbeatStage: String(event.stage ?? ""),
      heartbeatDetail: String(event.detail ?? ""),
      heartbeatElapsedSec: Number(event.elapsed_sec ?? 0) || undefined,
      stalled: false,
    }));
    return true;
  }
  if (event.event !== "research_progress" && event.event !== "research_quality_ready") return false;
  const activity = event.event === "research_progress"
    ? normalizeResearchActivity(event)
    : normalizeResearchQualityReadyActivity(event);
  if (!activity) return true;
  const copy = researchActivityCopy(activity);
  context.setStages((previous) => {
    if (event.event === "research_progress") {
      const targetStage = researchProgressStage(event, activity);
      return {
        ...previous,
        [targetStage]: {
          ...previous[targetStage],
          status: previous[targetStage].status === "completed" ? "completed" : "active",
          startedAt: previous[targetStage].startedAt ?? Date.now(),
          lastEventAt: Date.now(),
          lastSignal: copy.signal,
          message: copy.message,
        },
      };
    }
    return {
      ...previous,
      evidence: {
        ...previous.evidence,
        status: "completed",
        completedAt: Date.now(),
        durationMs: previous.evidence.startedAt
          ? Date.now() - previous.evidence.startedAt
          : previous.evidence.durationMs,
        lastEventAt: Date.now(),
        lastSignal: copy.signal,
        message: copy.message,
      },
      finalize: {
        ...previous.finalize,
        status: "completed",
        startedAt: previous.finalize.startedAt ?? Date.now(),
        completedAt: Date.now(),
        lastEventAt: Date.now(),
        lastSignal: "research_quality_ready",
        message: "Research quality-first bounded run complete",
      },
    };
  });
  context.setResearchActivity((previous) => [
    activity,
    ...previous.filter((item) => item.id !== activity.id),
  ].slice(0, 8));
  if (event.event === "research_progress") {
    context.setDiscoveredSources((previous) => buildDiscoveredSourceMap(previous, activity));
    context.setKnowledgeGaps((previous) => buildKnowledgeGaps(previous, activity));
  }
  return true;
}
