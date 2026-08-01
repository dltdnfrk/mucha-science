import { compactPersonaName, COUNCIL_STAGE_LABEL } from "./runProgressCouncil";
import type { CouncilActivity } from "./runProgressInteractionTypes";

type CouncilActivityProps = {
  readonly activity: readonly CouncilActivity[];
  readonly personas: readonly string[];
};

function councilActivityLabel(item: CouncilActivity): string {
  const stageLabel = item.councilStage
    ? COUNCIL_STAGE_LABEL[item.councilStage] || item.councilStage
    : "";
  if (item.kind === "round_start") return `라운드 시작 · ${item.layer}`;
  if (item.kind === "round_done") return `라운드 완료 · ${item.layer}`;
  const round = item.round ? ` · R${item.round}` : "";
  if (item.kind === "provider_call_start") return `호출 시작 · ${stageLabel}${round}`;
  if (item.kind === "provider_call_done") return `호출 완료 · ${stageLabel}${round}`;
  if (item.kind === "provider_call_timeout") return `타임아웃 · ${stageLabel}${round}`;
  if (item.kind === "provider_call_error") return `오류 · ${stageLabel}${round}`;
  return `${stageLabel}${round}`;
}

export function RunProgressCouncilActivity({ activity, personas }: CouncilActivityProps) {
  if (activity.length === 0) return null;
  return (
    <div className="mt-2 space-y-2">
      {personas.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {personas.slice(0, 8).map((persona) => (
            <span
              key={persona}
              className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 font-mono text-[10px] text-secondary"
            >
              {compactPersonaName(persona)}
            </span>
          ))}
          {personas.length > 8 && (
            <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-tertiary">
              +{personas.length - 8}
            </span>
          )}
        </div>
      )}
      <div className="space-y-1.5">
        {activity.slice(0, 6).map((item) => (
          <div
            key={item.id}
            className="min-w-0 rounded-lg border border-white/5 bg-black/20 px-2.5 py-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate text-[10px] uppercase tracking-wider text-tertiary">
                {councilActivityLabel(item)}
              </span>
              {item.score !== undefined && (
                <span className="shrink-0 rounded-full border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-secondary">
                  {item.score}
                </span>
              )}
            </div>
            {item.kind === "round_start" && (
              <p className="mt-1 text-xs text-secondary">
                페르소나 {item.activePersonaCount ?? item.activePersonaIds?.length ?? 0}명 소환
              </p>
            )}
            {item.kind === "turn" && (
              <p className="mt-1 text-xs text-secondary">
                <span className="font-mono text-white">
                  {compactPersonaName(item.persona)}
                </span>
                이(가) 응답 완료
                {item.responseChars ? ` · ${item.responseChars} chars` : ""}
                {item.provider ? ` · ${item.provider}` : ""}
              </p>
            )}
            {item.kind === "token" && (
              <>
                <div className="mt-1 flex items-center gap-2">
                  <span className="font-mono text-[11px] text-white">
                    {compactPersonaName(item.persona)}
                  </span>
                  {item.visualizationSource === "ollama" && (
                    <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-[10px] text-emerald-200">
                      Ollama · {item.visualizerModel}
                    </span>
                  )}
                </div>
                <p className="mt-1 break-words text-xs leading-relaxed text-secondary">
                  {item.text}
                </p>
              </>
            )}
            {item.kind === "round_done" && item.text && (
              <p className="mt-1 break-words text-[11px] leading-relaxed text-tertiary">
                {item.text}
              </p>
            )}
            {(item.kind === "provider_call_start"
              || item.kind === "provider_call_done"
              || item.kind === "provider_call_timeout"
              || item.kind === "provider_call_error") && (
              <div className="mt-1 space-y-1 text-xs leading-relaxed text-secondary">
                <p>
                  {item.providerRoute ? `route ${item.providerRoute}` : "provider route unavailable"}
                  {item.provider ? ` · provider ${item.provider}` : ""}
                  {item.model ? ` · ${item.model}` : ""}
                </p>
                <p className="text-[11px] text-tertiary">
                  {item.persona ? compactPersonaName(item.persona) : "persona"}
                  {item.timeoutSec !== undefined ? ` · timeout ${item.timeoutSec}s` : ""}
                  {item.elapsedSec !== undefined ? ` · elapsed ${item.elapsedSec}s` : ""}
                  {item.responseChars ? ` · ${item.responseChars} chars` : ""}
                  {item.errorClass ? ` · ${item.errorClass}` : ""}
                  {item.blocksProductPass ? " · blocks product pass" : ""}
                </p>
                {item.text && (
                  <p className="break-words text-[11px] leading-relaxed text-tertiary">
                    {item.text}
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
