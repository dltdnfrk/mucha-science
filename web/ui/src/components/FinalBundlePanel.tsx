// Structured final-bundle view for Run Progress (issue #46).
//
// Field accounting for final_report_html_yaml_bundle.v1:
// - rendered here: report_id, title, verdict, central_claims, source_ids,
//   evidence_ids, open_gaps, blockers
// - intentionally hidden (technical envelope): schema_version, contract
// Missing/partial/malformed payloads render explicit degradation copy.

import {
  finalBundleDegradationCopy,
  finalBundleListSections,
  parseFinalBundle,
} from "../lib/finalBundle";

export function FinalBundlePanel({ bundle }: { bundle: unknown }) {
  const view = parseFinalBundle(bundle);
  const degradation = finalBundleDegradationCopy(view);

  if (view.status === "malformed") {
    return (
      <div className="fade-in mt-4 rounded-lg border border-rose-500/20 bg-rose-500/[0.03] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-rose-200">
          Final bundle
        </p>
        <p className="mt-2 text-xs text-rose-100/80">{degradation}</p>
      </div>
    );
  }

  return (
    <div className="fade-in mt-4 rounded-lg border border-white/10 bg-white/[0.02] p-4 shadow-[var(--shadow-paper)]">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
          Final bundle
        </p>
        <span
          className={
            view.verdict === "PASS"
              ? "rounded bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-200"
              : view.verdict === "BLOCKED"
                ? "rounded bg-rose-500/15 px-2 py-0.5 text-[11px] font-semibold text-rose-200"
                : "rounded bg-white/10 px-2 py-0.5 text-[11px] text-secondary"
          }
        >
          {view.verdict || "판정 없음"}
        </span>
      </div>

      <p className="mt-2 text-sm text-white/90">{view.title || "제목 없음"}</p>
      <p className="text-[11px] text-tertiary">{view.reportId ? `report_id: ${view.reportId}` : "report_id 없음"}</p>

      {degradation && (
        <p className="mt-2 rounded border border-amber-500/20 bg-amber-500/[0.05] px-2 py-1 text-[11px] text-amber-200">
          {degradation}
        </p>
      )}

      {finalBundleListSections(view).map((section) => (
        <div className="mt-3" key={section.field}>
          <p className="text-[11px] uppercase tracking-wider text-tertiary">{section.label}</p>
          {section.items.length > 0 ? (
            <ul className="mt-1 space-y-1">
              {section.items.map((item, index) => (
                <li className="break-words text-xs text-secondary" key={`${section.field}-${index}`}>
                  {item}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-tertiary/70">{section.emptyCopy}</p>
          )}
        </div>
      ))}

      <div className="mt-3">
        <p className="text-[11px] uppercase tracking-wider text-tertiary">차단 사유</p>
        {view.blockers.length > 0 ? (
          <ul className="mt-1 space-y-1">
            {view.blockers.map((blocker, index) => (
              <li className="text-xs text-rose-200/90" key={`blocker-${index}`}>
                <span className="font-mono">{blocker.code || "unknown"}</span>
                {blocker.message ? ` — ${blocker.message}` : ""}
                {blocker.requiredAction ? (
                  <span className="text-tertiary"> (조치: {blocker.requiredAction})</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-xs text-tertiary/70">차단 사유가 없습니다.</p>
        )}
      </div>
    </div>
  );
}
