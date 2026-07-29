import type { CouncilActivity } from "./runProgressInteractionTypes";
import { signalAge, STAGE_LABEL, STAGES } from "./runProgressStages";
import type { ResearchActivity, Stage, StageState } from "./runProgressTypes";
import { RunProgressCouncilActivity } from "./RunProgressCouncilActivity";
import { RunProgressResearchActivity } from "./RunProgressResearchActivity";

type StageListProps = {
  readonly stages: Readonly<Record<Stage, StageState>>;
  readonly now: number;
  readonly councilRound: number;
  readonly councilActivity: readonly CouncilActivity[];
  readonly councilPersonas: readonly string[];
  readonly researchActivity: readonly ResearchActivity[];
};

export function RunProgressStageList(props: StageListProps) {
  const { stages, now, councilRound, councilActivity, councilPersonas, researchActivity } = props;
  return (
    <ul className="space-y-px overflow-hidden rounded-lg border border-white/5 shadow-[var(--shadow-paper)]">
      {STAGES.map((stage) => {
        const state = stages[stage];
        const isActive = state.status === "active";
        const isCompleted = state.status === "completed";
        const isError = state.status === "error";
        const lastSignalAge = signalAge(now, state.lastEventAt);
        const proofTone = isActive
          ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-100"
          : isCompleted
          ? "border-white/10 bg-black/20 text-tertiary"
          : isError
          ? "border-red-400/20 bg-red-400/10 text-red-200"
          : "border-white/5 bg-black/10 text-tertiary";
        return (
          <li
            key={stage}
            className={`flex items-center gap-3 px-4 py-3 transition ${
              isActive ? "bg-white/5" : "bg-white/[0.02]"
            }`}
          >
            <div className="flex h-5 w-5 shrink-0 items-center justify-center">
              {isCompleted ? (
                <svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              ) : isError ? (
                <svg className="h-4 w-4 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              ) : isActive ? (
                <svg className="h-3.5 w-3.5 animate-spin text-white" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.3" strokeWidth="3" />
                  <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                </svg>
              ) : (
                <div className="h-1.5 w-1.5 rounded-full bg-white/20" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between gap-3">
                <span className={`text-sm ${
                  isActive
                    ? "text-white"
                    : isCompleted
                    ? "text-secondary"
                    : isError
                    ? "text-red-300"
                    : "text-tertiary"
                }`}>
                  {STAGE_LABEL[stage]}
                </span>
                <span className="shrink-0 font-mono text-[10px] text-tertiary">
                  {state.durationMs ? `${Math.round(state.durationMs / 1000)}s` : ""}
                </span>
              </div>
              {stage === "council" && isActive && councilRound > 0 && (
                <p className="mt-0.5 text-[11px] text-tertiary">
                  Round <span className="font-mono text-white">{councilRound}</span> / 10
                </p>
              )}
              {(state.message || state.lastSignal) && (
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className={`min-w-[72px] text-center rounded-full border px-2 py-0.5 text-[10px] ${proofTone}`}>
                    {isActive ? "실행 중" : isCompleted ? "완료" : isError ? "오류" : "대기"}
                  </span>
                  {state.lastSignal && (
                    <span className="min-w-0 max-w-full truncate rounded-full border border-white/10 bg-black/20 px-2 py-0.5 font-mono text-[10px] text-secondary">
                      {state.lastSignal}{lastSignalAge ? ` · ${lastSignalAge} 전` : ""}
                    </span>
                  )}
                  {state.message && (
                    <span className="min-w-0 max-w-full truncate text-[11px] text-tertiary">
                      {state.message}
                    </span>
                  )}
                </div>
              )}
              {state.referenceProjects && state.referenceProjects.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {state.referenceProjects.slice(0, 5).map((project) => (
                    <span
                      key={project}
                      className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[10px] text-secondary"
                    >
                      {project}
                    </span>
                  ))}
                  {state.referenceProjects.length > 5 && (
                    <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-tertiary">
                      +{state.referenceProjects.length - 5}
                    </span>
                  )}
                </div>
              )}
              {state.artifactKeys && state.artifactKeys.length > 0 && (
                <p className="mt-1 truncate font-mono text-[10px] text-tertiary">
                  artifacts: {state.artifactKeys.slice(0, 8).join(" · ")}
                  {state.artifactKeys.length > 8 ? ` · +${state.artifactKeys.length - 8}` : ""}
                </p>
              )}
              {stage === "council" && (
                <RunProgressCouncilActivity activity={councilActivity} personas={councilPersonas} />
              )}
              <RunProgressResearchActivity stage={stage} activity={researchActivity} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
