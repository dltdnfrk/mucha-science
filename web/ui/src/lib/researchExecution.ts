export type PipelineProcessIdentity = {
  readonly pid: number;
  readonly process_start_time: string;
  readonly pgid: number;
  readonly launch_nonce: string;
  readonly generation: number;
  readonly owner_boot_id: string;
  readonly executable_digest: string;
};

export type PipelineLaunchReceipt = {
  readonly app_run_id: string;
  readonly generation: number;
  readonly launch_nonce: string;
  readonly owner_boot_id: string;
  readonly executable_path: string;
  readonly executable_digest: string;
  readonly reserved_at_unix_ms: number;
  readonly phase:
    | "reserved"
    | "spawned"
    | "running"
    | "cancel_requested"
    | "exit_observed"
    | "terminal";
  readonly identity: PipelineProcessIdentity | null;
  readonly terminal_kind: "completed" | "failed" | "canceled" | null;
  readonly termination_observed: boolean;
  readonly reaped: boolean;
  readonly termination_kill_sent: boolean;
};

export type ResearchCycleCompanion = {
  readonly cycleId: string;
  readonly researchRunId: string;
};

export type ResearchExecutionResult = {
  readonly companion: ResearchCycleCompanion;
  readonly receipt: PipelineLaunchReceipt;
};

export type ResearchRuntimeContext = {
  readonly runId: string;
  readonly turnId: string;
  readonly eventIndex: number;
  readonly generation: number;
};

type ResearchExecutionAuthorityDependencies = {
  readonly acceptCycle: (appRunId: string) => Promise<ResearchCycleCompanion>;
  readonly launchPipeline: (appRunId: string) => Promise<PipelineLaunchReceipt>;
};

class ResearchRunIdentityError extends Error {
  constructor() {
    super("accepted cycle research run identity does not match the app run");
    this.name = "ResearchRunIdentityError";
  }
}

export function createResearchExecutionAuthority({
  acceptCycle,
  launchPipeline,
}: ResearchExecutionAuthorityDependencies) {
  const executions = new Map<string, Promise<ResearchExecutionResult>>();
  return {
    execute(appRunId: string): Promise<ResearchExecutionResult> {
      const existing = executions.get(appRunId);
      if (existing) return existing;
      const execution = acceptCycle(appRunId).then(async (companion) => {
        if (companion.researchRunId !== appRunId) {
          throw new ResearchRunIdentityError();
        }
        const receipt = await launchPipeline(appRunId);
        return { companion, receipt };
      });
      executions.set(appRunId, execution);
      void execution.catch(() => {
        if (executions.get(appRunId) === execution) executions.delete(appRunId);
      });
      return execution;
    },
  };
}
