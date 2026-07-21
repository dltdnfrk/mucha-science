import { useEffect, useReducer, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScientificCycleView } from "../components/ScientificCycleView";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import {
  initialScientificState,
  scientificReducer,
} from "../lib/scientificReducer";
import {
  abortPayloadFromServer,
  acceptedCycleId,
  createAcknowledgementForScientificEvent,
  createAdvertisedScientificAction,
  createScientificAction,
  listenScientificErrors,
  listenScientificEvents,
  listenScientificResponses,
  sendScientificAction,
  startScientificSidecar,
  stopScientificSidecar,
  supportsScientificAction,
  toScientificEvent,
  welcomeCapabilities,
  type CycleAbortPayload,
  type ScientificCapabilities,
  type ScientificEnvelope,
} from "../lib/tauri";
import type {
  ScientificActionName,
  ScientificActionPayloadMap,
  ScientificEvent,
} from "../lib/types";

const CREATOR_ACCOUNTABILITY = {
  actor_kind: "human",
  display_name: "operator",
  organization: null,
  role: "operator",
  assertion_source: "operator_entry",
  verification_status: "operator_asserted_unverified",
  authority_scope: { kind: "none", scope: null },
  external_reference: null,
} as const;
type PageScientificAction = ScientificEvent | { resetScientificPage: true };
const WORKFLOW_ACTIONS: readonly ScientificActionName[] = [
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
export interface CycleStartRequestState {
  pendingMessageIds: ReadonlySet<string>;
  inFlight: boolean;
  startRequested: boolean;
  creationIdempotencyKey?: string;
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

function pageScientificReducer(
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

function queueSidecarStart() {
  const generation = ++nextSidecarGeneration;
  const completion = sidecarLifecycle.then(async () => {
    await startScientificSidecar();
    activeSidecarGeneration = generation;
  });
  sidecarLifecycle = completion.catch(() => undefined);
  return { generation, completion };
}

function queueSidecarStop(generation: number): Promise<void> {
  const completion = sidecarLifecycle.then(async () => {
    if (activeSidecarGeneration !== generation) return;
    await stopScientificSidecar();
    activeSidecarGeneration = undefined;
  });
  sidecarLifecycle = completion.catch(() => undefined);
  return completion;
}

export default function ScientificPage() {
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(pageScientificReducer, initialScientificState);
  const [question, setQuestion] = useState("");
  const [capabilities, setCapabilities] = useState<ScientificCapabilities>();
  const [responses, setResponses] = useState<ScientificEnvelope[]>([]);
  const [errors, setErrors] = useState<ScientificEnvelope[]>([]);
  const [actionError, setActionError] = useState<string>();
  const [abortPayload, setAbortPayload] = useState<RetainedAbortMetadata>();
  const creationIdempotencyKey = useRef<string | undefined>(undefined);
  const cycleId = useRef<string | undefined>(undefined);
  const pendingStartMessageIds = useRef(new Set<string>());
  const startRequestInFlight = useRef(false);
  const [startRequested, setStartRequested] = useState(false);
  const capabilitiesRef = useRef<ScientificCapabilities | undefined>(undefined);
  const abortPayloadRef = useRef<RetainedAbortMetadata | undefined>(undefined);
  const stateRef = useRef(initialScientificState);
  const clientInstanceId = useRef(protocolId("client"));
  const requestOrdinal = useRef(0);
  const ackOrdinal = useRef(0);
  const committedMessageIds = useRef(new Set<string>());
  const retiredCycleIds = useRef(new Set<string>());
  stateRef.current = state;

  useEffect(() => {
    let active = true;
    const cleanups: (() => void)[] = [];
    let listenersDisposed = false;
    let sidecarGeneration: number | undefined;
    const addCleanup = (cleanup: () => void) => {
      if (listenersDisposed) cleanup();
      else cleanups.push(cleanup);
    };
    const cleanupListeners = () => {
      listenersDisposed = true;
      cleanups.splice(0).forEach((cleanup) => cleanup());
    };

    const retainAbortMetadata = (envelope: ScientificEnvelope) => {
      const metadata = abortMetadataForActiveCycle(
        envelope,
        cycleId.current,
        stateRef.current.revision,
      );
      if (metadata) {
        abortPayloadRef.current = metadata;
        setAbortPayload(metadata);
      }
    };

    const registerListeners = async () => {
      try {
        addCleanup(await listenScientificEvents((envelope) => {
          if (!active || !cycleId.current || envelope.cycle_id !== cycleId.current ||
              retiredCycleIds.current.has(envelope.cycle_id)) return;
          const event = toScientificEvent(envelope);
          if (!event) return;

          const previousState = stateRef.current;
          const nextState = scientificReducer(previousState, event);
          stateRef.current = nextState;
          dispatch(event);
          const newlyCommitted = nextState.events.slice(previousState.events.length);

          for (const committedEvent of newlyCommitted) {
            if (committedMessageIds.current.has(committedEvent.message_id)) continue;
            committedMessageIds.current.add(committedEvent.message_id);

            const checkpoint = nextState.checkpoint;
            const stateHash = nextState.state_hash;
            const acknowledgement = committedEvent.type === "cycle.snapshot" &&
              checkpoint &&
              stateHash &&
              checkpoint.cycle_id === committedEvent.session_id &&
              supportsScientificAction(capabilitiesRef.current, "cycle.ack")
              ? createAcknowledgementForScientificEvent(
                capabilitiesRef.current,
                committedEvent,
                {
                  client_instance_id: clientInstanceId.current,
                  ack_ordinal: ++ackOrdinal.current,
                  checkpoint,
                  state_hash: stateHash,
                },
              )
              : undefined;
            if (acknowledgement) {
              void sendScientificAction(acknowledgement).catch((error: unknown) => {
                if (active) setActionError(messageFrom(error));
              });
            }

            if (committedEvent.type === "export.created") {
              const exportId = exportIdFromEvent(committedEvent);
              const exportGet = exportId &&
                supportsScientificAction(capabilitiesRef.current, "export.get")
                ? createAdvertisedScientificAction(
                  capabilitiesRef.current,
                  "export.get",
                  {
                    client_instance_id: clientInstanceId.current,
                    request_ordinal: ++requestOrdinal.current,
                    export_id: exportId,
                    include_archive_bytes: false,
                  },
                  {
                    cycleId: committedEvent.session_id,
                  },
                )
                : undefined;
              if (exportGet) {
                void sendScientificAction(exportGet).catch((error: unknown) => {
                  if (active) setActionError(messageFrom(error));
                });
              }
            }
          }

          if (newlyCommitted.some(({ message_id }) => message_id === event.message_id)) {
            retainAbortMetadata(envelope);
          }
        }));
        addCleanup(await listenScientificResponses((response) => {
          if (!active) return;
          setResponses((current) => [...current, response]);

          const advertised = welcomeCapabilities(response);
          if (advertised) {
            capabilitiesRef.current = advertised;
            setCapabilities(advertised);
          } else if (response.name === "protocol.welcome.response") {
            setActionError("The server welcome response did not advertise valid capabilities.");
          }

          const acceptedId = acceptedCycleId(response);
          if (
            acceptedId &&
            !cycleId.current &&
            response.correlation_id &&
            pendingStartMessageIds.current.has(response.correlation_id)
          ) {
            cycleId.current = acceptedId;
            startRequestInFlight.current = false;
            setStartRequested(false);
          }
          retainAbortMetadata(response);
        }));
        addCleanup(await listenScientificErrors((error) => {
          if (!active) return;
          setErrors((current) => [...current, error]);
          const requestState = clearRejectedCycleStartRequest({
            pendingMessageIds: pendingStartMessageIds.current,
            inFlight: startRequestInFlight.current,
            startRequested: true,
            creationIdempotencyKey: creationIdempotencyKey.current,
          }, error);
          if (requestState.pendingMessageIds === pendingStartMessageIds.current) return;
          pendingStartMessageIds.current = new Set(requestState.pendingMessageIds);
          startRequestInFlight.current = requestState.inFlight;
          setStartRequested(requestState.startRequested);
        }));

        if (!active) {
          cleanupListeners();
          return;
        }
        const sidecar = queueSidecarStart();
        sidecarGeneration = sidecar.generation;
        await sidecar.completion;
        if (!active) return;
        await sendScientificAction(createHello(clientInstanceId.current));
      } catch (error) {
        cleanupListeners();
        if (active) setActionError(messageFrom(error));
      }
    };

    void registerListeners();

    return () => {
      active = false;
      cleanupListeners();
      if (sidecarGeneration !== undefined) {
        void queueSidecarStop(sidecarGeneration).catch(() => undefined);
      }
    };
  }, []);

  const send = async <TName extends ScientificActionName>(
    name: TName,
    payload: ScientificActionPayloadMap[TName],
  ) => {
    setActionError(undefined);
    if (!supportsScientificAction(capabilities, name)) {
      setActionError(`The server did not advertise ${name}.`);
      return false;
    }
    if (name !== "cycle.start" && !cycleId.current) {
      setActionError(`A server-owned cycle ID is required for ${name}.`);
      return false;
    }

    const idempotencyKey = name === "cycle.start"
      ? (payload as ScientificActionPayloadMap["cycle.start"]).creation_idempotency_key
      : undefined;
    const action = createAdvertisedScientificAction(capabilities, name, payload, {
      cycleId: name === "cycle.start" ? null : cycleId.current ?? null,
      idempotencyKey,
    });
    if (!action) {
      setActionError(`The server did not advertise ${name}.`);
      return false;
    }

    try {
      if (name === "cycle.start") {
        pendingStartMessageIds.current.add(action.message_id);
      }
      await sendScientificAction(action);
      return true;
    } catch (error) {
      if (name === "cycle.start") {
        pendingStartMessageIds.current.delete(action.message_id);
      }
      setActionError(messageFrom(error));
      return false;
    }
  };

  const startCycle = () => {
    if (cycleId.current || startRequestInFlight.current) {
      setActionError("Reset the current cycle before starting another one.");
      return;
    }

    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setActionError("Enter a question before starting a cycle.");
      return;
    }
    const idempotencyKey = creationIdempotencyKey.current ?? `idempotency_${crypto.randomUUID().replaceAll("-", "")}`;
    creationIdempotencyKey.current = idempotencyKey;
    startRequestInFlight.current = true;
    setStartRequested(true);
    void send("cycle.start", {
      creation_idempotency_key: idempotencyKey,
      expected_revision: 0,
      raw_question: trimmedQuestion,
      contract_version: "ai-scientist.v1",
      boundary: {
        kind: "cognitive_only",
        description: "This client only performs cognitive work and external handoff.",
      },
      creator: CREATOR_ACCOUNTABILITY,
    }).then((sent) => {
      if (!sent) {
        startRequestInFlight.current = false;
        setStartRequested(false);
      }
    });
  };

  const recoveryAction = state.recovery?.kind === "snapshot" ? "cycle.resume" : "cycle.replay";
  const recoveryUnavailableReason =
    !state.recovery
      ? "No server recovery request."
      : !cycleId.current
        ? "Waiting for a server-owned cycle ID."
        : !supportsScientificAction(capabilities, recoveryAction)
          ? `The server did not advertise ${recoveryAction}.`
          : undefined;
  const abortUnavailableReason =
    !cycleId.current
      ? "Waiting for a server-owned cycle ID."
      : !supportsScientificAction(capabilities, "cycle.abort")
        ? "The server did not advertise cycle.abort."
        : !abortPayload ||
            abortPayload.cycleId !== cycleId.current ||
            abortPayload.revision !== state.revision ||
            abortPayload.payload.expected_revision !== state.revision
          ? "Required current-cycle abort metadata has not been supplied by the server."
          : undefined;
  const exportUnavailableReason =
    !cycleId.current
      ? "Waiting for a server-owned cycle ID."
      : !supportsScientificAction(capabilities, "export.create")
        ? "The server did not advertise export.create."
        : !state.export_allowed
          ? "The server has not reported that export gates are satisfied."
          : undefined;
  const terminalCycle = state.events.some(
    (event) => event.type === "cycle.completed" || event.type === "cycle.aborted",
  );
  const resetUnavailableReason =
    !cycleId.current
      ? "No active cycle to reset."
      : !terminalCycle
        ? "The server must report completion or abort before a new cycle can begin."
        : undefined;

  const resetCycle = () => {
    if (resetUnavailableReason) return;
    retiredCycleIds.current.add(cycleId.current!);
    cycleId.current = undefined;
    pendingStartMessageIds.current.clear();
    startRequestInFlight.current = false;
    creationIdempotencyKey.current = undefined;
    abortPayloadRef.current = undefined;
    committedMessageIds.current.clear();
    stateRef.current = initialScientificState;
    setAbortPayload(undefined);
    setActionError(undefined);
    setQuestion("");
    setStartRequested(false);
    dispatch({ resetScientificPage: true });
  };

  const recoverCycle = () => {
    if (!state.recovery || recoveryUnavailableReason) {
      return;
    }
    const checkpoint = state.checkpoint;
    if (!checkpoint || checkpoint.cycle_id !== cycleId.current) {
      setActionError("An exact server checkpoint is required before recovery.");
      return;
    }
    const ordinal = ++requestOrdinal.current;
    void send(recoveryAction, recoveryAction === "cycle.resume"
      ? {
        client_instance_id: clientInstanceId.current,
        request_ordinal: ordinal,
        cycle_id: cycleId.current,
        cursor: checkpoint,
        projection: "scientific-cycle.v1",
      }
      : {
        client_instance_id: clientInstanceId.current,
        request_ordinal: ordinal,
        cursor: checkpoint,
        max_events: 128,
      });
  };

  const abortCycle = () => {
    if (abortPayloadRef.current && !abortUnavailableReason) {
      void send("cycle.abort", abortPayloadRef.current.payload);
    }
  };

  return (
    <main className="mx-auto min-h-screen w-full max-w-5xl space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Scientific cycle (beta)</h1>
          <p className="text-sm text-muted-foreground">
            Hypothesis generation with external experiment handoff and human accountability.
          </p>
        </div>
        <Button variant="outline" onClick={() => navigate("/")}>Back to home</Button>
      </div>

      <section className="space-y-3" aria-labelledby="scientific-question-label">
        <label id="scientific-question-label" className="text-sm font-medium" htmlFor="scientific-question">
          Scientific question
        </label>
        <Textarea
          id="scientific-question"
          aria-label="Scientific question for the beta cycle"
          className="min-h-32"
          placeholder="State a question for hypothesis generation and external experiment handoff."
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <p className="text-sm text-muted-foreground">
          The creator is operator-asserted and unverified. Physical work is external; this page only
          sends protocol actions and can export a review package.
        </p>
      </section>

      <ScientificCycleView
        state={state}
        responses={responses}
        errors={errors}
        actionError={actionError}
        startUnavailableReason={
          cycleId.current || startRequested
            ? "Reset the current cycle before starting another one."
            : !supportsScientificAction(capabilities, "cycle.start")
              ? "The server did not advertise cycle.start."
              : undefined
        }
        resetUnavailableReason={resetUnavailableReason}
        recoveryUnavailableReason={recoveryUnavailableReason}
        abortUnavailableReason={abortUnavailableReason}
        exportUnavailableReason={exportUnavailableReason}
        onStart={startCycle}
        onReset={resetCycle}
        onRecover={recoverCycle}
        onAbort={abortCycle}
        onExport={() => {
          if (!exportUnavailableReason) {
            void send("export.create", {
              expected_revision: state.revision,
              format: "scientific-export.v1",
              artifact_ids: [],
              report_body_id: null,
              redaction_profile_id: null,
              external_reference_ids: [],
            });
          }
        }}
        workflowActions={WORKFLOW_ACTIONS.filter((name) => supportsScientificAction(capabilities, name))}
        workflowUnavailableReason={
          !cycleId.current
            ? "Waiting for a server-owned cycle ID."
            : state.integrity_latched || state.recovery
              ? "Replay or resume authoritative state before submitting a workflow action."
              : terminalCycle
                ? "The server reported this cycle as terminal."
                : undefined
        }
        onWorkflowAction={(name, payload) => {
          void send(name, {
            ...payload,
            ...(name === "export.create" && payload.expected_revision === undefined
              ? {
                  expected_revision: state.revision,
                  format: "scientific-export.v1",
                  artifact_ids: [],
                  report_body_id: null,
                  redaction_profile_id: null,
                  external_reference_ids: [],
                }
              : {}),
          } as ScientificActionPayloadMap[typeof name]);
        }}
      />
    </main>
  );
}

function createHello(clientInstanceId: string): ScientificEnvelope {
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

function protocolId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID().replaceAll("-", "")}`;
}

function exportIdFromEvent(event: ScientificEvent): string | undefined {
  const exportId = typeof event.payload === "object" &&
    event.payload !== null &&
    !Array.isArray(event.payload)
    ? (event.payload as Record<string, unknown>).export_id
    : undefined;
  return typeof exportId === "string" ? exportId : undefined;
}

function messageFrom(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("transformCallback")
    ? "Desktop sidecar bridge is unavailable in browser preview."
    : message;
}
interface RetainedAbortMetadata {
  payload: CycleAbortPayload;
  cycleId: string;
  revision: number;
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
