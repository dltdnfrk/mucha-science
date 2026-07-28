import EvidenceIndexPanel from "../components/EvidenceIndexPanel";
import type { TokenCard } from "./runProgressTypes";

type RunProgressReportsProps = {
  readonly reportPreview: string;
  readonly finalReport: string;
  readonly tokenCards: readonly TokenCard[];
};

export function RunProgressReports({
  reportPreview,
  finalReport,
  tokenCards,
}: RunProgressReportsProps) {
  return (
    <>
      {reportPreview && !finalReport && (
        <div className="fade-in mt-8 rounded-lg border border-white/5 bg-white/[0.02] p-4 shadow-[var(--shadow-paper)]">
          <p className="mb-3 text-[11px] uppercase tracking-wider text-tertiary">
            Report preview
          </p>
          <div className="space-y-3">
            <EvidenceIndexPanel markdown={reportPreview} compact title="보고서 근거 요약" />
            <details className="rounded-lg border border-white/10 bg-black/15 px-3 py-2">
              <summary className="cursor-pointer text-xs text-secondary transition hover:text-white">
                원본 Markdown 보기
              </summary>
              <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-tertiary">
                {reportPreview}
              </pre>
            </details>
          </div>
        </div>
      )}
      {finalReport && (
        <div className="fade-in mt-8 rounded-lg border border-emerald-500/10 bg-emerald-500/[0.02] p-4 shadow-[var(--shadow-paper)]">
          <p className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-emerald-200">
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            Final report
          </p>
          <div className="space-y-3">
            <EvidenceIndexPanel markdown={finalReport} compact title="보고서 근거 요약" />
            <details className="rounded-lg border border-white/10 bg-black/15 px-3 py-2">
              <summary className="cursor-pointer text-xs text-secondary transition hover:text-white">
                원본 Markdown 보기
              </summary>
              <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-tertiary">
                {finalReport}
              </pre>
            </details>
          </div>
        </div>
      )}
      {tokenCards.length > 0 && (
        <div className="fade-in mt-8">
          <p className="mb-3 text-[11px] uppercase tracking-wider text-tertiary">
            Council activity
          </p>
          <div className="space-y-px overflow-hidden rounded-lg border border-white/5">
            {tokenCards.map((card, index) => (
              <div key={index} className="bg-white/[0.02] px-4 py-3">
                <div className="mb-1 flex items-center gap-2 text-[10px] text-tertiary">
                  <span className="font-mono text-white">{card.persona}</span>
                  {card.layer && <span>·</span>}
                  {card.layer && <span>{card.layer}</span>}
                  {card.round !== undefined && <span>·</span>}
                  {card.round !== undefined && <span>R{card.round}</span>}
                </div>
                <p className="break-words text-xs leading-relaxed text-secondary">{card.text}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
