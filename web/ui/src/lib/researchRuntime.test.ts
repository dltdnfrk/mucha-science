import { describe, expect, it } from "vitest";
import type { BackendEvent } from "./tauriClient";
import {
  researchConversationStorageKey,
  toResearchConversationEvent,
  toResearchInteraction,
} from "./researchRuntime";

type ResearchRuntimeContext = {
  readonly runId: string;
  readonly turnId: string;
  readonly eventIndex: number;
};

const context: ResearchRuntimeContext = {
  runId: "app-run-algae-20260725",
  turnId: "turn-algae-1",
  eventIndex: 7,
};

describe("toResearchConversationEvent", () => {
  it("maps matching research progress to a canonical event with source and artifact IDs", () => {
    // Given
    const event = {
      event: "research_progress",
      app_run_id: context.runId,
      status: "source_found",
      query: "coastal algae oxygen production",
      source_url: "https://doi.org/10.1038/s41586-019-1666-6",
      source_title: "Coastal algae oxygen production study",
      artifact_ids: ["artifact:source-audit:app-run-algae-20260725"],
    } satisfies BackendEvent;

    // When
    const adapted = toResearchConversationEvent(event, context);

    // Then
    expect(adapted).toMatchObject({
      event: "research_progress",
      eventId: "app-run-algae-20260725:turn-algae-1:7",
      runId: "app-run-algae-20260725",
      turnId: "turn-algae-1",
      sourceIds: ["https://doi.org/10.1038/s41586-019-1666-6"],
      artifactIds: ["artifact:source-audit:app-run-algae-20260725"],
    });
    expect(adapted?.stage).toContain("coastal algae oxygen production");
    expect(adapted?.stage).toContain("Coastal algae oxygen production study");
  });

  it("maps report chunks and final reports without losing markdown or the report artifact", () => {
    // Given
    const reportChunk = {
      event: "report_chunk",
      app_run_id: context.runId,
      markdown: "## Evidence\n\nThe algae sample produced oxygen.",
    } satisfies BackendEvent;
    const finalReport = {
      event: "final_report",
      app_run_id: context.runId,
      markdown: "# Final report\n\nValidated findings.",
      report_path: "/tmp/muchanipo/algae-report.md",
    } satisfies BackendEvent;

    // When
    const chunk = toResearchConversationEvent(reportChunk, context);
    const final = toResearchConversationEvent(finalReport, {
      ...context,
      eventIndex: 8,
    });

    // Then
    expect(chunk).toEqual({
      event: "report_chunk",
      eventId: "app-run-algae-20260725:turn-algae-1:7",
      runId: "app-run-algae-20260725",
      turnId: "turn-algae-1",
      body: "## Evidence\n\nThe algae sample produced oxygen.",
      sourceIds: [],
      artifactIds: [],
    });
    expect(final).toEqual({
      event: "final_report",
      eventId: "app-run-algae-20260725:turn-algae-1:8",
      runId: "app-run-algae-20260725",
      turnId: "turn-algae-1",
      body: "# Final report\n\nValidated findings.",
      sourceIds: [],
      artifactIds: ["/tmp/muchanipo/algae-report.md"],
    });
  });

  it("ignores cross-run, malformed, and unrelated backend events", () => {
    // Given
    const crossRun = {
      event: "research_progress",
      app_run_id: "app-run-other",
      status: "source_found",
      query: "different run",
      source_url: "https://example.test/source",
      source_title: "Other source",
    } satisfies BackendEvent;
    const malformed = {
      event: "research_progress",
      app_run_id: context.runId,
      status: "",
      query: "coastal algae oxygen production",
    } satisfies BackendEvent;
    const unrelated = {
      event: "warning",
      app_run_id: context.runId,
      message: "non-conversation telemetry",
    } satisfies BackendEvent;

    // When
    const adapted = [crossRun, malformed, unrelated].map((event) =>
      toResearchConversationEvent(event, context),
    );

    // Then
    expect(adapted).toEqual([undefined, undefined, undefined]);
  });
});

describe("toResearchInteraction", () => {
  it("maps an interview question to an inline interaction", () => {
    // Given
    const event = {
      event: "interview_question",
      app_run_id: context.runId,
      q_id: "Q1_research_goal",
      text: "Which research outcome matters most?",
      options: [
        { key: "A", label: "Evidence summary" },
        { key: "B", label: "Experimental plan" },
      ],
    } satisfies BackendEvent;

    // When
    const interaction = toResearchInteraction(event, context);

    // Then
    expect(interaction).toEqual({
      kind: "inline",
      id: "Q1_research_goal",
      title: "Research question",
      prompt: "Which research outcome matters most?",
      options: [
        { key: "A", label: "Evidence summary" },
        { key: "B", label: "Experimental plan" },
      ],
    });
  });

  it("maps a HITL gate to an inline interaction with its gate metadata", () => {
    // Given
    const event = {
      event: "hitl_gate",
      app_run_id: context.runId,
      gate: "evidence",
      title: "Evidence review",
      prompt: "Approve the collected evidence to continue.",
      options: [
        { key: "approve", label: "Approve", value: "approved" },
        { key: "changes", label: "Request changes", value: "changes_requested" },
      ],
    } satisfies BackendEvent;

    // When
    const interaction = toResearchInteraction(event, context);

    // Then
    expect(interaction).toEqual({
      kind: "inline",
      id: "evidence",
      title: "Evidence review",
      prompt: "Approve the collected evidence to continue.",
      options: [
        { key: "approve", label: "Approve", value: "approved" },
        { key: "changes", label: "Request changes", value: "changes_requested" },
      ],
    });
  });
});

describe("researchConversationStorageKey", () => {
  it("is versioned and excludes question and secret material", () => {
    // Given
    const question = "How does coastal algae oxygen production change?";
    const secret = "sk-live-example-secret";

    // When
    const key = researchConversationStorageKey(context);

    // Then
    expect(key).toMatch(/^muchanipo\.research-conversation\.v\d+\./);
    expect(key).not.toContain(question);
    expect(key).not.toContain(secret);
  });
});
