type RunProgressBannersProps = {
  readonly error: string | null;
  readonly warnings: readonly string[];
  readonly onRestart: () => void;
  readonly onHome: () => void;
};

export function RunProgressBanners({
  error,
  warnings,
  onRestart,
  onHome,
}: RunProgressBannersProps) {
  return (
    <>
      {error && (
        <div className="fade-in mb-6 flex items-start justify-between gap-4 rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3">
          <p className="break-all text-sm text-red-300">{error}</p>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={onRestart}
              className="rounded-full bg-white px-3 py-1 text-xs font-medium text-black transition hover:opacity-90"
            >
              다시 시작
            </button>
            <button
              type="button"
              onClick={onHome}
              className="rounded-full border border-white/10 px-3 py-1 text-xs text-secondary transition hover:bg-white/5 hover:text-white"
            >
              처음으로
            </button>
          </div>
        </div>
      )}
      {warnings.length > 0 && !error && (
        <div className="fade-in mb-6 rounded-lg border border-amber-400/20 bg-amber-400/5 px-4 py-3">
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-amber-200">
            실행 경고
          </p>
          {warnings.map((warning) => (
            <p key={warning} className="break-all text-sm text-amber-100/80">
              {warning}
            </p>
          ))}
        </div>
      )}
    </>
  );
}
