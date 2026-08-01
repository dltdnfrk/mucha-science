import {
  formatBenchmarkMetricLabel,
  formatBenchmarkMetricValue,
  researchActivityCopy,
  researchPlanDisplayRows,
  researchPlanSummaryChips,
  researchProgressStage,
  researchQualityDetailChips,
} from "./runProgressResearchPresentation";
import type { ResearchActivity, Stage } from "./runProgressTypes";

function metadataItems(item: ResearchActivity): string[] {
  return [
    item.facetId ? `facet ${item.facetId}` : undefined,
    item.purpose ? `purpose ${item.purpose}` : undefined,
    item.sourceClass ? `source class ${item.sourceClass}` : undefined,
    item.intent ? `intent ${item.intent}` : undefined,
    item.backend ? `backend ${item.backend}` : undefined,
  ].filter((value): value is string => Boolean(value));
}

function ResearchPlan({ item }: { readonly item: ResearchActivity }) {
  const copy = researchActivityCopy(item);
  return (
    <div className="mt-1 space-y-1.5 text-xs leading-relaxed text-secondary">
      <p>{copy.message}</p>
      <div className="flex flex-wrap gap-1">
        {researchPlanSummaryChips(item).map((detail) => (
          <span
            key={detail}
            className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-tertiary"
          >
            {detail}
          </span>
        ))}
      </div>
      <div className="space-y-1">
        {researchPlanDisplayRows(item).map((row, routeIndex) => (
          <details
            key={`${row.query || "route"}-${routeIndex}`}
            className="min-w-0 rounded border border-white/5 bg-white/[0.02] px-2 py-1"
            open={routeIndex < 3}
          >
            <summary className="cursor-pointer break-words text-[11px] text-secondary marker:text-tertiary">
              {routeIndex + 1}. {row.query || `query ${routeIndex + 1}`}
            </summary>
            <div className="mt-1 space-y-0.5">
              {row.routeDetails.length > 0 && (
                <p className="break-words text-[10px] text-tertiary">
                  {row.routeDetails.join(" · ")}
                </p>
              )}
              {row.continueReason && (
                <p className="break-words text-[10px] text-tertiary">
                  continue reason: {row.continueReason}
                </p>
              )}
              {row.authorityRequirement && (
                <p className="break-words text-[10px] text-tertiary">
                  authority requirement: {row.authorityRequirement}
                </p>
              )}
              {row.acceptanceRules.length > 0 && (
                <p className="break-words text-[10px] text-tertiary">
                  acceptance rules: {row.acceptanceRules.join("; ")}
                </p>
              )}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

function ResearchActivityBody({ item }: { readonly item: ResearchActivity }) {
  const copy = researchActivityCopy(item);
  if (item.status === "research_plan_ready") return <ResearchPlan item={item} />;
  if (item.status === "source_found" || item.status === "source_evaluated") {
    return (
      <>
        <p className="mt-1 truncate text-xs text-secondary">
          {item.sourceTitle || "로컬/내부 근거"}
        </p>
        {item.sourceUrl && (
          <p className="mt-0.5 truncate font-mono text-[10px] text-tertiary">
            {item.sourceUrl}
          </p>
        )}
        {item.status === "source_evaluated" && (
          <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-tertiary">
            {item.sourceKind && <span>kind: {item.sourceKind}</span>}
            {item.facetIds && item.facetIds.length > 0 && (
              <span>facets: {item.facetIds.join(", ")}</span>
            )}
            {item.relevanceScore !== undefined && (
              <span>relevance: {Math.round(item.relevanceScore * 100)}%</span>
            )}
          </div>
        )}
        {item.reason && (
          <p className="mt-1 break-words text-[11px] leading-relaxed text-tertiary">
            {item.reason}
          </p>
        )}
        {item.query && (
          <p className="mt-1 break-words text-[11px] leading-relaxed text-tertiary">
            {item.query}
          </p>
        )}
      </>
    );
  }
  if (item.status === "knowledge_gap") {
    return (
      <div className="mt-1 space-y-1 text-xs leading-relaxed text-secondary">
        <p>{item.message || "필수 facet 근거가 부족합니다."}</p>
        <p className="text-[11px] text-tertiary">
          {item.facetId || "facet"}: {item.acceptedCount ?? 0}/{item.minAcceptedSources ?? "?"} accepted sources
        </p>
      </div>
    );
  }
  if (item.status === "facet_summary") {
    return (
      <p className="mt-1 break-words text-xs leading-relaxed text-secondary">
        근거 facet 요약 완료 · gaps {item.gapCount ?? 0}
      </p>
    );
  }
  const qualityStatus =
    item.status === "source_audit_gate"
    || item.status === "claim_evidence_gate"
    || item.status === "max_plus_benchmark_scored"
    || item.status === "research_quality_ready";
  if (!qualityStatus) {
    return (
      <p className="mt-1 break-words text-xs leading-relaxed text-secondary">
        {item.query || copy.message}
      </p>
    );
  }
  const details = researchQualityDetailChips(item);
  return (
    <div className="mt-1 space-y-1 text-xs leading-relaxed text-secondary">
      <p>{copy.message}</p>
      {item.benchmarkId && (
        <p className="break-words font-mono text-[10px] leading-relaxed text-tertiary">
          {item.benchmarkId}
        </p>
      )}
      {details.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {details.map((detail) => (
            <span
              key={detail}
              className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-tertiary"
            >
              {detail}
            </span>
          ))}
        </div>
      )}
      {item.metrics && Object.keys(item.metrics).length > 0 && (
        <div className="flex flex-wrap gap-1">
          {Object.entries(item.metrics).map(([key, value]) => (
            <span
              key={key}
              className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-tertiary"
            >
              {formatBenchmarkMetricLabel(key)} {formatBenchmarkMetricValue(value)}
            </span>
          ))}
        </div>
      )}
      {item.reason && (
        <p className="break-words text-[11px] leading-relaxed text-tertiary">{item.reason}</p>
      )}
    </div>
  );
}

export function RunProgressResearchActivity({
  stage,
  activity,
}: {
  readonly stage: Stage;
  readonly activity: readonly ResearchActivity[];
}) {
  if ((stage !== "research" && stage !== "evidence") || activity.length === 0) return null;
  return (
    <div className="mt-2 space-y-1.5">
      {activity
        .filter((item) =>
          researchProgressStage({ event: "research_progress", status: item.status }, item) === stage)
        .slice(0, 5)
        .map((item) => {
          const copy = researchActivityCopy(item);
          const metadata = metadataItems(item);
          return (
            <div
              key={item.id}
              className="min-w-0 rounded-lg border border-white/5 bg-black/20 px-2.5 py-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] uppercase tracking-wider text-tertiary">
                  {copy.label}
                  {item.queryIndex && item.queryCount ? ` · ${item.queryIndex}/${item.queryCount}` : ""}
                </span>
                {item.sourceGrade && (
                  <span className="shrink-0 rounded-full border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-secondary">
                    {item.sourceGrade}
                  </span>
                )}
              </div>
              <ResearchActivityBody item={item} />
              {metadata.length > 0 && (
                <p className="mt-1 break-words text-[10px] leading-relaxed text-tertiary">
                  {metadata.join(" · ")}
                </p>
              )}
              {item.continueReason && (
                <p className="mt-1 break-words text-[10px] leading-relaxed text-tertiary">
                  continue reason: {item.continueReason}
                </p>
              )}
              {item.authorityRequirement && (
                <p className="mt-1 break-words text-[10px] leading-relaxed text-tertiary">
                  authority requirement: {item.authorityRequirement}
                </p>
              )}
              {item.acceptanceRules && item.acceptanceRules.length > 0 && (
                <p className="mt-1 break-words text-[10px] leading-relaxed text-tertiary">
                  acceptance rules: {item.acceptanceRules.join("; ")}
                </p>
              )}
              {item.backends && item.backends.length > 0 && (
                <p className="mt-1 truncate text-[11px] text-tertiary">
                  {item.backends.join(" · ")}
                </p>
              )}
            </div>
          );
        })}
    </div>
  );
}
