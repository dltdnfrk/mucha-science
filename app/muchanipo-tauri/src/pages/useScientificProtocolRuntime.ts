import { useReducer, useRef, useState } from "react";
import {
  initialScientificState,
} from "../lib/scientificReducer";
import {
  createAdvertisedScientificAction,
  sendScientificAction,
  supportsScientificAction,
} from "../lib/tauri";
import type {
  ScientificCapabilities,
  ScientificEnvelope,
} from "../lib/tauri";
import type {
  ScientificActionName,
  ScientificActionPayloadMap,
} from "../lib/types";
import {
  pageScientificReducer,
  protocolId,
  scientificErrorMessage,
} from "./scientificPageProtocol";
import type { RetainedAbortMetadata } from "./scientificPageProtocol";
import { useScientificSidecarListeners } from "./useScientificSidecarListeners";

export function useScientificProtocolRuntime() {
  const [state, dispatch] = useReducer(pageScientificReducer, initialScientificState);
  const [capabilities, setCapabilities] = useState<ScientificCapabilities>();
  const [responses, setResponses] = useState<ScientificEnvelope[]>([]);
  const [errors, setErrors] = useState<ScientificEnvelope[]>([]);
  const [actionError, setActionError] = useState<string>();
  const [abortPayload, setAbortPayload] = useState<RetainedAbortMetadata>();
  const [startRequested, setStartRequested] = useState(false);
  const creationIdempotencyKey = useRef<string>();
  const cycleId = useRef<string>();
  const pendingStartMessageIds = useRef(new Set<string>());
  const startRequestInFlight = useRef(false);
  const capabilitiesRef = useRef<ScientificCapabilities>();
  const abortPayloadRef = useRef<RetainedAbortMetadata>();
  const stateRef = useRef(initialScientificState);
  const clientInstanceId = useRef(protocolId("client"));
  const requestOrdinal = useRef(0);
  const ackOrdinal = useRef(0);
  const committedMessageIds = useRef(new Set<string>());
  const retiredCycleIds = useRef(new Set<string>());
  stateRef.current = state;

  useScientificSidecarListeners({
    abortPayloadRef,
    ackOrdinal,
    capabilitiesRef,
    clientInstanceId,
    committedMessageIds,
    creationIdempotencyKey,
    cycleId,
    dispatch,
    pendingStartMessageIds,
    requestOrdinal,
    retiredCycleIds,
    setAbortPayload,
    setActionError,
    setCapabilities,
    setErrors,
    setResponses,
    setStartRequested,
    startRequestInFlight,
    stateRef,
  });

  const send = async <TName extends ScientificActionName>(
    name: TName,
    payload: ScientificActionPayloadMap[TName],
  ) => {
    setActionError(undefined);
    if (!supportsScientificAction(capabilities, name)) {
      setActionError(`서버가 ${name} 작업을 제공하지 않았습니다.`);
      return false;
    }
    if (name !== "cycle.start" && !cycleId.current) {
      setActionError(`${name} 작업에는 서버가 발급한 사이클 ID가 필요합니다.`);
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
      setActionError(`서버가 ${name} 작업을 제공하지 않았습니다.`);
      return false;
    }
    try {
      if (name === "cycle.start") pendingStartMessageIds.current.add(action.message_id);
      await sendScientificAction(action);
      return true;
    } catch (error) {
      if (name === "cycle.start") pendingStartMessageIds.current.delete(action.message_id);
      setActionError(scientificErrorMessage(error));
      return false;
    }
  };

  return {
    abortPayload,
    abortPayloadRef,
    actionError,
    capabilities,
    clientInstanceId,
    committedMessageIds,
    creationIdempotencyKey,
    cycleId,
    dispatch,
    errors,
    pendingStartMessageIds,
    requestOrdinal,
    responses,
    retiredCycleIds,
    send,
    setAbortPayload,
    setActionError,
    setStartRequested,
    startRequested,
    startRequestInFlight,
    state,
    stateRef,
  };
}
