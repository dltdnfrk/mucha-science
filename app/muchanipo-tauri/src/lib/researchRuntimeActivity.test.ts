import { describe, expect, it } from "vitest";
import type { BackendEvent } from "./tauriClient";
import {
  emptyResearchActivity,
  reduceResearchActivity,
  toResearchActivityProjections,
  toResearchProviderProjection,
} from "./researchRuntime";

const context = {
  runId: "app-run-algae-20260725",
  turnId: "turn-algae-1",
  eventIndex: 7,
  generation: 7,
};

describe("toResearchProviderProjection", () => {
  it("keeps model attempts separate and projects ordered academic route summaries", () => {
    const academicAttempt = toResearchProviderProjection({
      event: "provider_attempt",
      schema_version: "research-event.v1",
      provider_kind: "academic_source",
      attempt_id: "attempt:academic:openalex",
      route_id: "route:fixture:mixed",
      provider: "openalex",
      outcome: "success",
      count: 2,
    });
    const modelAttempt = toResearchProviderProjection({
      event: "provider_attempt",
      schema_version: "research-event.v1",
      provider_kind: "model",
      attempt_id: "attempt:model:opencode",
      route_id: "model:council",
      provider: "opencode",
      outcome: "failed",
      count: 0,
      failure: { code: "authentication", message: "HTTP 401 unauthorized" },
    });
    const summary = toResearchProviderProjection({
      event: "academic_route_summary",
      schema_version: "research-event.v1",
      route_id: "route:fixture:mixed",
      attempt_ids: ["attempt:academic:openalex", "attempt:academic:crossref"],
      outcome: "partial",
      count: 2,
    });

    expect(academicAttempt).toEqual(expect.objectContaining({
      kind: "academic_attempt",
      provider: "openalex",
      outcome: "success",
    }));
    expect(modelAttempt).toEqual(expect.objectContaining({
      kind: "model_attempt",
      provider: "opencode",
      outcome: "failed",
    }));
    expect(summary).toEqual(expect.objectContaining({
      kind: "academic_route_summary",
      routeId: "route:fixture:mixed",
      outcome: "partial",
    }));
  });
});

describe("research activity projection", () => {
  it("projects provider routes, evidence identity, stance, and ordinal uncertainty", () => {
    const events = [
      {
        event: "provider_attempt",
        app_run_id: context.runId,
        generation: context.generation,
        schema_version: "research-event.v1",
        provider_kind: "academic_source",
        attempt_id: "attempt:openalex",
        route_id: "route:literature",
        provider: "openalex",
        outcome: "success",
        count: 2,
      },
      {
        event: "academic_route_summary",
        app_run_id: context.runId,
        generation: context.generation,
        schema_version: "research-event.v1",
        route_id: "route:literature",
        attempt_ids: ["attempt:openalex"],
        outcome: "success",
        count: 2,
      },
      {
        event: "research_progress",
        app_run_id: context.runId,
        generation: context.generation,
        status: "source_decision",
        source_id: "source:algae",
        source_title: "Algae oxygen study",
        source_url: "https://doi.org/10.1000/algae",
        canonical_id: "doi:10.1000/algae",
        accepted: true,
      },
      {
        event: "research_progress",
        app_run_id: context.runId,
        generation: context.generation,
        status: "claim_evidence_gate",
        rows: [{
          claim_id: "claim:oxygen",
          claim: "해조류는 산소를 생산한다.",
          stance: "supports_claim",
          confidence: 0.97,
          uncertainty: "moderate",
        }],
      },
    ] satisfies BackendEvent[];

    const activity = events.reduce(
      (current, event) => reduceResearchActivity(
        current,
        toResearchActivityProjections(event, context),
      ),
      emptyResearchActivity(),
    );

    expect(activity.providers).toEqual([expect.objectContaining({
      provider: "openalex",
      routeId: "route:literature",
      outcome: "success",
    })]);
    expect(activity.routes).toEqual([expect.objectContaining({
      routeId: "route:literature",
      outcome: "success",
    })]);
    expect(activity.evidence).toEqual([expect.objectContaining({
      citationId: "doi:10.1000/algae",
      locator: "https://doi.org/10.1000/algae",
      sourceId: "source:algae",
    })]);
    expect(activity.claims).toEqual([expect.objectContaining({
      claimId: "claim:oxygen",
      stance: "supports",
      uncertainty: "moderate",
    })]);
    expect(JSON.stringify(activity)).not.toContain("0.97");
    expect(JSON.stringify(activity)).not.toContain("confidence");
  });

  it("aggregates a bounded counter-search batch and truthful no-novelty stop", () => {
    const statuses = [
      { status: "refutation_pass_started", task_count: 2 },
      { status: "refutation_query_executed" },
      { status: "refutation_source_evaluated" },
      {
        status: "refutation_pass_completed",
        reason: "completed all assessed with no novelty",
      },
    ];
    const activity = statuses.reduce((current, progress) => {
      const event = {
        event: "research_progress",
        app_run_id: context.runId,
        generation: context.generation,
        ...progress,
      } satisfies BackendEvent;
      return reduceResearchActivity(
        current,
        toResearchActivityProjections(event, context),
      );
    }, emptyResearchActivity());

    expect(activity.counterSearch).toEqual({
      batchSize: 2,
      evaluated: 1,
      executed: 1,
      noNovelty: true,
      status: "completed",
      stopReason: "completed all assessed with no novelty",
    });
  });

  it("rejects unsupported generations and premature cancellation", () => {
    const provider = {
      event: "provider_attempt",
      app_run_id: context.runId,
      generation: context.generation,
      schema_version: "research-event.v1",
      provider_kind: "academic_source",
      attempt_id: "attempt:provider",
      route_id: "route:provider",
      provider: "provider",
      outcome: "success",
      count: 1,
    } satisfies BackendEvent;
    const cancellation = {
      event: "execution_cancelled",
      app_run_id: context.runId,
      generation: context.generation,
      termination_observed: false,
      reaped: false,
    } satisfies BackendEvent;

    expect(toResearchActivityProjections(
      { ...provider, generation: context.generation - 1 },
      context,
    )).toEqual([]);
    expect(toResearchActivityProjections(
      { ...provider, schema_version: "research-event.v2" },
      context,
    )).toEqual([]);
    expect(toResearchActivityProjections(cancellation, context)).toEqual([]);
    expect(toResearchActivityProjections(
      { ...cancellation, termination_observed: true, reaped: true },
      context,
    )).toEqual([{ kind: "cancellation_acknowledged" }]);
  });
});
