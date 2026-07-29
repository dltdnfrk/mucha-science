import {
  PlannotatorPlanEditor,
  type PlanReviewEditState,
} from "../components/PlannotatorPlanEditor";
import EvidenceIndexPanel from "../components/EvidenceIndexPanel";
import { hitlEvidenceRefs } from "./runProgressInteractionParsing";
import type { HitlPrompt } from "./runProgressInteractionTypes";

type RunProgressHitlPromptProps = {
  readonly prompt: HitlPrompt | null;
  readonly edits: PlanReviewEditState | null;
  readonly editCount: number;
  readonly submitting: boolean;
  readonly error: string | null;
  readonly onEditsChange: (edits: PlanReviewEditState) => void;
  readonly onDecision: (status: "approved" | "changes_requested") => void;
};

export function RunProgressHitlPrompt(props: RunProgressHitlPromptProps) {
  const { prompt, edits, editCount, submitting, error, onEditsChange, onDecision } = props;
  if (!prompt) return null;
  return (
    <div className="fade-in mb-6 overflow-hidden rounded-lg border border-amber-400/20 bg-amber-400/5 px-4 py-4">
      <div className="mb-3 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-200">
            HITL Gate · {prompt.gate}
          </p>
          <h2 className="mt-1 text-sm font-medium leading-relaxed text-white">
            {prompt.title}
          </h2>
          <p className="mt-1 text-xs leading-relaxed text-secondary">{prompt.prompt}</p>
        </div>
        <span className="shrink-0 whitespace-nowrap rounded-full border border-amber-400/20 bg-amber-400/10 px-2.5 py-1 text-[10px] text-amber-200">
          승인 대기
        </span>
      </div>
      {prompt.gate === "evidence" && (
        <div className="mb-3">
          <EvidenceIndexPanel
            evidenceRefs={hitlEvidenceRefs(prompt)}
            compact
            title="검토할 근거"
          />
        </div>
      )}
      {prompt.preview && prompt.gate !== "evidence" && (
        <pre className="mb-3 max-h-64 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs leading-relaxed text-secondary">
          {prompt.preview}
        </pre>
      )}
      {prompt.preview && prompt.gate === "evidence" && (
        <details className="mb-3 rounded-lg border border-white/10 bg-black/15 px-3 py-2">
          <summary className="cursor-pointer text-xs text-secondary transition hover:text-white">
            원본 evidence payload 보기
          </summary>
          <pre className="mt-2 max-h-44 max-w-full overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-tertiary">
            {prompt.preview}
          </pre>
        </details>
      )}
      {prompt.gate === "plan" && edits && (
        <PlannotatorPlanEditor
          state={edits}
          onChange={onEditsChange}
          editCount={editCount}
        />
      )}
      <div className="grid grid-cols-1 gap-2 sm:ml-auto sm:inline-grid sm:max-w-full sm:grid-cols-[max-content_max-content]">
        <button
          type="button"
          disabled={submitting}
          onClick={() => onDecision("changes_requested")}
          className="min-h-10 min-w-0 max-w-full whitespace-nowrap rounded-full border border-white/10 px-4 py-2 text-center text-sm text-secondary transition hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          수정 필요
        </button>
        <button
          type="button"
          disabled={submitting}
          onClick={() => onDecision("approved")}
          className="min-h-10 min-w-0 max-w-full whitespace-nowrap rounded-full bg-white px-4 py-2 text-center text-sm font-medium text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "승인 중" : editCount > 0 ? "수정 반영 후 계속" : "승인하고 계속"}
        </button>
      </div>
      {error && <p className="mt-2 break-all text-xs text-red-300">{error}</p>}
    </div>
  );
}
