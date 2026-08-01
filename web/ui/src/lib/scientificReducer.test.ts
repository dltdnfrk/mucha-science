import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import {
  initialScientificState,
  applyAuthoritativeScientificSnapshot,
  scientificReducer,
  type ScientificState,
} from "./scientificReducer";
import {
  abortMetadataForActiveCycle,
  clearRejectedCycleStartRequest,
} from "../pages/ScientificPage";
import {
  acceptedCycleId,
  createAcknowledgementAction,
  createAdvertisedScientificAction,
  createScientificAction,
  isScientificEnvelope,
  normalizeBackendAction,
  toScientificEvent,
  welcomeCapabilities,
  type ScientificEnvelope,
} from "./tauri";
import type { HelloPayload, ScientificEvent } from "./types";

function event(
  sequence: number,
  revision: number,
  type: string,
  payload: unknown,
  message_id = `message-${sequence}`,
): ScientificEvent {
  return {
    protocol: "ai-scientist.v1",
    message_id,
    session_id: "session-1",
    sequence,
    revision,
    type,
    payload,
  };
}

function reduce(...events: ScientificEvent[]): ScientificState {
  return events.reduce(scientificReducer, initialScientificState);
}
const clientId = "client_0123456789abcdef0123456789abcdef";
const checkpoint = {
  cycle_id: "cycle_0123456789abcdef0123456789abcdef",
  sequence: 4,
  event_hash: `sha256:${"a".repeat(64)}`,
};
const helloPayload: HelloPayload = {
  handshake_idempotency_key: "idempotency_0123456789abcdef0123456789abcdef",
  client_instance_id: clientId,
  supported_versions: ["ai-scientist.v1"],
  capabilities: [],
  projection: "scientific-cycle.v1",
  cursors: [],
};

