import type { Dispatch, SetStateAction } from "react";
import type { BackendEvent } from "../lib/tauriClient";
import { pushCouncilActivity } from "./runProgressCouncil";
import { parseEventBoolean } from "./runProgressEventValues";
import type { CouncilActivity } from "./runProgressInteractionTypes";
import type { Stage, StageState, TokenCard } from "./runProgressTypes";

export type CouncilEventContext = {
  readonly setStages: Dispatch<SetStateAction<Record<Stage, StageState>>>;
  readonly setCouncilRound: Dispatch<SetStateAction<number>>;
  readonly setCouncilPersonas: Dispatch<SetStateAction<string[]>>;
  readonly setCouncilActivity: Dispatch<SetStateAction<CouncilActivity[]>>;
  readonly setTokenCards: Dispatch<SetStateAction<TokenCard[]>>;
};

function activateCouncil(
  context: CouncilEventContext,
  lastSignal: string,
  message: string,
): void {
  context.setStages((previous) => ({
    ...previous,
    council: {
      ...previous.council,
      status: previous.council.status === "completed" ? "completed" : "active",
      startedAt: previous.council.startedAt ?? Date.now(),
      lastEventAt: Date.now(),
      lastSignal,
      message,
    },
  }));
}

function providerMessage(eventName: string): string {
  if (eventName === "council_provider_call_start") return "Council provider 호출 시작";
  if (eventName === "council_provider_call_done") return "Council provider 응답 수신";
  if (eventName === "council_provider_call_timeout") return "Council provider 타임아웃 감지";
  return "Council provider 오류 감지";
}

function providerKind(eventName: string): CouncilActivity["kind"] {
  if (eventName === "council_provider_call_start") return "provider_call_start";
  if (eventName === "council_provider_call_done") return "provider_call_done";
  if (eventName === "council_provider_call_timeout") return "provider_call_timeout";
  return "provider_call_error";
}

export function handleCouncilEvent(event: BackendEvent, context: CouncilEventContext): boolean {
  if (event.event === "council_round_start" && typeof event.round === "number") {
    context.setCouncilRound(event.round);
    activateCouncil(context, `council_round_start · R${event.round}`, "페르소나 라운드 시작");
    const activePersonaIds = Array.isArray(event.active_persona_ids)
      ? event.active_persona_ids.map((item) => String(item)).filter(Boolean)
      : [];
    if (activePersonaIds.length > 0) context.setCouncilPersonas(activePersonaIds);
    context.setCouncilActivity((previous) =>
      pushCouncilActivity(previous, {
        id: `round-start:${event.round}:${event.layer ?? ""}`,
        kind: "round_start",
        round: event.round,
        layer: String(event.layer ?? ""),
        activePersonaCount:
          Number(event.active_persona_count ?? activePersonaIds.length) || undefined,
        activePersonaIds,
      }),
    );
    return true;
  }
  if (event.event === "council_turn" && typeof event.round === "number") {
    const persona = String(event.persona ?? "");
    const councilStage = String(event.council_stage ?? "");
    activateCouncil(context, `council_turn · ${persona || "persona"}`, "페르소나 응답 수신");
    context.setCouncilActivity((previous) =>
      pushCouncilActivity(previous, {
        id: `turn:${event.round}:${event.layer ?? ""}:${councilStage}:${persona}:${event.response_chars ?? ""}`,
        kind: "turn",
        round: event.round,
        layer: String(event.layer ?? ""),
        persona,
        councilStage,
        provider: String(event.provider ?? ""),
        responseChars: Number(event.response_chars ?? 0) || undefined,
      }),
    );
    return true;
  }
  if (event.event === "council_persona_token") {
    const persona = String(event.persona ?? "agent");
    const layer = typeof event.layer === "string" ? event.layer : undefined;
    const round = typeof event.round === "number" ? event.round : undefined;
    const delta = String(event.delta ?? "");
    context.setTokenCards((previous) => {
      const last = previous[previous.length - 1];
      if (last && last.persona === persona && last.layer === layer && last.round === round) {
        return [...previous.slice(0, -1), { ...last, text: last.text + delta }];
      }
      return [...previous, { persona, text: delta, layer, round }].slice(-12);
    });
    if (delta.trim()) {
      activateCouncil(context, `council_token · ${persona}`, "토론 시각화 토큰 수신");
      context.setCouncilActivity((previous) =>
        pushCouncilActivity(previous, {
          id: `token:${round ?? ""}:${layer ?? ""}:${event.council_stage ?? ""}:${persona}:${delta.slice(0, 80)}`,
          kind: "token",
          round,
          layer,
          persona,
          councilStage: String(event.council_stage ?? ""),
          text: delta,
          visualizationSource: String(event.visualization_source ?? ""),
          visualizerModel: String(event.visualizer_model ?? ""),
        }),
      );
    }
    return true;
  }
  if (event.event === "council_round_done" && typeof event.round === "number") {
    context.setCouncilActivity((previous) =>
      pushCouncilActivity(previous, {
        id: `round-done:${event.round}:${event.layer ?? ""}`,
        kind: "round_done",
        round: event.round,
        layer: String(event.layer ?? ""),
        score: Number(event.score ?? 0) || undefined,
        text: event.stopped ? String(event.stop_reason ?? "") : undefined,
      }),
    );
    return true;
  }
  const providerEvent =
    event.event === "council_provider_call_start"
    || event.event === "council_provider_call_done"
    || event.event === "council_provider_call_timeout"
    || event.event === "council_provider_call_error";
  if (!providerEvent || typeof event.round !== "number") return false;
  const persona = String(event.persona ?? "persona");
  const councilStage = String(event.council_stage ?? "council");
  const providerRoute = String(event.provider_route ?? "");
  const provider = String(event.provider ?? "");
  const elapsedSec = Number(event.elapsed_sec ?? 0) || undefined;
  const timeoutSec = Number(event.timeout_sec ?? 0) || undefined;
  activateCouncil(context, `${event.event} · ${councilStage}`, providerMessage(event.event));
  context.setCouncilActivity((previous) =>
    pushCouncilActivity(previous, {
      id: `provider:${event.event}:${event.round}:${event.layer ?? ""}:${councilStage}:${persona}:${providerRoute}:${provider}:${elapsedSec ?? timeoutSec ?? ""}`,
      kind: providerKind(event.event),
      round: event.round,
      layer: String(event.layer ?? ""),
      persona,
      councilStage,
      providerRoute: providerRoute || undefined,
      provider: provider || undefined,
      model: String(event.model ?? "") || undefined,
      responseChars: Number(event.response_chars ?? 0) || undefined,
      elapsedSec,
      timeoutSec,
      errorClass: String(event.error_class ?? "") || undefined,
      blocksProductPass: parseEventBoolean(event.blocks_product_pass),
      text: String(event.error ?? "").trim() || undefined,
    }),
  );
  return true;
}
