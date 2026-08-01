import { useEffect } from "react";
import type {
  Dispatch,
  MutableRefObject,
  SetStateAction,
} from "react";
import { scientificReducer } from "../lib/scientificReducer";
import type { ScientificState } from "../lib/scientificReducer";
import {
  acceptedCycleId,
  createAcknowledgementForScientificEvent,
  createAdvertisedScientificAction,
  listenScientificErrors,
  listenScientificEvents,
  listenScientificResponses,
  sendScientificAction,
  supportsScientificAction,
  toScientificEvent,
  welcomeCapabilities,
} from "../lib/tauri";
import type {
  ScientificCapabilities,
  ScientificEnvelope,
} from "../lib/tauri";
import {
  abortMetadataForActiveCycle,
  clearRejectedCycleStartRequest,
  createHello,
  exportIdFromEvent,
  queueSidecarStart,
  queueSidecarStop,
  scientificErrorMessage,
} from "./scientificPageProtocol";
import type {
  PageScientificAction,
  RetainedAbortMetadata,
} from "./scientificPageProtocol";

interface ScientificSidecarListenerContext {
  readonly abortPayloadRef: MutableRefObject<RetainedAbortMetadata | undefined>;
  readonly ackOrdinal: MutableRefObject<number>;
  readonly capabilitiesRef: MutableRefObject<ScientificCapabilities | undefined>;
  readonly clientInstanceId: MutableRefObject<string>;
  readonly committedMessageIds: MutableRefObject<Set<string>>;
  readonly creationIdempotencyKey: MutableRefObject<string | undefined>;
  readonly cycleId: MutableRefObject<string | undefined>;
  readonly dispatch: Dispatch<PageScientificAction>;
  readonly pendingStartMessageIds: MutableRefObject<Set<string>>;
  readonly requestOrdinal: MutableRefObject<number>;
  readonly retiredCycleIds: MutableRefObject<Set<string>>;
  readonly setAbortPayload: Dispatch<SetStateAction<RetainedAbortMetadata | undefined>>;
  readonly setActionError: Dispatch<SetStateAction<string | undefined>>;
  readonly setCapabilities: Dispatch<SetStateAction<ScientificCapabilities | undefined>>;
  readonly setErrors: Dispatch<SetStateAction<ScientificEnvelope[]>>;
  readonly setResponses: Dispatch<SetStateAction<ScientificEnvelope[]>>;
  readonly setStartRequested: Dispatch<SetStateAction<boolean>>;
  readonly startRequestInFlight: MutableRefObject<boolean>;
  readonly stateRef: MutableRefObject<ScientificState>;
}

export function useScientificSidecarListeners(
  context: ScientificSidecarListenerContext,
): void {
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
        context.cycleId.current,
        context.stateRef.current.revision,
      );
      if (metadata) {
        context.abortPayloadRef.current = metadata;
        context.setAbortPayload(metadata);
      }
    };

    const registerListeners = async () => {
      try {
        addCleanup(await listenScientificEvents((envelope) => {
          if (!active || !context.cycleId.current ||
              envelope.cycle_id !== context.cycleId.current ||
              context.retiredCycleIds.current.has(envelope.cycle_id)) return;
          const event = toScientificEvent(envelope);
          if (!event) return;
          const previousState = context.stateRef.current;
          const nextState = scientificReducer(previousState, event);
          context.stateRef.current = nextState;
          context.dispatch(event);
          const newlyCommitted = nextState.events.slice(previousState.events.length);

          for (const committedEvent of newlyCommitted) {
            if (context.committedMessageIds.current.has(committedEvent.message_id)) continue;
            context.committedMessageIds.current.add(committedEvent.message_id);
            sendAutomaticAcknowledgement(context, committedEvent, nextState, active);
            sendAutomaticExportGet(context, committedEvent, active);
          }
          if (newlyCommitted.some(({ message_id }) => message_id === event.message_id)) {
            retainAbortMetadata(envelope);
          }
        }));
        addCleanup(await listenScientificResponses((response) => {
          if (!active) return;
          context.setResponses((current) => [...current, response]);
          const advertised = welcomeCapabilities(response);
          if (advertised) {
            context.capabilitiesRef.current = advertised;
            context.setCapabilities(advertised);
          } else if (response.name === "protocol.welcome.response") {
            context.setActionError("서버 환영 응답에 유효한 기능 목록이 없습니다.");
          }
          const acceptedId = acceptedCycleId(response);
          if (
            acceptedId &&
            !context.cycleId.current &&
            response.correlation_id &&
            context.pendingStartMessageIds.current.has(response.correlation_id)
          ) {
            context.cycleId.current = acceptedId;
            context.startRequestInFlight.current = false;
            context.setStartRequested(false);
          }
          retainAbortMetadata(response);
        }));
        addCleanup(await listenScientificErrors((error) => {
          if (!active) return;
          context.setErrors((current) => [...current, error]);
          const requestState = clearRejectedCycleStartRequest({
            pendingMessageIds: context.pendingStartMessageIds.current,
            inFlight: context.startRequestInFlight.current,
            startRequested: true,
            creationIdempotencyKey: context.creationIdempotencyKey.current,
          }, error);
          if (requestState.pendingMessageIds === context.pendingStartMessageIds.current) return;
          context.pendingStartMessageIds.current = new Set(requestState.pendingMessageIds);
          context.startRequestInFlight.current = requestState.inFlight;
          context.setStartRequested(requestState.startRequested);
        }));
        if (!active) {
          cleanupListeners();
          return;
        }
        const sidecar = queueSidecarStart();
        sidecarGeneration = sidecar.generation;
        await sidecar.completion;
        if (active) await sendScientificAction(createHello(context.clientInstanceId.current));
      } catch (error) {
        cleanupListeners();
        if (active) context.setActionError(scientificErrorMessage(error));
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
}

function sendAutomaticAcknowledgement(
  context: ScientificSidecarListenerContext,
  event: ScientificState["events"][number],
  state: ScientificState,
  active: boolean,
): void {
  const { checkpoint, state_hash: stateHash } = state;
  if (
    event.type !== "cycle.snapshot" ||
    !checkpoint ||
    !stateHash ||
    checkpoint.cycle_id !== event.session_id ||
    !supportsScientificAction(context.capabilitiesRef.current, "cycle.ack")
  ) return;
  const acknowledgement = createAcknowledgementForScientificEvent(
    context.capabilitiesRef.current,
    event,
    {
      client_instance_id: context.clientInstanceId.current,
      ack_ordinal: ++context.ackOrdinal.current,
      checkpoint,
      state_hash: stateHash,
    },
  );
  if (acknowledgement) {
    void sendScientificAction(acknowledgement).catch((error: unknown) => {
      if (active) context.setActionError(scientificErrorMessage(error));
    });
  }
}

function sendAutomaticExportGet(
  context: ScientificSidecarListenerContext,
  event: ScientificState["events"][number],
  active: boolean,
): void {
  if (event.type !== "export.created") return;
  const exportId = exportIdFromEvent(event);
  if (!exportId || !supportsScientificAction(context.capabilitiesRef.current, "export.get")) return;
  const action = createAdvertisedScientificAction(
    context.capabilitiesRef.current,
    "export.get",
    {
      client_instance_id: context.clientInstanceId.current,
      request_ordinal: ++context.requestOrdinal.current,
      export_id: exportId,
      include_archive_bytes: false,
    },
    { cycleId: event.session_id },
  );
  if (action) {
    void sendScientificAction(action).catch((error: unknown) => {
      if (active) context.setActionError(scientificErrorMessage(error));
    });
  }
}
