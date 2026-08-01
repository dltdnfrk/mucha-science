import type { InterviewClarity, InterviewPrompt } from "./runProgressInteractionTypes";

type InterviewContextProps = {
  readonly prompt: InterviewPrompt;
  readonly clarity: InterviewClarity | null;
  readonly submitting: boolean;
  readonly activeDeepInterviewPrompt: boolean;
  readonly unknownDimensions: readonly string[];
  readonly ontologyNodes: readonly string[];
};

export function RunProgressInterviewContext(props: InterviewContextProps) {
  const {
    prompt,
    clarity,
    submitting,
    activeDeepInterviewPrompt,
    unknownDimensions,
    ontologyNodes,
  } = props;
  return (
    <>
      <div className="mb-3 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
            {prompt.header}
            {prompt.index && prompt.total ? ` · ${prompt.index}/${prompt.total}` : ""}
          </p>
          <h2 className="mt-1 whitespace-pre-wrap text-sm font-medium leading-relaxed text-white">
            {prompt.text}
          </h2>
          {prompt.counselling && (
            <div className="mt-3 rounded-lg border border-sky-400/15 bg-sky-400/5 px-3 py-2 text-[11px] leading-relaxed text-sky-100">
              <div className="mb-1 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider text-sky-200/80">
                <span className="font-semibold">Deep Interview</span>
                {prompt.counselling.mode && <span>{prompt.counselling.mode}</span>}
                {prompt.counselling.provider && <span>{prompt.counselling.provider}</span>}
              </div>
              {prompt.counselling.rationale && (
                <p className="text-sky-100/90">{prompt.counselling.rationale}</p>
              )}
              {prompt.counselling.referenceInsights.length > 0 && (
                <p className="mt-1 text-sky-100/75">
                  참고자료 단서: {prompt.counselling.referenceInsights.slice(0, 3).join(" · ")}
                </p>
              )}
              {prompt.counselling.assumptionsToTest.length > 0 && (
                <p className="mt-1 text-sky-100/75">
                  검증할 가정: {prompt.counselling.assumptionsToTest.slice(0, 2).join(" · ")}
                </p>
              )}
              {prompt.counselling.prdImpact && (
                <p className="mt-1 text-sky-100/60">
                  해석 반영: {prompt.counselling.prdImpact}
                </p>
              )}
            </div>
          )}
        </div>
        <span className="shrink-0 whitespace-nowrap rounded-full border border-amber-400/20 bg-amber-400/10 px-2.5 py-1 text-[10px] text-amber-200">
          {submitting ? "다음 질문 대기" : "대기 중"}
        </span>
      </div>
      {clarity && (
        <div className="mb-3 rounded-lg border border-white/5 bg-black/20 px-3 py-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-tertiary">
            <span className="font-semibold uppercase tracking-wider text-secondary">
              Deep Interview
            </span>
            {clarity.mode && <span>{clarity.mode}</span>}
            {clarity.researchType && <span>{clarity.researchType}</span>}
            {clarity.focusLabel && <span>{clarity.focusLabel}</span>}
            {clarity.coverageScore !== undefined && (
              <span>coverage {Math.round(clarity.coverageScore * 100)}%</span>
            )}
            {clarity.ambiguityScore !== undefined && (
              <span>ambiguity {Math.round(clarity.ambiguityScore * 100)}%</span>
            )}
          </div>
          {clarity.focusQuestion && (
            <p className="mt-1 break-words text-[11px] leading-relaxed text-secondary">
              {clarity.focusQuestion}
            </p>
          )}
          {clarity.missingDimensions.length > 0 && (
            <p className="mt-1 truncate text-[11px] text-tertiary">
              남은 차원: {clarity.missingDimensions.join(" · ")}
            </p>
          )}
        </div>
      )}
      {prompt.preview && (
        <pre className="mb-3 max-h-56 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs leading-relaxed text-secondary">
          {prompt.preview}
        </pre>
      )}
      {activeDeepInterviewPrompt && (
        <div className="mb-3 grid gap-2 md:grid-cols-2">
          <div className="rounded-xl border border-white/10 bg-black/20 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">
              Unknowns board
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {unknownDimensions.length > 0 ? (
                unknownDimensions.map((dimension) => (
                  <span
                    key={dimension}
                    className="rounded-full border border-amber-400/20 bg-amber-400/10 px-2 py-0.5 text-[10px] text-amber-100"
                  >
                    {dimension}
                  </span>
                ))
              ) : (
                <span className="text-[11px] text-secondary">
                  No unresolved dimensions reported.
                </span>
              )}
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-black/20 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">
              Ontology map seed
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(ontologyNodes.length > 0
                ? ontologyNodes
                : ["entity", "relation", "boundary"]).map((node) => (
                <span
                  key={node}
                  className="rounded-full border border-sky-400/20 bg-sky-400/10 px-2 py-0.5 text-[10px] text-sky-100"
                >
                  {node}
                </span>
              ))}
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-tertiary">
              This turn should stabilize entities, relations, triggers, constraints, or evidence boundaries.
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-black/20 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">
              Answer assimilation
            </p>
            <p className="mt-2 text-[11px] leading-relaxed text-secondary">
              {prompt.counselling?.prdImpact
                || "Your answer will update the working interpretation before research, evidence, and council stages continue."}
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-black/20 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">
              Capability graph
            </p>
            <div className="mt-2 grid grid-cols-2 gap-1.5 text-[10px] text-secondary">
              <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1">Ambiguity gate</span>
              <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1">Source grounding</span>
              <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1">Council handoff</span>
              <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1">Report contract</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
