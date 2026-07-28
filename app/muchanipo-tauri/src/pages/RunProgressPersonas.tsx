import { PersonaPoolCard, type PersonaPoolSummary } from "../components/PersonaPoolCard";
import type { BrowserPersonaRow } from "./runProgressInteractionTypes";

type RunProgressPersonasProps = {
  readonly rows: readonly BrowserPersonaRow[];
  readonly pool: PersonaPoolSummary | null;
};

export function RunProgressPersonas({ rows, pool }: RunProgressPersonasProps) {
  return (
    <>
      <div className="fade-in mb-6 rounded-lg border border-white/5 bg-white/[0.02] p-4 shadow-[var(--shadow-paper)]">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
              Selected personas
            </p>
            <h2 className="mt-1 text-sm font-medium text-white">Persona provenance</h2>
          </div>
          <span className="min-w-[86px] rounded-full border border-white/10 bg-black/20 px-2 py-1 text-center font-mono text-[10px] uppercase tracking-[0.08em] text-tertiary">
            Provenance
          </span>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {rows.map((persona) => (
            <div
              key={persona.id}
              className="rounded-lg border border-white/10 bg-black/20 px-3 py-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white">{persona.name}</p>
                  <p className="mt-1 text-xs leading-5 text-secondary">{persona.role}</p>
                </div>
                <span className="shrink-0 rounded-md border border-white/10 px-2 py-1 text-[10px] text-tertiary">
                  Source
                </span>
              </div>
              <p className="mt-2 break-words font-mono text-[10px] leading-5 text-tertiary">
                {persona.provenance}
              </p>
              <p className="mt-1 text-[11px] leading-5 text-tertiary">{persona.note}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="fade-in mb-6">
        <PersonaPoolCard pool={pool} />
      </div>
    </>
  );
}
