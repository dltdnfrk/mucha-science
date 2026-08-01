import { describe, expect, it } from "vitest";
import {
  backendEventName,
  type InterviewOntologyDeltaEvent,
  type PipelineStartedEvent,
} from "./types";

describe("backendEventName", () => {
  it("prefers the backend event discriminator when both names are present", () => {
    const event: PipelineStartedEvent = {
      type: "pipeline_started",
      event: "run_started",
      topic: "algae oxygen",
      session_id: "session-1",
      ts: "2026-07-25T00:00:00Z",
    };

    expect(backendEventName(event)).toBe("run_started");
  });

  it("recognizes an ontology delta through its typed fallback discriminator", () => {
    const event: InterviewOntologyDeltaEvent = {
      type: "interview_ontology_delta",
      targets_unknown_ids: ["unknown-evidence"],
      question_quality_gate: { passed: true },
    };

    expect(backendEventName(event)).toBe("interview_ontology_delta");
  });
});
