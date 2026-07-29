import {
  initialScientificState,
  scientificReducer,
} from "../lib/scientificReducer";
import {
  acceptedCycleId,
  abortPayloadFromServer,
  createScientificAction,
  listenScientificErrors,
  listenScientificResponses,
  sendScientificAction,
  startScientificSidecar,
  stopScientificSidecar,
  supportsScientificAction,
  welcomeCapabilities,
} from "../lib/tauri";
import type {
  CycleAbortPayload,
  ScientificCapabilities,
  ScientificEnvelope,
} from "../lib/tauri";
import type {
  ScientificActionName,
  ScientificEvent,
} from "../lib/types";

export const CREATOR_ACCOUNTABILITY = {
  actor_kind: "human",
  display_name: "operator",
  organization: null,
  role: "operator",
  assertion_source: "operator_entry",
  verification_status: "operator_asserted_unverified",
  authority_scope: { kind: "none", scope: null },
  external_reference: null,
} as const;

export const WORKFLOW_ACTIONS: readonly ScientificActionName[] = [
  "cycle.continue",
  "responsibility.question_selection.disposition",
  "responsibility.safety_ethics_review.disposition",
  "responsibility.execution_accountability.disposition",
  "responsibility.exception_interpretation.disposition",
  "responsibility.novelty_value_judgment.disposition",
  "responsibility.final_accountability.disposition",
  "responsibility.disposition.supersede",
  "proposal.reject",
  "result.submit",
  "validation.adjudicate",
  "export.create",
  "export.get",
  "report.render",
];

export const VALIDATION_DETAIL_ACTIONS = [
  "cycle.replay",
  "cycle.resume",
  "export.get",
  "report.render",
  "cycle.ack",
] as const satisfies readonly ScientificActionName[];

export interface ScientificCycleCompanion {
  readonly cycleId: string;
  readonly researchRunId: string;
}

export function acceptedCycleCompanionFromResponse(
  response: ScientificEnvelope,
  expectedResearchRunId: string,
): ScientificCycleCompanion | undefined {
  const cycleId = acceptedCycleId(response);
  const result = response.payload.result;
  if (
    !cycleId
  ) {
    return undefined;
  }
  if (
    typeof result !== "object" ||
    result === null ||
    Array.isArray(result) ||
    !("research_run_id" in result) ||
    result.research_run_id !== expectedResearchRunId
  ) {
    throw new ScientificCycleCompanionError(
      "accepted cycle research run identity does not match the app run",
    );
  }
  return { cycleId, researchRunId: expectedResearchRunId };
}

class ScientificCycleCompanionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ScientificCycleCompanionError";
  }
}

export type PageScientificAction = ScientificEvent | { resetScientificPage: true };

export interface CycleStartRequestState {
  pendingMessageIds: ReadonlySet<string>;
  inFlight: boolean;
  startRequested: boolean;
  creationIdempotencyKey?: string;
}

export interface RetainedAbortMetadata {
  payload: CycleAbortPayload;
  cycleId: string;
  revision: number;
}

export function clearRejectedCycleStartRequest(
  state: CycleStartRequestState,
  error: ScientificEnvelope,
): CycleStartRequestState {
  if (
    error.name !== "command.rejected.error" ||
    !error.correlation_id ||
    !state.pendingMessageIds.has(error.correlation_id)
  ) {
    return state;
  }
  const pendingMessageIds = new Set(state.pendingMessageIds);
  pendingMessageIds.delete(error.correlation_id);
  return {
    ...state,
    pendingMessageIds,
    inFlight: false,
    startRequested: false,
  };
}

export function pageScientificReducer(
  state: typeof initialScientificState,
  action: PageScientificAction,
) {
  return "resetScientificPage" in action
    ? initialScientificState
    : scientificReducer(state, action);
}

let sidecarLifecycle: Promise<void> = Promise.resolve();
let activeSidecarGeneration: number | undefined;
let nextSidecarGeneration = 0;

export function queueSidecarStart() {
  const generation = ++nextSidecarGeneration;
  const completion = sidecarLifecycle.then(async () => {
    await startScientificSidecar();
    activeSidecarGeneration = generation;
  });
  sidecarLifecycle = completion.catch(() => undefined);
  return { generation, completion };
}

export function queueSidecarStop(generation: number): Promise<void> {
  const completion = sidecarLifecycle.then(async () => {
    if (activeSidecarGeneration !== generation) return;
    await stopScientificSidecar();
    activeSidecarGeneration = undefined;
  });
  sidecarLifecycle = completion.catch(() => undefined);
  return completion;
}

