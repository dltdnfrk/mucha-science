import { describe, expect, it } from "vitest";
import { buildPersonaPlanLayers, type StudioTurn } from "./StudioSession";

const turns: StudioTurn[] = [
  {
    id: "turn-scope",
    target: "정리 항목 · 범위",
    question: "scope?",
    rationale: "scope rationale",
    expected: "scope boundary",
  },
  {
    id: "turn-actor",
    target: "정리 항목 · 주체",
    question: "actor?",
    rationale: "actor rationale",
    expected: "actor boundary",
  },
  {
    id: "turn-evidence",
    target: "정리 항목 · 근거",
    question: "evidence?",
    rationale: "evidence rationale",
    expected: "evidence boundary",
  },
];

describe("buildPersonaPlanLayers", () => {
  it("builds three ordered pending layers from the supplied goal", () => {
    const layers = buildPersonaPlanLayers("coastal algae oxygen", turns);

    expect(layers.map((layer) => layer.layer)).toEqual(["Layer 1", "Layer 2", "Layer 3"]);
    expect(layers.map((layer) => layer.status)).toEqual(["pending", "pending", "pending"]);
    expect(layers.map((layer) => layer.basis)).toEqual([
      "coastal algae oxygen",
      "coastal algae oxygen",
      "coastal algae oxygen",
    ]);
  });

  it("binds each answered interview turn only to its corresponding layer", () => {
    const answered = turns.map((turn) =>
      turn.id === "turn-actor" ? { ...turn, answer: "hospital procurement lead" } : turn
    );

    const layers = buildPersonaPlanLayers("fallback goal", answered);

    expect(layers[0]).toEqual(expect.objectContaining({
      sourceTurnId: "turn-actor",
      status: "answered",
      basis: "hospital procurement lead",
    }));
    expect(layers[1]).toEqual(expect.objectContaining({
      sourceTurnId: "turn-evidence",
      status: "pending",
      basis: "fallback goal",
    }));
    expect(layers[2]).toEqual(expect.objectContaining({
      sourceTurnId: "turn-scope",
      status: "pending",
      basis: "fallback goal",
    }));
  });
});
