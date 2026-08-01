import type { Dispatch, SetStateAction } from "react";
import { describe, expect, it } from "vitest";
import type { CouncilActivity } from "./runProgressInteractionTypes";
import {
  handleCouncilEvent,
  type CouncilEventContext,
} from "./runProgressCouncilEvents";

describe("handleCouncilEvent provider failures", () => {
  it("maps the backend blocker discriminator and error class into council activity", () => {
    let activities: CouncilActivity[] = [];
    const setCouncilActivity: Dispatch<SetStateAction<CouncilActivity[]>> = (action) => {
      activities = typeof action === "function" ? action(activities) : action;
    };
    const context: CouncilEventContext = {
      setStages: () => {},
      setCouncilRound: () => {},
      setCouncilPersonas: () => {},
      setCouncilActivity,
      setTokenCards: () => {},
    };

    const handled = handleCouncilEvent({
      event: "council_provider_call_error",
      round: 3,
      persona: "persona-clinician",
      council_stage: "peer_review",
      provider: "mimo",
      error_class: "authentication",
      blocks_product_pass: "true",
      error: "provider rejected credentials",
    }, context);

    expect(handled).toBe(true);
    expect(activities).toEqual([
      expect.objectContaining({
        kind: "provider_call_error",
        errorClass: "authentication",
        blocksProductPass: true,
        text: "provider rejected credentials",
      }),
    ]);
  });
});
