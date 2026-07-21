import {
  AI_SCIENTIST_PROTOCOL,
  type Accountability,
  SCIENTIFIC_EVENT_NAMES,
  type ScientificCursor,
  type ScientificEvent,
  type ValidationDimensions,
} from "./types";

export interface ScientificDiagnostic {
  kind:
    | "cross_cycle"
    | "duplicate"
    | "gap"
    | "sequence_collision"
    | "stale_revision"
    | "stale_sequence"
    | "unsupported_event"
    | "invalid_protocol";
  message_id: string;
  detail: string;
}

export type ScientificRecoveryRequest =
  | { kind: "replay"; after_sequence: number }
  | { kind: "snapshot"; at_revision: number };

export interface ScientificState {
  session_id?: string;
  sequence: number;
  revision: number;
  message_ids: ReadonlySet<string>;
  events: readonly ScientificEvent[];
  unsupported_events: readonly ScientificEvent[];
  pending_events: ReadonlyMap<string, ScientificEvent>;
  diagnostics: readonly ScientificDiagnostic[];
  recovery?: ScientificRecoveryRequest;
  accountability: readonly Accountability[];
  validation: readonly ValidationDimensions[];
  confidence?: number;
  v_level?: string;
  stage?: string;
  outcome?: string;
  automation_mode?: string;
  current_gate?: string;
  disposition?: string;
  current_refs: Readonly<Record<string, unknown>>;
  export_allowed: boolean;
  integrity_latched: boolean;
  checkpoint?: ScientificCursor;
  state_hash?: string;
}

export const initialScientificState: ScientificState = {
  sequence: 0,
  revision: 0,
  message_ids: new Set<string>(),
  events: [],
  unsupported_events: [],
  diagnostics: [],
  pending_events: new Map<string, ScientificEvent>(),
  accountability: [],
  validation: [],
  current_refs: {},
  export_allowed: false,
  integrity_latched: false,
};

// Accepted-command responses stream alongside events and carry the
// server-derived current gate status in their `result`; they are projected,
// never used to infer lifecycle transitions.
const supportedEvents = new Set<string>([
  ...SCIENTIFIC_EVENT_NAMES,
  "command.accepted.response",
]);

export function scientificReducer(
  state: ScientificState,
  event: ScientificEvent,
): ScientificState {
  if (state.message_ids.has(event.message_id)) {
    return diagnose(state, {
      kind: "duplicate",
      message_id: event.message_id,
      detail: "Server message was already processed.",
    });
  }

  if (state.pending_events.has(event.message_id)) {
    return diagnose(state, {
      kind: "duplicate",
      message_id: event.message_id,
      detail: "Server message is already pending contiguous replay.",
    });
  }

  if (event.protocol !== AI_SCIENTIST_PROTOCOL) {
    return diagnose(state, {
      kind: "invalid_protocol",
      message_id: event.message_id,
      detail: "Event protocol is not negotiated by this client.",
    });
  }

  if (!state.session_id) {
    if (event.type !== "cycle.started" || event.sequence !== 1 || event.revision < 1) {
      return diagnose(state, {
        kind: "cross_cycle",
        message_id: event.message_id,
        detail: "No accepted cycle start owns this event; lifecycle state was not inferred.",
      });
    }
  } else if (event.session_id !== state.session_id) {
    return diagnose(state, {
      kind: "cross_cycle",
      message_id: event.message_id,
      detail: "Event belongs to a different cycle and was quarantined.",
    });
  }

  const cycleScopedState = state.session_id
    ? state
    : { ...state, session_id: event.session_id };

  if (event.sequence <= cycleScopedState.sequence) {
    return diagnose(cycleScopedState, {
      kind: "stale_sequence",
      message_id: event.message_id,
      detail: "Server sequence was already committed; lifecycle state was not inferred.",
    });
  }

  if (event.sequence !== cycleScopedState.sequence + 1) {
    const collidingEvent = [...cycleScopedState.pending_events.values()].find(
      (pending) => pending.sequence === event.sequence,
    );
    if (collidingEvent) {
      return {
        ...diagnose(cycleScopedState, {
          kind: "sequence_collision",
          message_id: event.message_id,
          detail: "Server reused a pending sequence with a different message; lifecycle state was not inferred.",
        }),
        recovery: { kind: "snapshot", at_revision: cycleScopedState.revision },
        integrity_latched: true,
      };
    }

    const pending_events = new Map(cycleScopedState.pending_events);
    pending_events.set(event.message_id, event);
    return {
      ...diagnose({ ...cycleScopedState, pending_events }, {
        kind: "gap",
        message_id: event.message_id,
        detail: "Server sequence is not contiguous; lifecycle state was not inferred.",
      }),
      recovery: cycleScopedState.integrity_latched
        ? { kind: "snapshot", at_revision: cycleScopedState.revision }
        : { kind: "replay", after_sequence: cycleScopedState.sequence },
    };
  }

  if (event.revision <= cycleScopedState.revision) {
    return {
      ...diagnose(cycleScopedState, {
        kind: "stale_revision",
        message_id: event.message_id,
        detail: "Server revision did not advance; lifecycle state was not inferred.",
      }),
      recovery: { kind: "snapshot", at_revision: cycleScopedState.revision },
    };
  }

  return drainPending(acceptEvent(cycleScopedState, event));
}
export function applyAuthoritativeScientificSnapshot(
  state: ScientificState,
  events: readonly ScientificEvent[],
): ScientificState {
  const snapshot = events.reduce(scientificReducer, initialScientificState);

  if (
    !snapshot.session_id ||
    snapshot.session_id !== state.session_id ||
    snapshot.sequence < state.sequence ||
    snapshot.revision < state.revision ||
    snapshot.pending_events.size > 0 ||
    snapshot.recovery ||
    snapshot.integrity_latched
  ) {
    return state;
  }

  return { ...snapshot, integrity_latched: false };
}


