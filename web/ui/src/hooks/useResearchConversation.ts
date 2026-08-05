import { useCallback, useEffect, useRef, useState } from "react";
import { recordResearchConversationEvent, startResearchConversationTurn } from "../lib/researchConversation";
import type { ResearchConversationSession } from "../lib/researchConversation";
import {
  createResearchIdentifier,
  createResearchWorkspace,
  deleteResearchSession,
  downloadResearchTurn,
  listResearchConversationSummaries,
  loadResearchWorkspace,
  persistResearchWorkspace,
  switchResearchWorkspace,
} from "../lib/researchConversationStorage";
import type { PersistedTurnStatus } from "../lib/researchConversationStorage";
import {
  canChangeResearchConversation,
  projectTurnActivity,
  recoverUnresumableResearchTurns,
  setTurnCancellationRequested,
  stripTransientRuntime,
} from "../lib/researchConversationController";
import type {
  ResearchConversationController,
  ResearchTurnRuntime,
  UseResearchConversationOptions,
} from "../lib/researchConversationController";
import { useResearchPipelineBridge } from "./useResearchPipelineBridge";
import { markRunDone, markRunFailed, pushRun } from "../lib/runsIndex";
import { composeResearchExecutionEnvironment } from "../lib/sourceConnections";
import { submitIdea } from "../lib/tauriClient";
import { readEnvsFromSettings, readResearchDepth } from "../pages/runProgressSettings";
export type { PendingResearchInteraction } from "./useResearchPipelineBridge";
export { createResearchExecutionAuthority } from "../lib/researchExecution";
export type { ResearchCycleCompanion } from "../lib/researchExecution";
export type { ResearchConversationController, ResearchTurnRuntime } from "../lib/researchConversationController";

