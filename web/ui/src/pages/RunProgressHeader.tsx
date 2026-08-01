import type { StudioProvenance } from "./runProgressInteractionTypes";

type RunProgressHeaderProps = {
  readonly topic: string;
  readonly runId?: string;
  readonly studioProvenance: StudioProvenance | null;
  readonly aborting: boolean;
  readonly onAbort: () => void;
};

export function RunProgressHeader({
  topic,
  runId,
  studioProvenance,
  aborting,
  onAbort,
}: RunProgressHeaderProps) {
  return (
    <div className="fade-in mb-8 border-b border-white/10 pb-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="atlas-label mb-2">Browser</p>
          <h1 className="display-serif truncate text-[32px] font-semibold leading-tight text-white md:text-[44px]">
            {topic || "(주제 없음)"}
          </h1>
          <p className="mt-1 text-xs text-tertiary">{runId}</p>
          {studioProvenance && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {studioProvenance.studioId && (
                <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/20 bg-amber-400/10 px-2 py-0.5 text-[10px] text-amber-100">
                  <span className="h-1 w-1 rounded-full bg-amber-300" />
                  Studio {studioProvenance.studioId.slice(-6)}
                </span>
              )}
              {studioProvenance.studioModel && (
                <span className="inline-flex items-center gap-1 rounded-full border border-sky-400/20 bg-sky-400/10 px-2 py-0.5 text-[10px] text-sky-100">
                  <span className="h-1 w-1 rounded-full bg-sky-300" />
                  {studioProvenance.studioModel}
                </span>
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onAbort}
          disabled={aborting}
          className="shrink-0 rounded-full border border-red-400/20 px-3 py-1.5 text-xs text-red-200 transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {aborting ? "중단 중" : "중단"}
        </button>
      </div>
    </div>
  );
}
