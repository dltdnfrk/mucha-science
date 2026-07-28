import { formatElapsed } from "./runProgressStages";
import type { RuntimeEvidence } from "./runProgressInteractionTypes";
import type { ResearchContractState } from "./runProgressTypes";

type EvidencePanelsProps = {
  readonly desktopRuntimeStatus: string;
  readonly liveE2eStatus: string;
  readonly sourceAccessEvidenceStatus: string;
  readonly researchContract: ResearchContractState;
  readonly currentSessionEvidenceCount: number;
  readonly researchSessionLabel: string;
  readonly memoryPolicyLabel: string;
  readonly importedRefsLabel: string;
  readonly runtimeEvidence: RuntimeEvidence | null;
};

export function RunProgressEvidencePanels(props: EvidencePanelsProps) {
  const {
    desktopRuntimeStatus,
    liveE2eStatus,
    sourceAccessEvidenceStatus,
    researchContract,
    currentSessionEvidenceCount,
    researchSessionLabel,
    memoryPolicyLabel,
    importedRefsLabel,
    runtimeEvidence,
  } = props;
  return (
    <>
      <div className="fade-in mb-6 rounded-lg border border-white/5 bg-white/[0.02] px-4 py-3 shadow-[var(--shadow-paper)]">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
              Desktop/live evidence
            </p>
            <h2 className="mt-1 text-sm font-medium text-white">Evidence gap surface</h2>
          </div>
          <span className="rounded-full border border-white/10 bg-black/20 px-2.5 py-1 font-mono text-[10px] text-tertiary">
            run scoped
          </span>
        </div>
        <div className="grid gap-2 md:grid-cols-3">
          {[
            ["Desktop runtime", desktopRuntimeStatus],
            ["Live e2e", liveE2eStatus],
            ["Source access", sourceAccessEvidenceStatus],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">{label}</p>
              <p className="mt-1 text-xs text-white">{value}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="fade-in mb-6 rounded-lg border border-white/5 bg-white/[0.02] px-4 py-3 shadow-[var(--shadow-paper)]">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
              Research contract
            </p>
            <h2 className="mt-1 text-sm font-medium text-white">Current-session evidence / imported refs boundary</h2>
          </div>
          <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 font-mono text-[10px] text-emerald-100">
            no implicit memory
          </span>
        </div>
        <div className="grid gap-2 md:grid-cols-4">
          {[
            ["Session", researchSessionLabel],
            ["Memory policy", memoryPolicyLabel],
            [
              "Current session evidence",
              `${currentSessionEvidenceCount} source event${currentSessionEvidenceCount === 1 ? "" : "s"}`,
            ],
            ["Imported wiki refs", importedRefsLabel],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">{label}</p>
              <p className="mt-1 break-words font-mono text-xs text-white">{value}</p>
            </div>
          ))}
        </div>
        {researchContract.importedKnowledgeRefs.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {researchContract.importedKnowledgeRefs.map((ref) => (
              <span
                key={ref}
                className="max-w-full truncate rounded-md border border-sky-300/15 bg-sky-300/10 px-2.5 py-1 font-mono text-[10px] text-sky-100"
                title={ref}
              >
                {ref}
              </span>
            ))}
          </div>
        )}
      </div>
      {runtimeEvidence && (
        <div className={`fade-in mb-6 rounded-lg border px-4 py-3 ${
          runtimeEvidence.stalled
            ? "border-amber-400/20 bg-amber-400/5"
            : "border-white/5 bg-white/[0.02]"
        }`}>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-tertiary">
            <span className="font-semibold uppercase tracking-wider text-secondary">Runtime</span>
            {runtimeEvidence.childPid !== undefined && runtimeEvidence.childPid !== null && (
              <span className="font-mono">bridge pid {runtimeEvidence.childPid}</span>
            )}
            {runtimeEvidence.pythonPid && (
              <span className="font-mono">python pid {runtimeEvidence.pythonPid}</span>
            )}
            {runtimeEvidence.heartbeatStage && (
              <span>
                {runtimeEvidence.heartbeatStage}
                {runtimeEvidence.heartbeatDetail ? ` · ${runtimeEvidence.heartbeatDetail}` : ""}
              </span>
            )}
            {runtimeEvidence.lastEventElapsedMs !== undefined
              && runtimeEvidence.lastEventElapsedMs !== null && (
              <span>last event {formatElapsed(runtimeEvidence.lastEventElapsedMs)} ago</span>
            )}
            {runtimeEvidence.runtimeAgeMs !== undefined && runtimeEvidence.runtimeAgeMs !== null && (
              <span>age {formatElapsed(runtimeEvidence.runtimeAgeMs)}</span>
            )}
          </div>
          {(runtimeEvidence.pythonExecutable || runtimeEvidence.appBinaryPath) && (
            <div className="mt-2 space-y-1">
              {runtimeEvidence.pythonExecutable && (
                <p className="truncate font-mono text-[10px] text-tertiary">
                  py {runtimeEvidence.pythonExecutable}
                </p>
              )}
              {runtimeEvidence.appBinaryPath && (
                <p className="truncate font-mono text-[10px] text-tertiary">
                  app {runtimeEvidence.appBinaryPath}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}
