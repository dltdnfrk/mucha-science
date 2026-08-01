import { describe, expect, it, vi } from "vitest";
import {
  createResearchExecutionAuthority,
} from "./useResearchConversation";
import {
  VALIDATION_DETAIL_ACTIONS,
} from "../pages/scientificPageProtocol";

describe("research conversation execution authority", () => {
  it("persists one matching cycle before one pipeline launch under duplicate retry", async () => {
    // Given
    const causalOrder: string[] = [];
    let acknowledgeLaunch: (() => void) | undefined;
    const launchAcknowledged = new Promise<void>((resolve) => {
      acknowledgeLaunch = resolve;
    });
    const acceptCycle = vi.fn(async (appRunId: string) => {
      causalOrder.push(`cycle:${appRunId}`);
      return {
        cycleId: "cycle_00000000000000000000000000000001",
        researchRunId: appRunId,
      };
    });
    const launchPipeline = vi.fn(async (appRunId: string) => {
      causalOrder.push(`start:${appRunId}`);
      await launchAcknowledged;
    });
    const authority = createResearchExecutionAuthority({
      acceptCycle,
      launchPipeline,
    });

    // When
    const first = authority.execute("run_00000000000000000000000000000001");
    await vi.waitFor(() => expect(launchPipeline).toHaveBeenCalledTimes(1));
    const retried = authority.execute("run_00000000000000000000000000000001");
    acknowledgeLaunch?.();
    const [firstCompanion, retriedCompanion] = await Promise.all([first, retried]);

    // Then
    expect(firstCompanion).toEqual(retriedCompanion);
    expect(acceptCycle).toHaveBeenCalledTimes(1);
    expect(launchPipeline).toHaveBeenCalledTimes(1);
    expect(causalOrder).toEqual([
      "cycle:run_00000000000000000000000000000001",
      "start:run_00000000000000000000000000000001",
    ]);
  });

  it("rejects a stale cycle identity before pipeline launch", async () => {
    // Given
    const launchPipeline = vi.fn(async () => undefined);
    const authority = createResearchExecutionAuthority({
      acceptCycle: async () => ({
        cycleId: "cycle_00000000000000000000000000000002",
        researchRunId: "run_ffffffffffffffffffffffffffffffff",
      }),
      launchPipeline,
    });

    // When
    const execution = authority.execute("run_00000000000000000000000000000002");

    // Then
    await expect(execution).rejects.toThrow("research run identity");
    expect(launchPipeline).not.toHaveBeenCalled();
  });

  it("keeps validation detail actions read-only and replay-oriented", () => {
    // Given / When
    const actions = new Set(VALIDATION_DETAIL_ACTIONS);

    // Then
    expect(actions).toEqual(new Set([
      "cycle.replay",
      "cycle.resume",
      "export.get",
      "report.render",
      "cycle.ack",
    ]));
    expect(actions.has("cycle.start")).toBe(false);
    expect(actions.has("validation.adjudicate")).toBe(false);
  });
});
