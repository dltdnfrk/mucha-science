import { formatElapsed, STAGE_LABEL, STAGES } from "./runProgressStages";
import type { RuntimeEvidence } from "./runProgressInteractionTypes";
import type { Stage, StageState } from "./runProgressTypes";

type RunProgressStatusProps = {
  readonly completedCount: number;
  readonly totalProgress: number;
  readonly runError: string | null;
  readonly activeStage?: Stage;
  readonly latestStage: Stage;
  readonly latestStageState: StageState;
  readonly liveStatusLabel: string;
  readonly liveDetail: string;
  readonly liveSignalAge: string;
  readonly runtimeEvidence: RuntimeEvidence | null;
};

export function RunProgressStatus(props: RunProgressStatusProps) {
  const {
    completedCount,
    totalProgress,
    runError,
    activeStage,
    latestStage,
    latestStageState,
    liveStatusLabel,
    liveDetail,
    liveSignalAge,
    runtimeEvidence,
  } = props;
  return (
    <>
      <div className="fade-in mb-6 flex items-center gap-3">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-white transition-all duration-500"
            style={{ width: `${totalProgress}%` }}
          />
        </div>
        <span className="font-mono text-xs text-secondary">
          {completedCount}/{STAGES.length}
        </span>
      </div>
      <div className={`fade-in mb-6 overflow-hidden rounded-lg border px-4 py-4 shadow-[var(--shadow-paper)] ${
        runError
          ? "border-red-500/20 bg-red-500/5"
          : activeStage
          ? "border-emerald-400/20 bg-emerald-400/5"
          : "border-white/5 bg-white/[0.02]"
      }`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              {!runError && activeStage && (
                <span className="relative flex h-2.5 w-2.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-300 opacity-60" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-300" />
                </span>
              )}
              <span className="text-[11px] font-semibold uppercase tracking-wider text-secondary">
                Run
              </span>
              <span className={`min-w-[120px] max-w-[160px] truncate rounded-full border px-2 py-0.5 text-center font-mono text-[10px] uppercase tracking-[0.08em] ${
                runError
                  ? "border-red-400/20 bg-red-400/10 text-red-200"
                  : activeStage
                  ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-100"
                  : "border-white/10 bg-black/20 text-tertiary"
              }`}>
                {liveStatusLabel}
              </span>
            </div>
            <p className="break-words text-sm leading-relaxed text-white">
              {STAGE_LABEL[latestStage]} · {liveDetail}
            </p>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-tertiary">
              {latestStageState.lastSignal && (
                <span className="font-mono">signal {latestStageState.lastSignal}</span>
              )}
              {liveSignalAge && <span>last signal {liveSignalAge} 전</span>}
              {runtimeEvidence?.lastEventElapsedMs !== undefined
                && runtimeEvidence.lastEventElapsedMs !== null && (
                <span>backend event age {formatElapsed(runtimeEvidence.lastEventElapsedMs)}</span>
              )}
              {runtimeEvidence?.runtimeAgeMs !== undefined && runtimeEvidence.runtimeAgeMs !== null && (
                <span>runtime age {formatElapsed(runtimeEvidence.runtimeAgeMs)}</span>
              )}
            </div>
          </div>
          <div className="shrink-0 rounded-md border border-white/10 bg-black/20 px-3 py-2 text-right">
            <p className="font-mono text-lg text-white">{completedCount}/{STAGES.length}</p>
            <p className="text-[10px] uppercase tracking-wider text-tertiary">steps done</p>
          </div>
        </div>
      </div>
    </>
  );
}