export function useResearchConversation({
  buildSourceExecutionProfile,
}: UseResearchConversationOptions): ResearchConversationController {
  const [initialState] = useState(() => {
    const loadedWorkspace = loadResearchWorkspace();
    const recovery = recoverUnresumableResearchTurns(loadedWorkspace.runtimeByTurn);
    return {
      workspace: {
        ...loadedWorkspace,
        runtimeByTurn: recovery.runtimeByTurn,
      },
      composerError: recovery.composerError,
    };
  });
  const [session, setSession] = useState(initialState.workspace.session);
  const [runtimeByTurn, setRuntimeByTurn] = useState<
    Readonly<Record<string, ResearchTurnRuntime>>
  >(initialState.workspace.runtimeByTurn);
  const [conversationSummaries, setConversationSummaries] = useState(
    listResearchConversationSummaries,
  );
  const [composerError, setComposerError] = useState(initialState.composerError);
  const sessionRef = useRef(session);
  const runtimeRef = useRef(runtimeByTurn);
  const submissionInFlightRef = useRef<{
    readonly prompt: string;
    readonly promise: Promise<boolean>;
  }>();

  const updateSession = useCallback((
    updater: (current: ResearchConversationSession) => ResearchConversationSession,
  ) => {
    const next = updater(sessionRef.current);
    sessionRef.current = next;
    setSession(next);
  }, []);

  const updateRuntime = useCallback((
    updater: (
      current: Readonly<Record<string, ResearchTurnRuntime>>,
    ) => Readonly<Record<string, ResearchTurnRuntime>>,
  ) => {
    const next = updater(runtimeRef.current);
    runtimeRef.current = next;
    setRuntimeByTurn(next);
  }, []);

  const completeRun = useCallback((
    runId: string,
    turnId: string,
    status: Extract<PersistedTurnStatus, "complete" | "error" | "canceled" | "resumable">,
    errorMessage?: string,
  ) => {
    const completedAt = Date.now();
    updateRuntime((current) => ({
      ...current,
      [turnId]: {
        ...current[turnId],
        completedAt,
        error: status === "error" || status === "resumable"
          ? errorMessage ?? (status === "resumable"
            ? "근거 승인 후 연구를 계속할 수 있습니다."
            : "연구 실행이 완료되지 않았습니다.")
          : undefined,
        startedAt: current[turnId]?.startedAt ?? completedAt,
        status,
      },
    }));
    if (status === "complete") markRunDone(runId);
    else markRunFailed(runId);
  }, [updateRuntime]);

  const recordConversationEvent = useCallback((
    event: Parameters<typeof recordResearchConversationEvent>[1],
  ) => {
    updateSession((current) => recordResearchConversationEvent(current, event));
  }, [updateSession]);

  const {
    activeTurnId,
    answerInteraction,
    attachRun,
    cancelActiveRun,
    pendingInteraction,
    resumeRun,
  } = useResearchPipelineBridge({
    onActivity: (_runId, turnId, projections) => {
      updateRuntime((current) => projectTurnActivity(current, turnId, projections));
    },
    onConversationEvent: recordConversationEvent,
    onError: () => setComposerError("검토 응답을 보내지 못했습니다. 다시 시도하세요."),
    onTerminal: completeRun,
  });

  useEffect(() => {
    persistResearchWorkspace(session, stripTransientRuntime(runtimeByTurn));
    setConversationSummaries(listResearchConversationSummaries());
  }, [runtimeByTurn, session]);

  useEffect(() => {
    let mounted = true;
    const initialWorkspace = initialState.workspace;
    const resumableTurn = [...initialWorkspace.session.turns].reverse().find((turn) => (
      initialWorkspace.runtimeByTurn[turn.turnId]?.status === "running"
    ));
    const generation = resumableTurn
      ? initialWorkspace.runtimeByTurn[resumableTurn.turnId]?.generation
      : undefined;
    if (resumableTurn && generation !== undefined) {
      void attachRun(resumableTurn.runId, resumableTurn.turnId, generation).catch((error) => {
        if (!mounted) return;
        const detail = error instanceof Error && error.message.trim()
          ? ` ${error.message.trim()}`
          : "";
        const message = `이전 연구 실행에 다시 연결하지 못했습니다.${detail}`;
        completeRun(resumableTurn.runId, resumableTurn.turnId, "error", message);
        setComposerError(message);
      });
    }
    return () => {
      mounted = false;
    };
  }, [attachRun, completeRun, initialState.workspace]);

  const submit = useCallback((prompt: string): Promise<boolean> => {
    const normalizedPrompt = prompt.trim();
    if (!normalizedPrompt) {
      setComposerError("연구 질문을 한 문장 이상 입력하세요.");
      return Promise.resolve(false);
    }
    const activeSubmission = submissionInFlightRef.current;
    if (activeSubmission) {
      if (activeSubmission.prompt === normalizedPrompt) return activeSubmission.promise;
      setComposerError("현재 연구가 끝난 뒤 후속 질문을 보낼 수 있습니다.");
      return Promise.resolve(false);
    }
    if (
      activeTurnId ||
      Object.values(runtimeRef.current).some((runtime) => runtime.status === "running")
    ) {
      setComposerError("현재 연구가 끝난 뒤 후속 질문을 보낼 수 있습니다.");
      return Promise.resolve(false);
    }

    setComposerError(undefined);
    const submission = (async () => {
      const runId = createResearchIdentifier("run");
      const turnId = createResearchIdentifier("turn");
      updateSession((current) => startResearchConversationTurn(current, {
        prompt: normalizedPrompt,
        runId,
        turnId,
      }));

      const startedAt = Date.now();
      try {
        const profile = buildSourceExecutionProfile();
        updateRuntime((current) => ({
          ...current,
          [turnId]: {
            skippedSources: profile.publicMetadata.skippedSources,
            startedAt,
            status: "running",
          },
        }));
        pushRun(runId, normalizedPrompt);
        const environment = composeResearchExecutionEnvironment(
          readEnvsFromSettings(),
          profile,
        );
        const receipt = await submitIdea(
          normalizedPrompt,
          "full",
          readResearchDepth(),
          environment,
          runId,
        );
        updateRuntime((current) => ({
          ...current,
          [turnId]: {
            ...current[turnId],
            generation: receipt.generation,
            startedAt,
            status: "running",
          },
        }));
        const attached = await attachRun(runId, turnId, receipt.generation);
        if (!attached) throw new Error("연구 이벤트 연결이 취소되었습니다.");
        return true;
      } catch (error) {
        completeRun(runId, turnId, "error");
        const detail = error instanceof Error ? ` ${error.message}` : "";
        setComposerError(`연구를 시작하지 못했습니다.${detail}`);
        return false;
      }
    })();
    submissionInFlightRef.current = { prompt: normalizedPrompt, promise: submission };
    void submission.finally(() => {
      if (submissionInFlightRef.current?.promise === submission) {
        submissionInFlightRef.current = undefined;
      }
    });
    return submission;
  }, [
    activeTurnId,
    attachRun,
    buildSourceExecutionProfile,
    completeRun,
    updateRuntime,
    updateSession,
  ]);

  const exportTurn = useCallback((turnId: string) => {
    downloadResearchTurn(sessionRef.current, turnId);
  }, []);

  const deleteConversation = useCallback((sessionId: string): boolean => {
    deleteResearchSession(sessionId);
    if (sessionId === sessionRef.current.sessionId) {
      const remaining = listResearchConversationSummaries();
      const next = remaining[0];
      const workspace = next
        ? switchResearchWorkspace(next.sessionId)
        : createResearchWorkspace();
      if (workspace) {
        sessionRef.current = workspace.session;
        runtimeRef.current = workspace.runtimeByTurn;
        setSession(workspace.session);
        setRuntimeByTurn(workspace.runtimeByTurn);
      }
    }
    setConversationSummaries(listResearchConversationSummaries());
    setComposerError(undefined);
    return true;
  }, []);

  const newConversation = useCallback((): boolean => {
    if (!canChangeResearchConversation(activeTurnId, runtimeRef.current)) {
      setComposerError("현재 연구가 끝난 뒤 새 대화를 만들 수 있습니다.");
      return false;
    }
    const workspace = createResearchWorkspace();
    sessionRef.current = workspace.session;
    runtimeRef.current = workspace.runtimeByTurn;
    setSession(workspace.session);
    setRuntimeByTurn(workspace.runtimeByTurn);
    setConversationSummaries(listResearchConversationSummaries());
    setComposerError(undefined);
    return true;
  }, [activeTurnId]);

  const switchConversation = useCallback((sessionId: string): boolean => {
    if (!canChangeResearchConversation(activeTurnId, runtimeRef.current)) {
      setComposerError("현재 연구가 끝난 뒤 대화를 전환할 수 있습니다.");
      return false;
    }
    const workspace = switchResearchWorkspace(sessionId);
    if (!workspace) {
      setComposerError("저장된 연구 대화를 불러오지 못했습니다.");
      return false;
    }
    sessionRef.current = workspace.session;
    runtimeRef.current = workspace.runtimeByTurn;
    setSession(workspace.session);
    setRuntimeByTurn(workspace.runtimeByTurn);
    setConversationSummaries(listResearchConversationSummaries());
    setComposerError(undefined);
    return true;
  }, [activeTurnId]);

  const cancelTurn = useCallback(async (turnId: string) => {
    const runtime = runtimeRef.current[turnId];
    if (!runtime || runtime.status !== "running" || activeTurnId !== turnId) return;
    updateRuntime((current) => setTurnCancellationRequested(current, turnId, true));
    const acknowledged = await cancelActiveRun();
    if (!acknowledged) {
      updateRuntime((current) => setTurnCancellationRequested(current, turnId, false));
      setComposerError("실행 종료 요청을 확인하지 못했습니다. 다시 시도하세요.");
    }
  }, [activeTurnId, cancelActiveRun, updateRuntime]);

  const runningTurnId = Object.entries(runtimeByTurn)
    .find(([, runtime]) => runtime.status === "running")?.[0];

  const reopenApproval = useCallback((turnId: string): void => {
    const runtime = runtimeRef.current[turnId];
    if (!runtime || runtime.generation === undefined) return;
    const run = runtimeByTurn[turnId];
    const turn = [...session.turns].reverse().find((candidate) => candidate.turnId === turnId);
    if (!turn) return;
    void resumeRun(turn.runId, turnId, runtime.generation).catch(() => {
      setComposerError("승인 화면을 다시 열지 못했습니다.");
    });
    if (!run) return;
  }, [resumeRun, runtimeByTurn, session.turns]);

  const resumeWithComment = useCallback(async (turnId: string, comment: string): Promise<boolean> => {
    const runtime = runtimeRef.current[turnId];
    if (!runtime || runtime.generation === undefined) return false;
    const turn = [...session.turns].reverse().find((candidate) => candidate.turnId === turnId);
    if (!turn) return false;
    try {
      return await resumeRun(turn.runId, turnId, runtime.generation, comment);
    } catch {
      setComposerError("수정 의견을 보내지 못했습니다.");
      return false;
    }
  }, [resumeRun, session.turns]);

  return {
    activeTurnId: activeTurnId ?? runningTurnId,
    composerError,
    conversationSummaries,
    isRunning: Boolean(activeTurnId || runningTurnId),
    pendingInteraction,
    runtimeByTurn,
    session,
    answerInteraction,
    cancelTurn,
    deleteConversation,
    exportTurn,
    newConversation,
    reopenApproval,
    resumeWithComment,
    submit,
    switchConversation,
  };
}
