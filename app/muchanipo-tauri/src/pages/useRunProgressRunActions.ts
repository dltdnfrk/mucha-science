import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { submitIdea, sendAction, type PipelineMode } from "../lib/tauriClient";
import { markRunFailed, markRunRunning } from "../lib/runsIndex";
import { clearRunScopedSessionKeys } from "./runProgressStages";
import { readEnvsFromSettings, readResearchDepth } from "./runProgressSettings";

type RunActionsProps = {
  readonly runId?: string;
  readonly topic: string;
  readonly aborting: boolean;
  readonly runErrorRef: MutableRefObject<string | null>;
  readonly setRunError: Dispatch<SetStateAction<string | null>>;
  readonly setRunWarnings: Dispatch<SetStateAction<string[]>>;
  readonly setTopic: Dispatch<SetStateAction<string>>;
  readonly setInterviewSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setHitlSubmitting: Dispatch<SetStateAction<boolean>>;
  readonly setAborting: Dispatch<SetStateAction<boolean>>;
  readonly resetExecutionArtifacts: () => void;
  readonly resetResearchArtifacts: () => void;
  readonly resetCouncilArtifacts: () => void;
  readonly resetInteractionArtifacts: () => void;
};

function clearPersistedArtifacts(runId: string): void {
  localStorage.removeItem(`run:${runId}:sources`);
  localStorage.removeItem(`run:${runId}:gaps`);
  for (const suffix of [
    "report", "report_path", "vault_path", "chapter_count", "pending", "pending_at",
  ]) {
    localStorage.removeItem(`run:${runId}:${suffix}`);
  }
  sessionStorage.removeItem(`run:${runId}:pending_session`);
  clearRunScopedSessionKeys(runId);
  markRunRunning(runId);
}

export function useRunProgressRunActions(props: RunActionsProps) {
  const failRun = useCallback((message: string) => {
    props.runErrorRef.current = message;
    props.setRunError(message);
    props.setInterviewSubmitting(false);
    props.setHitlSubmitting(false);
    if (props.runId) markRunFailed(props.runId);
  }, [props.runId]);

  const startRunFromTopic = useCallback(async (
    runTopic: string,
    options: { clearArtifacts?: boolean; warning?: string } = {},
  ) => {
    if (!props.runId) return false;
    const trimmed = runTopic.trim();
    if (!trimmed) {
      failRun("주제 정보가 없습니다.");
      return false;
    }
    props.runErrorRef.current = null;
    props.setRunError(null);
    props.setRunWarnings(options.warning ? [options.warning] : []);
    props.setTopic(trimmed);

    if (options.clearArtifacts) {
      props.resetExecutionArtifacts();
      props.resetResearchArtifacts();
      props.resetCouncilArtifacts();
      props.resetInteractionArtifacts();
      try {
        clearPersistedArtifacts(props.runId);
      } catch (error) {
        if (!(error instanceof Error)) throw error;
      }
    }

    try {
      const pipelineMode =
        (localStorage.getItem("pipeline_mode") as PipelineMode | null) || "full";
      await submitIdea(
        trimmed,
        pipelineMode,
        readResearchDepth(),
        readEnvsFromSettings(),
        props.runId,
      );
      return true;
    } catch (error) {
      failRun(error instanceof Error ? error.message : String(error));
      return false;
    }
  }, [
    failRun,
    props.runId,
    props.resetExecutionArtifacts,
    props.resetResearchArtifacts,
    props.resetCouncilArtifacts,
    props.resetInteractionArtifacts,
  ]);

  const abortRun = useCallback(async () => {
    if (props.aborting) return;
    props.setAborting(true);
    try {
      await sendAction({ action: "abort" });
    } catch (error) {
      failRun(error instanceof Error ? error.message : String(error));
    } finally {
      props.setAborting(false);
    }
  }, [props.aborting, failRun]);

  const restartRun = useCallback(async () => {
    if (!props.runId) return;
    const runTopic =
      props.topic || localStorage.getItem(`run:${props.runId}:topic`) || "";
    await startRunFromTopic(runTopic, { clearArtifacts: true });
  }, [props.runId, props.topic, startRunFromTopic]);

  return { failRun, startRunFromTopic, abortRun, restartRun };
}
