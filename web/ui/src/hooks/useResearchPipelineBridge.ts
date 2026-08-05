import { useCallback, useEffect, useRef, useState } from "react";
import {
  toResearchActivityProjections,
  toResearchConversationEvent,
  toResearchInteraction,
} from "../lib/researchRuntime";
import type {
  ResearchActivityProjection,
  ResearchConversationEvent,
  ResearchInteraction,
  ResearchRuntimeContext,
} from "../lib/researchRuntime";
import { cancelPipeline } from "../lib/pipelineExecutionClient";
import {
  getBufferedEvents,
  onBackendEvent,
  sendAction,
} from "../lib/tauriClient";
import type { BackendAction, BackendEvent } from "../lib/tauriClient";

type ActiveResearchRun = {
  cancellationRequested: boolean;
  eventIndex: number;
  generation: number;
  runId: string;
  seenEvents: Set<string>;
  seenEventOrder: string[];
  turnId: string;
};

const MAX_SEEN_EVENTS = 10_000;

export type PendingResearchInteraction = {
  readonly allowFreeText: boolean;
  readonly backendEvent: "hitl_gate" | "interview_question";
  readonly interaction: ResearchInteraction;
  readonly submitting: boolean;
};

type ResearchPipelineBridgeOptions = {
  readonly onActivity: (
    runId: string,
    turnId: string,
    projections: readonly ResearchActivityProjection[],
  ) => void;
  readonly onConversationEvent: (event: ResearchConversationEvent) => void;
  readonly onError: () => void;
  readonly onTerminal: (
    runId: string,
    turnId: string,
    status: "complete" | "error" | "canceled",
    errorMessage?: string,
  ) => void;
};

