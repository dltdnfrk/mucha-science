import type { PipelineLaunchReceipt } from "./researchExecution";
import {
  cancelWebPipeline,
  startWebPipeline,
} from "./webPipelineClient";

export type PipelineMode = "stub" | "full";
export type ResearchDepth = "shallow" | "deep" | "max" | "superdeep";

export interface PipelineRuntimeStatus {
  running: boolean;
  stdin_open?: boolean;
  child_tracked?: boolean;
  buffered_event_count?: number;
  child_pid?: number | null;
  app_run_id?: string | null;
  runtime_age_ms?: number | null;
  last_event_elapsed_ms?: number | null;
  app_binary_path?: string | null;
  workspace_root?: string;
}

export interface PipelineCancellationAcknowledgement {
  acknowledged: boolean;
  app_run_id: string;
  generation: number;
  termination_observed: boolean;
  reaped: boolean;
  kill_sent: boolean;
}

export async function submitIdea(
  topic: string,
  pipeline: PipelineMode = "full",
  depth: ResearchDepth = "deep",
  envs?: Record<string, string>,
  appRunId?: string,
): Promise<PipelineLaunchReceipt> {
  if (!appRunId) {
    throw new Error("A browser pipeline run requires an app run ID.");
  }
  return startWebPipeline(topic, pipeline, depth, envs ?? {}, appRunId);
}

export async function cancelPipeline(
  appRunId: string,
  generation: number,
): Promise<PipelineCancellationAcknowledgement> {
  return cancelWebPipeline(appRunId, generation);
}