function acceptEvent(state: ScientificState, event: ScientificEvent): ScientificState {
  const message_ids = new Set(state.message_ids);
  message_ids.add(event.message_id);
  const pending_events = new Map(state.pending_events);
  pending_events.delete(event.message_id);
  const next: ScientificState = {
    ...state,
    message_ids,
    pending_events,
    session_id: event.session_id,
    sequence: event.sequence,
    revision: event.revision,
    events: [...state.events, event],
  };

  if (!supportedEvents.has(event.type)) {
    return {
      ...next,
      unsupported_events: [...state.unsupported_events, event],
      diagnostics: [
        ...state.diagnostics,
        {
          kind: "unsupported_event",
          message_id: event.message_id,
          detail: `Negotiated event '${event.type}' is retained but not interpreted.`,
        },
      ],
    };
  }

  return projectServerMetadata(next, event);
}

function drainPending(state: ScientificState): ScientificState {
  let next = state;
  let snapshotRequired = false;
  while (true) {
    const pending = [...next.pending_events.values()].find(
      (event) => event.sequence === next.sequence + 1,
    );
    if (!pending) {
      return {
        ...next,
        recovery: next.integrity_latched || snapshotRequired
          ? { kind: "snapshot", at_revision: next.revision }
          : next.pending_events.size > 0
            ? { kind: "replay", after_sequence: next.sequence }
            : undefined,
      };
    }
    if (pending.revision <= next.revision) {
      const pending_events = new Map(next.pending_events);
      pending_events.delete(pending.message_id);
      snapshotRequired = true;
      next = diagnose({ ...next, pending_events }, {
        kind: "stale_revision",
        message_id: pending.message_id,
        detail: "Pending server revision did not advance and was dropped.",
      });
      continue;
    }
    next = acceptEvent(next, pending);
  }
}

function diagnose(state: ScientificState, diagnostic: ScientificDiagnostic): ScientificState {
  return { ...state, diagnostics: [...state.diagnostics, diagnostic] };
}

function projectServerMetadata(
  state: ScientificState,
  event: ScientificEvent,
): ScientificState {
  if (!isRecord(event.payload)) {
    return state;
  }

  const { payload } = event;
  const accountability = isAccountability(payload.accountability)
    ? [...state.accountability, payload.accountability]
    : state.accountability;
  const validation = isValidationDimensions(payload.validation)
    ? [...state.validation, payload.validation]
    : state.validation;
  const export_allowed = exportGateFor(event);
  const current_refs = isRecord(payload.derived_current_refs)
    ? payload.derived_current_refs
    : state.current_refs;
  const gates = isRecord(payload.gates) ? payload.gates : undefined;

  return {
    ...state,
    accountability,
    validation,
    current_refs,
    ...(typeof payload.confidence === "number" ? { confidence: payload.confidence } : {}),
    ...(typeof payload.v_level === "string" ? { v_level: payload.v_level } : {}),
    ...(typeof payload.stage === "string" ? { stage: payload.stage } : {}),
    ...(typeof payload.operation === "string" ? { stage: payload.operation } : {}),
    ...(typeof payload.outcome === "string" ? { outcome: payload.outcome } : {}),
    ...(typeof payload.automation_mode === "string" ? { automation_mode: payload.automation_mode } : {}),
    ...(typeof payload.current_gate === "string" ? { current_gate: payload.current_gate } : {}),
    ...(typeof payload.disposition === "string" ? { disposition: payload.disposition } : {}),
    ...(typeof gates?.current === "string" ? { current_gate: gates.current } : {}),
    ...(typeof payload.responsibility_statuses === "object"
      ? { disposition: JSON.stringify(payload.responsibility_statuses) }
      : {}),
    ...(export_allowed === undefined ? {} : { export_allowed }),
    ...authoritativeSnapshotFor(event),
  };
}

function exportGateFor(event: ScientificEvent): boolean | undefined {
  if (event.type === "export.created") {
    return true;
  }
  if (event.type !== "command.accepted.response" || !isRecord(event.payload)) {
    return undefined;
  }
  const result = event.payload.result;
  if (!isRecord(result) || !isRecord(result.gates)) {
    return undefined;
  }
  return typeof result.gates.export_ready === "boolean"
    ? result.gates.export_ready
    : undefined;
}

function authoritativeSnapshotFor(
  event: ScientificEvent,
): Pick<ScientificState, "checkpoint" | "state_hash"> {
  if (event.type !== "cycle.snapshot" || !isRecord(event.payload)) {
    return {};
  }
  const { checkpoint, state_hash } = event.payload;
  return isScientificCursor(checkpoint) && isDigest(state_hash)
    ? { checkpoint, state_hash }
    : {};
}

function isScientificCursor(value: unknown): value is ScientificCursor {
  return isRecord(value) &&
    typeof value.cycle_id === "string" &&
    typeof value.sequence === "number" &&
    Number.isSafeInteger(value.sequence) &&
    value.sequence >= 0 &&
    isDigest(value.event_hash);
}

function isDigest(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)
  );
}

function isAccountability(value: unknown): value is Accountability {
  return (
    isRecord(value) &&
    (value.label === "asserted" || value.label === "unverified")
  );
}

function isValidationDimensions(value: unknown): value is ValidationDimensions {
  if (!isRecord(value)) {
    return false;
  }
  const statuses = new Set(["pending", "passed", "failed", "not_applicable"]);
  return ["empirical", "methodological", "reproducibility", "ethical"].every(
    (key) => typeof value[key] === "string" && statuses.has(value[key]),
  );
}