export function useResearchPipelineBridge({
  onActivity,
  onConversationEvent,
  onError,
  onTerminal,
}: ResearchPipelineBridgeOptions) {
  const [activeTurnId, setActiveTurnId] = useState<string>();
  const [pendingInteraction, setPendingInteraction] = useState<PendingResearchInteraction>();
  const activeRunRef = useRef<ActiveResearchRun>();
  const unlistenRef = useRef<() => void>();
  const generationRef = useRef(0);
  const callbacksRef = useRef({
    onActivity,
    onConversationEvent,
    onError,
    onTerminal,
  });
  useEffect(() => {
    callbacksRef.current = {
      onActivity,
      onConversationEvent,
      onError,
      onTerminal,
    };
  });

  const detachRun = useCallback(() => {
    generationRef.current += 1;
    activeRunRef.current = undefined;
    setActiveTurnId(undefined);
    unlistenRef.current?.();
    unlistenRef.current = undefined;
  }, []);

  const processEvent = useCallback((event: BackendEvent) => {
    const activeRun = activeRunRef.current;
    if (
      !activeRun
      || event.app_run_id !== activeRun.runId
      || event.generation !== activeRun.generation
    ) return;
    const fingerprint = JSON.stringify(event);
    if (activeRun.seenEvents.has(fingerprint)) return;
    activeRun.seenEvents.add(fingerprint);
    activeRun.seenEventOrder.push(fingerprint);
    if (activeRun.seenEventOrder.length > MAX_SEEN_EVENTS) {
      const expired = activeRun.seenEventOrder.shift();
      if (expired) activeRun.seenEvents.delete(expired);
    }

    const context: ResearchRuntimeContext = {
      eventIndex: activeRun.eventIndex,
      generation: activeRun.generation,
      runId: activeRun.runId,
      turnId: activeRun.turnId,
    };
    activeRun.eventIndex += 1;
    const activity = toResearchActivityProjections(event, context);
    if (activity.length > 0) {
      callbacksRef.current.onActivity(activeRun.runId, activeRun.turnId, activity);
    }
    if (
      activity.some((projection) => projection.kind === "cancellation_acknowledged")
    ) {
      callbacksRef.current.onTerminal(activeRun.runId, activeRun.turnId, "canceled");
      setPendingInteraction(undefined);
      detachRun();
      return;
    }
    const conversationEvent = toResearchConversationEvent(event, context);
    if (conversationEvent && !activeRun.cancellationRequested) {
      callbacksRef.current.onConversationEvent(conversationEvent);
    }
    if (!activeRun.cancellationRequested) {
      setInteractionFromEvent(event, context, setPendingInteraction);
    }

    if (event.event === "done" && !activeRun.cancellationRequested) {
      callbacksRef.current.onTerminal(activeRun.runId, activeRun.turnId, "complete");
      setPendingInteraction(undefined);
      detachRun();
    } else if (
      !activeRun.cancellationRequested
      && (event.event === "error" || event.event === "pipeline_error")
    ) {
      const errorMessage = event.message?.trim();
      if (errorMessage) {
        callbacksRef.current.onTerminal(
          activeRun.runId,
          activeRun.turnId,
          "error",
          errorMessage,
        );
      } else {
        callbacksRef.current.onTerminal(activeRun.runId, activeRun.turnId, "error");
      }
      setPendingInteraction(undefined);
      detachRun();
    }
  }, [detachRun]);

  const attachRun = useCallback(async (
    runId: string,
    turnId: string,
    executionGeneration: number,
  ) => {
    detachRun();
    const attachmentGeneration = generationRef.current;
    activeRunRef.current = {
      cancellationRequested: false,
      eventIndex: 0,
      generation: executionGeneration,
      runId,
      seenEvents: new Set(),
      seenEventOrder: [],
      turnId,
    };
    setActiveTurnId(turnId);
    try {
      const unlisten = await onBackendEvent(processEvent, runId);
      if (attachmentGeneration !== generationRef.current) {
        unlisten();
        return false;
      }
      unlistenRef.current = unlisten;
      const bufferedEvents = await getBufferedEvents(runId);
      if (attachmentGeneration !== generationRef.current) return false;
      bufferedEvents.forEach(processEvent);
      return true;
    } catch (error) {
      if (attachmentGeneration === generationRef.current) detachRun();
      throw error;
    }
  }, [detachRun, processEvent]);

  const cancelActiveRun = useCallback(async (): Promise<boolean> => {
    const activeRun = activeRunRef.current;
    if (!activeRun || activeRun.cancellationRequested) return false;
    activeRun.cancellationRequested = true;
    setPendingInteraction(undefined);
    try {
      const acknowledgement = await cancelPipeline(activeRun.runId, activeRun.generation);
      processEvent({
        event: "execution_cancelled",
        app_run_id: acknowledgement.app_run_id,
        generation: acknowledgement.generation,
        termination_observed: acknowledgement.termination_observed,
        reaped: acknowledgement.reaped,
      });
      return acknowledgement.acknowledged;
    } catch {
      const current = activeRunRef.current;
      if (current === activeRun) current.cancellationRequested = false;
      callbacksRef.current.onError();
      return false;
    }
  }, [processEvent]);

  const answerInteraction = useCallback(async (
    optionKey?: string,
    freeText?: string,
  ) => {
    const pending = pendingInteraction;
    if (!pending || pending.submitting) return;
    const option = pending.interaction.options.find((candidate) => candidate.key === optionKey);
    const answer = freeText?.trim() || option?.label || "";
    if (!answer) return;
    setPendingInteraction({ ...pending, submitting: true });

    try {
      if (pending.backendEvent === "interview_question") {
        await sendAction({
          action: "interview_answer",
          answer,
          choice: option?.key ?? "OTHER",
          other_text: freeText?.trim() || undefined,
          q_id: pending.interaction.id,
          selected: option?.value ?? option?.key ?? "OTHER",
        }, activeRunRef.current?.runId, activeRunRef.current?.generation);
      } else {
        const decision = option?.value ?? option?.key;
        if (decision !== "approved" && decision !== "changes_requested") {
          setPendingInteraction({ ...pending, submitting: false });
          return;
        }
        const comment = freeText?.trim();
        if (decision === "changes_requested" && !comment) {
          setPendingInteraction({ ...pending, submitting: false });
          return;
        }
        await sendAction(
          createHitlDecisionAction(pending.interaction.id, decision, comment),
          activeRunRef.current?.runId,
          activeRunRef.current?.generation,
        );
      }
      setPendingInteraction(undefined);
    } catch {
      setPendingInteraction({ ...pending, submitting: false });
      callbacksRef.current.onError();
    }
  }, [pendingInteraction]);

  useEffect(() => detachRun, [detachRun]);

  return {
    activeTurnId,
    answerInteraction,
    attachRun,
    cancelActiveRun,
    detachRun,
    pendingInteraction,
  };
}

export function createHitlDecisionAction(
  gate: string,
  status: "approved" | "changes_requested",
  comment?: string,
): BackendAction {
  const normalizedComment = comment?.trim();
  return normalizedComment
    ? { action: "hitl_decision", comment: normalizedComment, gate, status }
    : { action: "hitl_decision", gate, status };
}

function setInteractionFromEvent(
  event: BackendEvent,
  context: ResearchRuntimeContext,
  setPendingInteraction: (
    value: PendingResearchInteraction | undefined,
  ) => void,
): void {
  const interaction = toResearchInteraction(event, context);
  if (!interaction || (event.event !== "interview_question" && event.event !== "hitl_gate")) return;
  setPendingInteraction({
    allowFreeText: event.event === "interview_question" && event.allow_other !== false,
    backendEvent: event.event,
    interaction,
    submitting: false,
  });
}
