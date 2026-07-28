import type { DeepInterviewArtifacts } from "./runProgressInteractionTypes";

export function RunProgressInterviewArtifacts({
  artifacts,
}: {
  readonly artifacts: DeepInterviewArtifacts | null;
}) {
  if (!artifacts) return null;
  return (
    <div className="fade-in mb-6 overflow-hidden rounded-lg border border-white/10 bg-white/[0.03] px-4 py-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
            Deep Interview Artifacts
          </p>
          <h2 className="mt-1 break-words text-sm font-medium text-white">
            {artifacts.workflow} · {artifacts.documentCount} documents
          </h2>
        </div>
        {artifacts.commit && (
          <span className="max-w-full truncate rounded-full border border-white/10 bg-black/20 px-2.5 py-1 font-mono text-[10px] text-secondary">
            {artifacts.commit.slice(0, 12)}
          </span>
        )}
      </div>
      {artifacts.evidenceMarkers.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {artifacts.evidenceMarkers.slice(0, 8).map((marker) => (
            <span
              key={marker}
              className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[10px] text-tertiary"
            >
              {marker}
            </span>
          ))}
        </div>
      )}
      <div className="grid gap-2 md:grid-cols-2">
        {artifacts.manifest.map((doc) => (
          <div key={doc.path} className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="min-w-0 truncate font-mono text-[11px] text-secondary">
                {doc.path}
              </span>
              <span className="shrink-0 text-[10px] text-tertiary">{doc.chars} chars</span>
            </div>
            <p className="truncate text-xs font-medium text-white">{doc.title}</p>
            {doc.preview && (
              <p className="mt-1 max-h-12 overflow-hidden break-words text-[11px] leading-relaxed text-tertiary">
                {doc.preview}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