describe("scientificReducer", () => {
  it("reads the generated protocol corpus as exact manifest-addressed bytes", () => {
    const root = new URL("../../../../config/protocol/ai-scientist.v1/", import.meta.url);
    const manifest = JSON.parse(readFileSync(new URL("manifest.json", root), "utf8")) as {
      unicode_version: string;
      files: { path: string; length: number; sha256: string }[];
    };

    expect(manifest.unicode_version).toBe("15.1.0");
    expect(manifest.files.map(({ path }) => path).sort()).toEqual([
      "bytes/corpus.jsonl", "invalid/corpus.jsonl", "legacy/corpus.jsonl",
      "replay/corpus.jsonl", "valid/corpus.jsonl",
    ]);
    for (const entry of manifest.files) {
      const bytes = readFileSync(new URL(entry.path, root));
      expect(bytes.length).toBe(entry.length);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(entry.sha256);
      expect(bytes.at(-1)).toBe(0x0a);
      expect(bytes.toString("utf8").split("\n").filter(Boolean).every((record) => {
        try {
          JSON.parse(record);
          return true;
        } catch {
          return false;
        }
      })).toBe(true);
    }
  });
  it("deduplicates server message IDs without advancing state", () => {
    const started = event(1, 1, "cycle.started", {
      topic: "test",
      accountability: { label: "asserted" },
    });
    const state = scientificReducer(reduce(started), started);

    expect(state.sequence).toBe(1);
    expect(state.revision).toBe(1);
    expect(state.events).toHaveLength(1);
    expect(state.diagnostics.at(-1)?.kind).toBe("duplicate");
  });

  it("quarantines a foreign first event without letting it claim cycle ownership", () => {
    const state = reduce(event(2, 2, "cycle.continued", {}));

    expect(state.session_id).toBeUndefined();
    expect(state.sequence).toBe(0);
    expect(state.events).toHaveLength(0);
    expect(state.pending_events).toHaveLength(0);
    expect(state.recovery).toBeUndefined();
    expect(state.diagnostics.at(-1)?.kind).toBe("cross_cycle");
  });
  it("buffers in-cycle sequence gaps and drains them once replay converges", () => {
    const third = event(3, 3, "cycle.completed", {}, "message-3");
    const state = reduce(
      event(1, 1, "cycle.started", {}, "message-1"),
      third,
      event(2, 2, "cycle.continued", {}, "message-2"),
    );

    expect(state.events.map((received) => received.sequence)).toEqual([1, 2, 3]);
    expect(state.message_ids.has("message-3")).toBe(true);
    expect(state.pending_events).toHaveLength(0);
    expect(state.recovery).toBeUndefined();
  });
  it("keeps replay recovery active until every pending sequence is applied", () => {
    const state = reduce(
      event(1, 1, "cycle.started", {}, "message-1"),
      event(3, 3, "cycle.completed", {}, "message-3"),
    );

    expect(state.sequence).toBe(1);
    expect(state.pending_events.has("message-3")).toBe(true);
    expect(state.recovery).toEqual({ kind: "replay", after_sequence: 1 });
  });
  it("requests a snapshot after a stale revision without advancing state", () => {
    const state = reduce(
      event(1, 1, "cycle.started", {}),
      event(2, 1, "cycle.continued", {}),
    );

    expect(state.sequence).toBe(1);
    expect(state.recovery).toEqual({ kind: "snapshot", at_revision: 1 });
    expect(state.diagnostics.at(-1)?.kind).toBe("stale_revision");
  });
  it("retains unknown negotiated events without projecting their raw lifecycle metadata", () => {
    const state = reduce(
      event(1, 1, "cycle.started", {}),
      event(2, 2, "future.server.event", {
        value: "kept",
        stage: "A",
        outcome: "forged",
        export_allowed: true,
      }),
    );

    expect(state.sequence).toBe(2);
    expect(state.events).toHaveLength(2);
    expect(state.unsupported_events).toHaveLength(1);
    expect(state.unsupported_events[0]?.type).toBe("future.server.event");
    expect(state.stage).toBeUndefined();
    expect(state.outcome).toBeUndefined();
    expect(state.export_allowed).toBe(false);
    expect(state.diagnostics.at(-1)?.kind).toBe("unsupported_event");
  });
  it("quarantines cross-cycle events before they can become pending", () => {
    const started = event(1, 1, "cycle.started", {}, "message-1");
    const foreign = {
      ...event(3, 3, "cycle.completed", {}, "message-foreign"),
      session_id: "session-2",
    };
    const state = reduce(started, foreign);

    expect(state.session_id).toBe("session-1");
    expect(state.pending_events).toHaveLength(0);
    expect(state.events).toHaveLength(1);
    expect(state.diagnostics.at(-1)?.kind).toBe("cross_cycle");
  });
  it("drops stale sequences instead of retaining immortal pending events", () => {
    const state = reduce(
      event(1, 1, "cycle.started", {}, "message-1"),
      event(1, 2, "cycle.continued", {}, "message-stale"),
    );

    expect(state.events).toHaveLength(1);
    expect(state.pending_events).toHaveLength(0);
    expect(state.recovery).toBeUndefined();
    expect(state.diagnostics.at(-1)?.kind).toBe("stale_sequence");
  });
  it("keeps snapshot recovery latched after equivocation converges until an authoritative snapshot validates", () => {
    const first = event(1, 1, "cycle.started", {}, "message-1");
    const thirdA = event(3, 3, "cycle.completed", {}, "message-3a");
    const thirdB = event(3, 4, "cycle.aborted", {}, "message-3b");
    const second = event(2, 2, "cycle.continued", {}, "message-2");
    const converged = reduce(first, thirdA, thirdB, second);
    const ordinaryEvent = scientificReducer(
      converged,
      event(4, 4, "cycle.continued", {}, "message-4"),
    );

    expect(converged.events.map((received) => received.sequence)).toEqual([1, 2, 3]);
    expect(converged.pending_events).toHaveLength(0);
    expect(converged.integrity_latched).toBe(true);
    expect(converged.recovery).toEqual({ kind: "snapshot", at_revision: 3 });
    expect(ordinaryEvent.recovery).toEqual({ kind: "snapshot", at_revision: 4 });

    expect(
      applyAuthoritativeScientificSnapshot(ordinaryEvent, [first, second, thirdA]),
    ).toBe(ordinaryEvent);

    const recovered = applyAuthoritativeScientificSnapshot(ordinaryEvent, [
      first,
      second,
      thirdA,
      event(4, 4, "cycle.continued", {}, "message-4-authoritative"),
    ]);

    expect(recovered.integrity_latched).toBe(false);
    expect(recovered.recovery).toBeUndefined();
    expect(recovered.events.map((received) => received.sequence)).toEqual([1, 2, 3, 4]);
  });
  it("requests a snapshot when dropping a stale pending frame leaves the sequence incomplete", () => {
    const state = reduce(
      event(1, 1, "cycle.started", {}, "message-1"),
      event(3, 2, "cycle.completed", {}, "message-3"),
      event(2, 2, "cycle.continued", {}, "message-2"),
    );

    expect(state.sequence).toBe(2);
    expect(state.revision).toBe(2);
    expect(state.pending_events).toHaveLength(0);
    expect(state.recovery).toEqual({ kind: "snapshot", at_revision: 2 });
    expect(state.diagnostics.at(-1)).toMatchObject({
      kind: "stale_revision",
      message_id: "message-3",
    });
  });
  it("persists unverified accountability labels exactly as server asserted", () => {
    const state = reduce(
      event(1, 1, "cycle.started", {}),
      event(2, 2, "cycle.continued", {
        continuation: "review evidence",
        accountability: { label: "unverified", assertion: "server supplied" },
      }),
    );

    expect(state.accountability).toEqual([
      { label: "unverified", assertion: "server supplied" },
    ]);
  });

  it("keeps confidence and V-level independent while retaining validation dimensions", () => {
    const validation = {
      empirical: "passed",
      methodological: "pending",
      reproducibility: "failed",
      ethical: "not_applicable",
    } as const;
    const state = reduce(
      event(1, 1, "cycle.started", {}),
      event(2, 2, "result.recorded", {
        source: "repository",
        result: { finding: true },
        validation,
        accountability: { label: "asserted" },
        confidence: 0.72,
        v_level: "V3",
      }),
    );

    expect(state.confidence).toBe(0.72);
    expect(state.v_level).toBe("V3");
    expect(state.validation).toEqual([validation]);
  });
  it("retains projected stage and outcome when later events omit them", () => {
    const state = reduce(
      event(1, 1, "cycle.started", {}),
      event(2, 2, "cycle.continued", {
        stage: "validation",
        outcome: "pending",
      }),
      event(3, 3, "export.created", {}),
    );

    expect(state.stage).toBe("validation");
    expect(state.outcome).toBe("pending");
  });
  it("retains actual server event names without inferring support or export gates", () => {
    const state = reduce(event(1, 1, "cycle.started", {
      normalized_question: "Question?",
      export_allowed: true,
    }));

    expect(state.events[0]?.type).toBe("cycle.started");
    expect(state.export_allowed).toBe(false);
    expect(state.events[0]?.payload).toEqual({
      normalized_question: "Question?",
      export_allowed: true,
    });
  });

  it("builds exact hello and distinguishes read from mutation idempotency", () => {
    const hello = createScientificAction("protocol.hello", helloPayload);
    const read = createScientificAction("report.render", {
      client_instance_id: clientId,
      request_ordinal: 1,
      cycle_id: checkpoint.cycle_id,
      at_revision: 4,
      format: "canonical_json",
      include_status_overlay: false,
    });
    const secondRead = createScientificAction("export.get", {
      client_instance_id: clientId,
      request_ordinal: 2,
      export_id: "export_0123456789abcdef0123456789abcdef",
      include_archive_bytes: false,
    });
    const mutation = createScientificAction("export.create", {
      expected_revision: 4,
      format: "scientific-export.v1",
      artifact_ids: [],
      report_body_id: null,
      redaction_profile_id: null,
      external_reference_ids: [],
    });

    expect(hello).toMatchObject({
      kind: "action",
      cycle_id: null,
      correlation_id: hello.message_id,
      causation_id: null,
      sequence: 0,
      revision: 0,
      idempotency_key: helloPayload.handshake_idempotency_key,
      payload: helloPayload,
    });
    expect(read.idempotency_key).toBeNull();
    expect(secondRead).toMatchObject({
      idempotency_key: null,
      payload: { request_ordinal: 2, include_archive_bytes: false },
    });
    expect(mutation.idempotency_key).toMatch(/^idempotency_/);
    expect(hello.timestamp).toMatch(/\.\d{6}Z$/);
  });
  it("preserves the exact cycle.start payload and creation idempotency key", () => {
    const payload = {
      creation_idempotency_key: "creation_123",
      expected_revision: 0,
      raw_question: "Question?",
      contract_version: "ai-scientist.v1",
      boundary: { kind: "cognitive_only", description: "Cognitive work only." },
      creator: { display_name: "operator" },
    } as const;
    const action = createScientificAction("cycle.start", payload, {
      idempotencyKey: payload.creation_idempotency_key,
    });

    expect(action.idempotency_key).toBe(payload.creation_idempotency_key);
    expect(action.payload).toEqual(payload);
    expect(action.cycle_id).toBeNull();
  });

  it("takes a cycle ID only from an accepted server response", () => {
    const accepted: ScientificEnvelope = {
      ...createScientificAction("protocol.hello", helloPayload),
      kind: "response",
      name: "command.accepted.response",
      cycle_id: "cycle_0123456789abcdef0123456789abcdef",
    };
    const rejected = { ...accepted, name: "command.rejected.error" };

    expect(acceptedCycleId(accepted)).toBe("cycle_0123456789abcdef0123456789abcdef");
    expect(acceptedCycleId(rejected)).toBeUndefined();
  });
  it("clears only a correlated rejected cycle start while retaining its retry key", () => {
    const pendingMessageIds = new Set(["start-message"]);
    const requestState = {
      pendingMessageIds,
      inFlight: true,
      startRequested: true,
      creationIdempotencyKey: "creation_123",
    };
    const rejection: ScientificEnvelope = {
      ...createScientificAction("protocol.hello", helloPayload),
      kind: "error",
      name: "command.rejected.error",
      correlation_id: "start-message",
    };

    expect(clearRejectedCycleStartRequest(requestState, rejection)).toEqual({
      pendingMessageIds: new Set(),
      inFlight: false,
      startRequested: false,
      creationIdempotencyKey: "creation_123",
    });
    expect(clearRejectedCycleStartRequest(requestState, {
      ...rejection,
      correlation_id: "other-message",
    })).toBe(requestState);
  });

  it("derives export permission only from server-computed accepted-command gates", () => {
    const genericPayload = reduce(
      event(1, 1, "cycle.started", {}),
      event(2, 2, "cycle.continued", { export_allowed: true }),
    );
    const inferred = reduce(
      event(1, 1, "cycle.started", {}),
      event(2, 2, "validation.assessment.transitioned", {
        export_allowed: true,
      }),
    );
    const opened = reduce(
      event(1, 1, "cycle.started", {}),
      event(2, 2, "command.accepted.response", {
        request_message_id: "message-2",
        result: { gates: { export_ready: true } },
      }),
    );
    const closed = scientificReducer(
      opened,
      event(3, 3, "command.accepted.response", {
        request_message_id: "message-3",
        result: { gates: { export_ready: false } },
      }),
    );

    expect(genericPayload.export_allowed).toBe(false);
    expect(inferred.export_allowed).toBe(false);
    expect(opened.export_allowed).toBe(true);
    expect(closed.export_allowed).toBe(false);
  });
  it("builds only advertised recovery actions with the server's frozen empty payload", () => {
    const welcome: ScientificEnvelope = {
      ...createScientificAction("protocol.hello", helloPayload),
      kind: "response",
      name: "protocol.welcome.response",
      payload: { capabilities: ["cycle.replay"] },
    };

    const capabilities = welcomeCapabilities(welcome);
    expect(capabilities).toEqual(["cycle.replay"]);
    expect(createAdvertisedScientificAction(capabilities, "export.create", {
      expected_revision: 1,
      format: "scientific-export.v1",
      artifact_ids: [],
      report_body_id: null,
      redaction_profile_id: null,
      external_reference_ids: [],
    })).toBeUndefined();
    expect(createAdvertisedScientificAction(capabilities, "cycle.replay", {
      client_instance_id: clientId,
      request_ordinal: 1,
      cursor: checkpoint,
      max_events: 128,
    }, {
      cycleId: checkpoint.cycle_id,
    })).toMatchObject({
      name: "cycle.replay",
      payload: {
        client_instance_id: clientId,
        request_ordinal: 1,
        cursor: checkpoint,
        max_events: 128,
      },
      cycle_id: checkpoint.cycle_id,
      sequence: 0,
      revision: 0,
    });
  });

  it("acknowledges only a supplied authoritative snapshot checkpoint", () => {
    const eventEnvelope: ScientificEnvelope = {
      ...createScientificAction("protocol.hello", helloPayload),
      kind: "event",
      name: "cycle.continued",
      cycle_id: checkpoint.cycle_id,
      sequence: 4,
      revision: 3,
    };
    const acknowledgement = {
      client_instance_id: clientId,
      ack_ordinal: 1,
      checkpoint,
      state_hash: `sha256:${"b".repeat(64)}`,
    };

    expect(createAcknowledgementAction([], eventEnvelope, acknowledgement)).toBeUndefined();
    expect(createAcknowledgementAction(["cycle.ack"], {
      ...eventEnvelope,
      cycle_id: null,
    }, acknowledgement)).toBeUndefined();
    expect(createAcknowledgementAction(["cycle.ack"], eventEnvelope, acknowledgement)).toMatchObject({
      name: "cycle.ack",
      idempotency_key: null,
      payload: acknowledgement,
    });
  });
  it("retains an acknowledgement checkpoint only from an exact snapshot", () => {
    const state = reduce(
      event(1, 1, "cycle.started", {}),
      event(2, 2, "cycle.snapshot", {
        checkpoint,
        state_hash: `sha256:${"c".repeat(64)}`,
      }),
    );
    const stale = scientificReducer(state, event(3, 3, "cycle.snapshot", {
      checkpoint: { ...checkpoint, sequence: 3, event_hash: "forged" },
      state_hash: "forged",
    }));

    expect(state.checkpoint).toEqual(checkpoint);
    expect(stale.checkpoint).toEqual(checkpoint);
    expect(stale.state_hash).toBe(state.state_hash);
  });
  it.each([
    { sequence: Number.NaN },
    { sequence: 1.5 },
    { sequence: -1 },
    { revision: Number.NaN },
    { revision: 1.5 },
    { revision: -1 },
    { message_id: "" },
    { message_id: "message-not-a-protocol-id" },
    { cycle_id: "cycle-not-a-protocol-id" },
    { correlation_id: 42 },
    { causation_id: [] },
    { payload: [] },
    { extensions: [] },
    { timestamp: "2026-07-19T00:00:00.000Z" },
  ])("rejects malformed scientific envelopes: %o", (override) => {
    const envelope = {
      ...createScientificAction("protocol.hello", helloPayload),
      kind: "event",
      name: "cycle.started",
      cycle_id: "cycle_0123456789abcdef0123456789abcdef",
      ...override,
    };

    expect(isScientificEnvelope(envelope)).toBe(false);
    expect(toScientificEvent(envelope)).toBeUndefined();
  });

  it("preserves supplied abort fields without fake defaults", () => {
    const payload = {
      expected_revision: 7,
      actor: { display_name: "server-reported operator" },
      reason: "The operator ended the review.",
      final_observation: "External results remain unverified.",
    };
    const action = createAdvertisedScientificAction(
      ["cycle.abort"],
      "cycle.abort",
      payload,
      { cycleId: "cycle_server_owned" },
    );

    expect(action?.payload).toEqual(payload);
    expect(action?.cycle_id).toBe("cycle_server_owned");
    expect(action?.revision).toBe(0);
    expect(Object.keys(action?.payload ?? {})).toEqual([
      "expected_revision",
      "actor",
      "reason",
      "final_observation",
    ]);
  });
  it("rejects missing or conflicting legacy action discriminators", () => {
    expect(() => normalizeBackendAction({})).toThrow("unambiguous action discriminator");
    expect(() => normalizeBackendAction({
      action: "abort",
      type: "interview_answer",
    })).toThrow("unambiguous action discriminator");
    expect(() => normalizeBackendAction({
      type: "interview_answer",
      question_id: "question-1",
    })).toThrow("question ID and a non-empty answer");
  });
  it("normalizes only valid unambiguous legacy actions", () => {
    expect(normalizeBackendAction({
      type: "interview_answer",
      question_id: "question-1",
      selected: "approved",
    })).toMatchObject({
      action: "interview_answer",
      q_id: "question-1",
      answer: "approved",
    });
  });
  it("rejects foreign and stale abort metadata", () => {
    const cycleId = "cycle_0123456789abcdef0123456789abcdef";
    const envelope: ScientificEnvelope = {
      ...createScientificAction("protocol.hello", helloPayload),
      kind: "response",
      cycle_id: cycleId,
      revision: 4,
      payload: {
        expected_revision: 4,
        actor: { display_name: "operator" },
        reason: "Review ended.",
        final_observation: "No physical work occurred.",
      },
    };

    expect(abortMetadataForActiveCycle(envelope, "cycle_other", 4)).toBeUndefined();
    expect(abortMetadataForActiveCycle(envelope, cycleId, 3)).toBeUndefined();
    expect(abortMetadataForActiveCycle(envelope, cycleId, 4)?.payload).toEqual(
      envelope.payload,
    );
  });
});
