#!/usr/bin/env node
// Packaged-sidecar end-to-end drive of the ai-scientist.v1 wire lifecycle.
//
// This script exercises the exact packaged artifact (no PATH Python, no source
// tree) through: hello negotiation, cycle start, L/H/P stages, question/safety/
// execution-accountability dispositions, local X=not_run, server-derived export
// gating, export create/get, interim report projection with status overlay,
// kill/restart/resume/ack recovery, emergency read-only denial, and abort on a
// second cycle. External-result import, adjudication, and completion remain
// covered by the backend integration suites because result staging is a
// local-only (non-wire) operation by contract.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import process from "node:process";

const HOST_TARGETS = {
  "darwin:arm64": "aarch64-apple-darwin",
  "darwin:x64": "x86_64-apple-darwin",
  "linux:x64": "x86_64-unknown-linux-gnu",
  "win32:x64": "x86_64-pc-windows-msvc",
};
const target = HOST_TARGETS[`${process.platform}:${process.arch}`];
if (!target) {
  throw new Error(`no native sidecar target for ${process.platform}/${process.arch}`);
}
const sidecar = process.env.MUCHANIPO_E2E_SIDECAR
  ?? join("src-tauri", "binaries", `muchanipo-service-${target}${process.platform === "win32" ? ".exe" : ""}`);
if (!existsSync(sidecar)) {
  throw new Error(`packaged sidecar is missing: ${sidecar}; run \`npm run sidecar:build\` first`);
}

const TIMESTAMP = "2026-07-20T00:00:00.000000Z";
const LATER = "2026-07-20T00:00:01.000000Z";
const CLIENT = "client_e2e00000000000000000000000000000";
let messageCounter = 0;
let requestOrdinal = 0;
let ackOrdinal = 0;

function messageId() {
  messageCounter += 1;
  return `message_${String(messageCounter).padStart(32, "0")}`;
}

function assertEqual(actual, expected, label) {
  const left = JSON.stringify(actual);
  const right = JSON.stringify(expected);
  if (left !== right) {
    throw new Error(`${label}: expected ${right}, got ${left}`);
  }
}

function assertTrue(value, label) {
  if (!value) {
    throw new Error(label);
  }
}

function actor() {
  return {
    actor_kind: "human", display_name: "Operator", organization: null, role: "reviewer",
    assertion_source: "operator_entry", verification_status: "operator_asserted_unverified",
    authority_scope: { kind: "none", scope: null }, external_reference: null,
  };
}

function stageFields() {
  return {
    accountable_party: actor(),
    performers: [{ kind: "human", name: "Operator", version: null, external_reference: null }],
    execution_kind: "cognitive", automation_mode: "manual",
    boundary: { kind: "cognitive_only", description: "cognitive only" },
    started_at: TIMESTAMP, completed_at: LATER,
  };
}

function envelope(name, { cycleId = null, payload, read = false }) {
  const id = messageId();
  return {
    protocol: "muchanipo", protocol_version: "ai-scientist.v1", kind: "action", name,
    message_id: id, cycle_id: cycleId, correlation_id: id, causation_id: null,
    sequence: 0, revision: 0,
    idempotency_key: read ? null : `request-${id}`,
    timestamp: TIMESTAMP, payload, extensions: {},
  };
}

function readPayload(extra) {
  requestOrdinal += 1;
  return { client_instance_id: CLIENT, request_ordinal: requestOrdinal, ...extra };
}

class Sidecar {
  constructor(home) {
    this.child = spawn(sidecar, [
      "serve", "--topic", "scientific-cycle", "--scientific-mode", "--scientific-home", home,
    ], { stdio: ["pipe", "pipe", "inherit"] });
    this.buffer = "";
    this.lines = [];
    this.waiters = [];
    this.child.stdout.setEncoding("utf-8");
    this.child.stdout.on("data", (chunk) => {
      this.buffer += chunk;
      let index;
      while ((index = this.buffer.indexOf("\n")) >= 0) {
        const line = this.buffer.slice(0, index);
        this.buffer = this.buffer.slice(index + 1);
        const waiter = this.waiters.shift();
        if (waiter) {
          waiter(line);
        } else {
          this.lines.push(line);
        }
      }
    });
  }