export function createHello(clientInstanceId: string): ScientificEnvelope {
  const handshakeIdempotencyKey = protocolId("idempotency");
  return createScientificAction("protocol.hello", {
    handshake_idempotency_key: handshakeIdempotencyKey,
    client_instance_id: clientInstanceId,
    supported_versions: ["ai-scientist.v1"],
    capabilities: [],
    projection: "scientific-cycle.v1",
    cursors: [],
  }, { idempotencyKey: handshakeIdempotencyKey });
}

export async function acceptScientificCycleCompanion(
  researchRunId: string,
  rawQuestion: string,
): Promise<ScientificCycleCompanion> {
  const cleanups: (() => void)[] = [];
  let sidecarGeneration: number | undefined;
  let expectedStartMessageId: string | undefined;
  let resolveWelcome: ((capabilities: ScientificCapabilities) => void) | undefined;
  let resolveAccepted: ((companion: ScientificCycleCompanion) => void) | undefined;
  let rejectFailure: ((error: ScientificCycleCompanionError) => void) | undefined;
  const welcome = new Promise<ScientificCapabilities>((resolve) => {
    resolveWelcome = resolve;
  });
  const accepted = new Promise<ScientificCycleCompanion>((resolve) => {
    resolveAccepted = resolve;
  });
  const failed = new Promise<never>((_, reject) => {
    rejectFailure = (error) => reject(error);
  });

  try {
    cleanups.push(await listenScientificResponses((response) => {
      const capabilities = welcomeCapabilities(response);
      if (capabilities) resolveWelcome?.(capabilities);
      if (
        expectedStartMessageId &&
        response.correlation_id === expectedStartMessageId
      ) {
        try {
          const companion = acceptedCycleCompanionFromResponse(
            response,
            researchRunId,
          );
          if (companion) resolveAccepted?.(companion);
        } catch (error) {
          rejectFailure?.(error instanceof ScientificCycleCompanionError
            ? error
            : new ScientificCycleCompanionError(String(error)));
        }
      }
    }));
    cleanups.push(await listenScientificErrors((error) => {
      if (
        !expectedStartMessageId ||
        error.correlation_id === expectedStartMessageId
      ) {
        rejectFailure?.(new ScientificCycleCompanionError(
          `scientific cycle request was rejected: ${error.name}`,
        ));
      }
    }));

    const sidecar = queueSidecarStart();
    sidecarGeneration = sidecar.generation;
    await sidecar.completion;
    await sendScientificAction(createHello(protocolId("client")));
    const capabilities = await Promise.race([welcome, failed]);
    if (!supportsScientificAction(capabilities, "cycle.start")) {
      throw new ScientificCycleCompanionError(
        "scientific sidecar does not advertise cycle.start",
      );
    }
    const creationIdempotencyKey = researchRunId.replace(
      /^run_/,
      "idempotency_",
    );
    const startPayload = {
      creation_idempotency_key: creationIdempotencyKey,
      expected_revision: 0 as const,
      raw_question: rawQuestion,
      research_run_id: researchRunId,
      contract_version: "ai-scientist.v1" as const,
      boundary: {
        kind: "cognitive_only" as const,
        description: "This client only performs cognitive work and external handoff.",
      },
      creator: CREATOR_ACCOUNTABILITY,
    };
    const start = createScientificAction(
      "cycle.start",
      startPayload,
      { idempotencyKey: creationIdempotencyKey },
    );
    expectedStartMessageId = start.message_id;
    await sendScientificAction(start);
    return await Promise.race([accepted, failed]);
  } finally {
    cleanups.splice(0).forEach((cleanup) => cleanup());
    if (sidecarGeneration !== undefined) {
      await queueSidecarStop(sidecarGeneration);
    }
  }
}

export function protocolId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID().replaceAll("-", "")}`;
}

export function exportIdFromEvent(event: ScientificEvent): string | undefined {
  const exportId = typeof event.payload === "object" &&
    event.payload !== null &&
    !Array.isArray(event.payload)
    ? (event.payload as Record<string, unknown>).export_id
    : undefined;
  return typeof exportId === "string" ? exportId : undefined;
}

export function scientificErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("transformCallback")
    ? "브라우저 미리보기에서는 데스크톱 사이드카 브리지를 사용할 수 없습니다."
    : message;
}

export function abortMetadataForActiveCycle(
  envelope: ScientificEnvelope,
  activeCycleId: string | undefined,
  revision: number,
): RetainedAbortMetadata | undefined {
  const payload = abortPayloadFromServer(envelope);
  return payload &&
      activeCycleId &&
      envelope.cycle_id === activeCycleId &&
      envelope.revision === revision &&
      payload.expected_revision === revision
    ? { payload, cycleId: activeCycleId, revision }
    : undefined;
}
