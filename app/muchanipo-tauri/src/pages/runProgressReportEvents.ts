import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";
import type { BackendEvent } from "../lib/tauriClient";
import { deleteRun, markRunDone } from "../lib/runsIndex";
import type { HitlPrompt, InterviewPrompt } from "./runProgressInteractionTypes";
import { normalizeResearchQualityReadyActivity } from "./runProgressResearchNormalization";
import {
  persistPendingReport,
  persistReportReadiness,
  promotePendingReport,
  readStoredReportReadiness,
  type ReportReadiness,
} from "./runProgressStorage";
import { STAGES } from "./runProgressStages";
import type { ResearchActivity, Stage, StageState } from "./runProgressTypes";

export type ReportEventContext = {
  readonly runId?: string;
  readonly runErrorRef: MutableRefObject<string | null>;
  readonly chunkKeysRef: MutableRefObject<Set<string>>;
  readonly finalReportReceivedRef: MutableRefObject<boolean>;
  readonly navigationTimers: Set<number>;
  readonly isMounted: () => boolean;
  readonly navigate: NavigateFunction;
  readonly setStages: Dispatch<SetStateAction<Record<Stage, StageState>>>;
  readonly setReportPreview: Dispatch<SetStateAction<string>>;
  readonly setFinalReport: Dispatch<SetStateAction<string>>;
  readonly setReportReadiness: Dispatch<SetStateAction<ReportReadiness>>;
  readonly setInterviewSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setInterviewPrompt: Dispatch<SetStateAction<InterviewPrompt | null>>;
  readonly setHitlSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setHitlPrompt: Dispatch<SetStateAction<HitlPrompt | null>>;
  readonly setResearchActivity: Dispatch<SetStateAction<ResearchActivity[]>>;
};

export function handleReportEvent(event: BackendEvent, context: ReportEventContext): boolean {
  const runId = context.runId;
  if (event.event === "report_chunk" && runId) {
    const chunk = String(event.markdown ?? event.delta ?? "");
    const key = chunk.trim();
    if (
      !key
      || context.finalReportReceivedRef.current
      || context.chunkKeysRef.current.has(key)
    ) return true;
    context.chunkKeysRef.current.add(key);
    context.setStages((previous) => ({
      ...previous,
      report: {
        ...previous.report,
        status: previous.report.status === "completed" ? "completed" : "active",
        startedAt: previous.report.startedAt ?? Date.now(),
        lastEventAt: Date.now(),
        lastSignal: `report_chunk · ${event.chapter_no ?? event.title ?? "chapter"}`,
        message: "보고서 chunk 수신",
      },
    }));
    context.setReportPreview((previous) => `${previous}${previous ? "\n\n" : ""}${chunk}`);
    return true;
  }
  if (event.event === "final_report" && runId) {
    const markdown = typeof event.markdown === "string" ? event.markdown : "";
    const reportPath = typeof event.report_path === "string" ? event.report_path : "";
    const vaultPath = typeof event.vault_path === "string" ? event.vault_path : "";
    const chapterCount = typeof event.chapter_count === "number" ? event.chapter_count : 0;
    context.finalReportReceivedRef.current = true;
    context.chunkKeysRef.current.clear();
    context.setStages((previous) => ({
      ...previous,
      report: {
        ...previous.report,
        status: "active",
        startedAt: previous.report.startedAt ?? Date.now(),
        lastEventAt: Date.now(),
        lastSignal: "final_report",
        message: "최종 보고서 수신 · 품질 판정 대기",
      },
    }));
    persistPendingReport(runId, {
      chapterCount,
      markdown,
      reportPath,
      vaultPath,
    });
    const storedReadiness = readStoredReportReadiness(runId);
    if (storedReadiness === "ready" || storedReadiness === "legacy") {
      const promoted = promotePendingReport(runId);
      if (promoted) context.setFinalReport(promoted);
    }
    return true;
  }
  if (event.event !== "done" || !runId || context.runErrorRef.current) return false;
  const qualityReadyActivity = normalizeResearchQualityReadyActivity(event);
  const readiness = persistReportReadiness(
    runId,
    event.research_quality_readiness,
  );
  context.setReportReadiness(readiness);
  const reportCanBeShown = readiness === "ready" || readiness === "legacy";
  if (reportCanBeShown) {
    const promoted = promotePendingReport(runId);
    if (promoted) context.setFinalReport(promoted);
  }
  context.setInterviewSubmitting(false);
  context.setInterviewPrompt(null);
  context.setHitlSubmitting(false);
  context.setHitlPrompt(null);
  context.setStages((previous) => {
    const next = { ...previous };
    for (const stage of STAGES) {
      if (next[stage].status === "active" || stage === "finalize") {
        next[stage] = {
          ...next[stage],
          status: "completed",
          completedAt: Date.now(),
          durationMs: next[stage].startedAt
            ? Date.now() - (next[stage].startedAt ?? Date.now())
            : next[stage].durationMs,
          lastEventAt: Date.now(),
          lastSignal: qualityReadyActivity ? "research_quality_ready" : "done",
          message: qualityReadyActivity
            ? "Research quality-first bounded run complete"
            : "완료 · done event 수신",
        };
      }
    }
    return next;
  });
  if (qualityReadyActivity) {
    context.setResearchActivity((previous) => [
      qualityReadyActivity,
      ...previous.filter((item) => item.id !== qualityReadyActivity.id),
    ].slice(0, 8));
    markRunDone(runId);
    return true;
  }
  if (event.aborted) {
    deleteRun(runId);
    context.navigationTimers.add(window.setTimeout(() => {
      if (context.isMounted()) context.navigate("/");
    }, 300));
    return true;
  }
  markRunDone(runId);
  if (reportCanBeShown) {
    context.navigationTimers.add(window.setTimeout(() => {
      if (context.isMounted()) context.navigate(`/browser/${runId}/report`);
    }, 600));
  }
  return true;
}