  nextLine() {
    if (this.lines.length > 0) {
      return Promise.resolve(this.lines.shift());
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("timed out waiting for sidecar output")), 15000);
      this.waiters.push((line) => {
        clearTimeout(timer);
        resolve(line);
      });
    });
  }

  async request(action) {
    this.child.stdin.write(JSON.stringify(action) + "\n");
    const response = JSON.parse(await this.nextLine());
    assertEqual(response.correlation_id, action.message_id, `${action.name} correlation`);
    return response;
  }

  async hello() {
    const action = envelope("protocol.hello", {
      payload: {
        handshake_idempotency_key: "", client_instance_id: CLIENT,
        supported_versions: ["ai-scientist.v1"], capabilities: [], projection: "full", cursors: [],
      },
    });
    action.payload.handshake_idempotency_key = action.idempotency_key;
    const welcome = await this.request(action);
    assertEqual(welcome.name, "protocol.welcome.response", "hello handshake");
    assertEqual(welcome.payload.selected_version, "ai-scientist.v1", "negotiated version");
    return welcome;
  }

  async accepted(action, label) {
    const response = await this.request(action);
    assertEqual(response.name, "command.accepted.response", `${label} acceptance (${JSON.stringify(response.payload)})`);
    return response;
  }

  async rejected(action, code, label) {
    const response = await this.request(action);
    assertEqual(response.name, "command.rejected.error", `${label} rejection kind`);
    assertEqual(response.payload.stable_code, code, `${label} stable code`);
    return response;
  }

  kill() {
    this.child.kill("SIGKILL");
  }

  async shutdown() {
    this.child.stdin.end();
    await new Promise((resolve) => this.child.once("exit", resolve));
  }
}

function makeHome(flags) {
  const home = mkdtempSync(join(tmpdir(), "muchanipo-e2e-"));
  writeFileSync(join(home, "config.json"), JSON.stringify({
    ai_scientist: {
      enabled: true, protocol_capability: true, allow_new_cycles: true,
      allow_external_result_import: false, emergency_read_only: false,
      ...flags,
    },
  }));
  return home;
}

async function resumeSnapshot(server, cycleId, { fromSequence = 0, eventHash } = {}) {
  const genesis = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
  const response = await server.request(envelope("cycle.resume", {
    cycleId,
    read: true,
    payload: readPayload({
      cycle_id: cycleId,
      cursor: { cycle_id: cycleId, sequence: fromSequence, event_hash: eventHash ?? genesis },
      projection: "full",
    }),
  }));
  assertEqual(response.name, "cycle.resume.response", "resume response");
  return response.payload;
}

async function main() {
  const home = makeHome({});
  let server = new Sidecar(home);
  const welcome = await server.hello();
  for (const capability of ["cycle.start", "cycle.continue", "export.create", "report.render", "cycle.ack"]) {
    assertTrue(welcome.payload.capabilities.includes(capability), `welcome advertises ${capability}`);
  }
  assertTrue(!welcome.payload.capabilities.includes("result.submit"), "import stays unadvertised when unconfigured");

  // Start a cycle.
  const startAction = envelope("cycle.start", {
    payload: {
      creation_idempotency_key: "", expected_revision: 0, raw_question: "Question?",
      contract_version: "ai-scientist.v1",
      boundary: { kind: "cognitive_only", description: "cognitive only" }, creator: actor(),
    },
  });
  startAction.payload.creation_idempotency_key = startAction.idempotency_key;
  const started = await server.accepted(startAction, "cycle.start");
  const cycleId = started.payload.result.cycle_id;
  let revision = started.revision;
  assertEqual(revision, 1, "start revision");

  const continueAction = (operation, stageInput) => envelope("cycle.continue", {
    cycleId,
    payload: { expected_revision: revision, operation, stage_input: { kind: operation, ...stageInput } },
  });

  // Landscape: export must not be ready yet.
  const landscape = await server.accepted(continueAction("landscape.complete", {
    invalidate_current_proposal: false,
    ...stageFields(),
    landscape_artifacts: [{
      title: "Landscape", summary: "Committed sources", source_artifact_ids: [],
      limitations: ["Unverified sources"],
    }],
  }), "landscape.complete");
  revision = landscape.revision;
  assertEqual(landscape.payload.result.gates, { export_ready: false }, "landscape export gate");

  // Learn requirement scope from the server; clients never derive it.
  let snapshot = await resumeSnapshot(server, cycleId);
  const requirementFor = (state, responsibility) => {
    const requirementId = state.requirements[responsibility];
    return { requirementId, scopeHash: state.records[requirementId].content.scope_hash };
  };
  const disposition = (responsibility, details, state) => {
    const { requirementId, scopeHash } = requirementFor(state, responsibility);
    return envelope(`responsibility.${responsibility}.disposition`, {
      cycleId,
      payload: {
        expected_revision: revision, requirement_id: requirementId, actor: actor(),
        asserted_at: TIMESTAMP, status: "satisfied", rationale: "Reviewed.",
        scope_hash: scopeHash, details,
      },
    });
  };

  const question = await server.accepted(disposition("question_selection", {
    selected_normalized_question: snapshot.snapshot.state.question, rejected_alternatives: [],
  }, snapshot.snapshot.state), "question disposition");
  revision = question.revision;

  const hypothesis = await server.accepted(continueAction("hypothesis.complete", {
    invalidate_current_proposal: false,
    ...stageFields(),
    claims: [{
      artifact_type: "claim", statement: "Claim", falsification_criteria: "Measure outcome",
      evidence_artifact_ids: [], parent_claim_ids: [], rank: 1,
      limitations: [
        "Unvalidated candidate; rank is prioritization, not support.",
        "Evidence text is explicitly unlinked to committed artifacts.",
      ],
    }],
  }), "hypothesis.complete");
  revision = hypothesis.revision;

  snapshot = await resumeSnapshot(server, cycleId);
  const claims = snapshot.snapshot.state.current.claims;
  const proposal = await server.accepted(continueAction("proposal.complete", {
    ...stageFields(),
    proposal: {
      claim_ids: claims,
      risks: ["External execution risk"],
      acceptance_criteria: ["Externally reviewed result"],
      handoff_boundary: { kind: "export_only", description: "external handoff only" },
    },
  }), "proposal.complete");
  revision = proposal.revision;
  assertEqual(proposal.payload.result.gates, { export_ready: false }, "proposal export gate");

  snapshot = await resumeSnapshot(server, cycleId);
  const state = snapshot.snapshot.state;
  const proposalId = state.current.proposal;
  const proposalHash = state.records[proposalId].content_hash;

  const safety = await server.accepted(disposition("safety_ethics_review", {
    proposal_id: proposalId, proposal_hash: proposalHash,
    risk_findings: ["External execution risk"], export_only_boundary_confirmed: true,
  }, state), "safety disposition");
  revision = safety.revision;

  const execution = await server.accepted(disposition("execution_accountability", {
    proposal_id: proposalId, proposal_hash: proposalHash,
    handoff_owner: actor(),
    execution_boundary: { kind: "export_only", description: "external execution only" },
  }, state), "execution accountability disposition");
  revision = execution.revision;
  assertEqual(execution.payload.result.gates, { export_ready: false }, "pre-X export gate");

  // Local X=not_run flips the server-derived export gate.
  const notRun = await server.accepted(continueAction("execution.not_run", {
    proposal_id: proposalId, proposal_hash: proposalHash,
    status: "not_run", execution_kind: "not_run", accountable_party: null, performers: [],
    automation_mode: "not_run", boundary: { kind: "export_only", description: "external handoff only" },
    started_at: null, completed_at: null, artifact_ids: [], result_ids: [],
  }), "execution.not_run");
  revision = notRun.revision;
  assertEqual(notRun.payload.result.gates, { export_ready: true }, "post-X export gate opens");
  await resumeSnapshot(server, cycleId); // replay must accept the not_run frame

  // Export create/get.
  const exported = await server.accepted(envelope("export.create", {
    cycleId,
    payload: {
      expected_revision: revision, format: "scientific-export.v1", artifact_ids: [],
      report_body_id: null, redaction_profile_id: null, external_reference_ids: [],
    },
  }), "export.create");
  revision = exported.revision;
  const exportId = exported.payload.result.export_id;
  assertTrue(typeof exportId === "string" && exportId.length > 0, "export id issued");
  assertEqual(exported.payload.result.gates, { export_ready: true }, "post-export gate status");
  await resumeSnapshot(server, cycleId); // replay must accept the export frame

  const exportGet = await server.request(envelope("export.get", {
    read: true,
    payload: readPayload({ export_id: exportId, include_archive_bytes: false }),
  }));
  assertEqual(exportGet.name, "export.get.response", "export.get response");
  assertEqual(exportGet.payload.export_id, exportId, "export.get id");
  assertTrue(exportGet.payload.archive_base64 === null, "archive bytes withheld unless requested");

  // Interim report projection plus non-authoritative status overlay.
  const interim = await server.accepted(continueAction("write.interim", {
    ...stageFields(),
    source_revision: revision, source_artifact_ids: [], claim_ids: claims,
    result_ids: [], analysis_artifact_ids: [], limitations: ["No executed results yet."],
  }), "write.interim");
  revision = interim.revision;
  await resumeSnapshot(server, cycleId); // replay must accept the interim report frame

  const rendered = await server.request(envelope("report.render", {
    read: true,
    payload: readPayload({
      cycle_id: cycleId, at_revision: revision, format: "markdown", include_status_overlay: true,
    }),
  }));
  assertEqual(rendered.name, "report.render.response", `report.render response (${JSON.stringify(rendered.payload)})`);
  assertTrue(typeof rendered.payload.body_hash === "string", "report body hash present");
  assertTrue(rendered.payload.status_overlay !== undefined, "status overlay present");

  // Kill the sidecar mid-session; restart, resume, acknowledge.
  server.kill();
  server = new Sidecar(home);
  await server.hello();
  const recovered = await resumeSnapshot(server, cycleId);
  assertEqual(recovered.current_revision, revision, "revision survives sidecar kill");
  ackOrdinal += 1;
  const ack = await server.request(envelope("cycle.ack", {
    cycleId,
    read: true,
    payload: {
      client_instance_id: CLIENT, ack_ordinal: ackOrdinal,
      checkpoint: recovered.snapshot.checkpoint, state_hash: recovered.snapshot.state_hash,
    },
  }));
  assertEqual(ack.name, "cycle.acknowledged.response", "acknowledgement");
  assertEqual(ack.payload.accepted, true, "acknowledgement accepted");
  await server.shutdown();

  // Emergency read-only: reads succeed, every mutation is denied.
  writeFileSync(join(home, "config.json"), JSON.stringify({
    ai_scientist: {
      enabled: true, protocol_capability: true, allow_new_cycles: true,
      allow_external_result_import: false, emergency_read_only: true,
    },
  }));
  server = new Sidecar(home);
  const emergencyWelcome = await server.hello();
  assertEqual(emergencyWelcome.payload.operation_modes, ["read_only"], "emergency mode advertised");
  assertTrue(!emergencyWelcome.payload.capabilities.includes("cycle.continue"), "mutations unadvertised in emergency");
  const emergencyRead = await server.request(envelope("report.render", {
    read: true,
    payload: readPayload({
      cycle_id: cycleId, at_revision: revision, format: "markdown", include_status_overlay: false,
    }),
  }));
  assertEqual(emergencyRead.name, "report.render.response", "emergency read succeeds");
  await server.rejected(continueAction("landscape.complete", {
    invalidate_current_proposal: true,
    ...stageFields(),
    landscape_artifacts: [{ title: "Denied", summary: "Denied", source_artifact_ids: [], limitations: ["Denied"] }],
  }), "read_only", "emergency mutation");
  await server.shutdown();

  // Abort a separate cycle; terminal state closes the export gate.
  writeFileSync(join(home, "config.json"), JSON.stringify({
    ai_scientist: {
      enabled: true, protocol_capability: true, allow_new_cycles: true,
      allow_external_result_import: false, emergency_read_only: false,
    },
  }));
  server = new Sidecar(home);
  await server.hello();
  const secondStart = envelope("cycle.start", {
    payload: {
      creation_idempotency_key: "", expected_revision: 0, raw_question: "Second question?",
      contract_version: "ai-scientist.v1",
      boundary: { kind: "cognitive_only", description: "cognitive only" }, creator: actor(),
    },
  });
  secondStart.payload.creation_idempotency_key = secondStart.idempotency_key;
  const second = await server.accepted(secondStart, "second cycle.start");
  const secondCycle = second.payload.result.cycle_id;
  assertTrue(secondCycle !== cycleId, "second cycle is distinct");
  const aborted = await server.accepted(envelope("cycle.abort", {
    cycleId: secondCycle,
    payload: { expected_revision: second.revision, actor: actor(), reason: "operator stop", final_observation: "none" },
  }), "cycle.abort");
  assertEqual(aborted.payload.result.gates, { export_ready: false }, "aborted cycle export gate");
  await server.rejected(envelope("cycle.abort", {
    cycleId: secondCycle,
    payload: { expected_revision: aborted.revision, actor: actor(), reason: "again", final_observation: "none" },
  }), "gate_unsatisfied", "terminal cycle rejects further mutation");
  await server.shutdown();

  console.log("scientific-cycle sidecar E2E passed:", JSON.stringify({
    cycle_id: cycleId, final_revision: revision, export_id: exportId,
  }));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
