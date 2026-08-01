import { describe, expect, it } from "vitest";
import { normalizePersonaPoolSummary } from "../components/PersonaPoolCard";
import { browserPersonaRows } from "./runProgressCouncil";

describe("browserPersonaRows", () => {
  it("marks backend-selected personas with backend provenance", () => {
    const rows = browserPersonaRows(["persona-clinician", "mirofish-entity-regulator"]);

    expect(rows).toEqual([
      expect.objectContaining({
        name: "P-clinician",
        role: "selected persona",
        provenance: "Backend selected persona",
      }),
      expect.objectContaining({
        name: "M-regulator",
        role: "selected council persona",
        provenance: "Backend selected persona",
      }),
    ]);
  });

  it("returns the provenance-bearing fallback ladder before backend selection", () => {
    const rows = browserPersonaRows([]);

    expect(rows.map((row) => row.provenance)).toEqual([
      "Fallback template",
      "Persona sample pool",
      "Diversity sampling",
      "Council protocol",
    ]);
  });
});

describe("normalizePersonaPoolSummary", () => {
  it("maps backend telemetry into the stable pool summary", () => {
    const summary = normalizePersonaPoolSummary({
      persona_seed_source: "Nemotron-Personas-Korea",
      persona_validation_framework: "HACHIMI",
      persona_diversity_framework: "MAP-Elites",
      council_protocol: "OASIS/CAMEL",
      persona_pool_size: "32",
      persona_pool_target_size: 40,
      active_persona_count: 8,
      persona_diversity_coverage: 0.75,
      persona_diversity_bins_per_axis: 6,
      persona_fallbacks_used: 2,
    });

    expect(summary).toEqual({
      seedSource: "Nemotron-Personas-Korea",
      validationFramework: "HACHIMI",
      diversityFramework: "MAP-Elites",
      councilProtocol: "OASIS/CAMEL",
      poolSize: 32,
      poolTargetSize: 40,
      activeCount: 8,
      diversityCoverage: 0.75,
      diversityBinsPerAxis: 6,
      fallbacksUsed: 2,
    });
  });

  it("rejects empty telemetry and normalizes non-finite counts", () => {
    expect(normalizePersonaPoolSummary({})).toBeNull();
    expect(normalizePersonaPoolSummary({
      persona_seed_source: "seed",
      persona_pool_size: "not-a-number",
    })).toEqual(expect.objectContaining({
      seedSource: "seed",
      poolSize: 0,
    }));
  });
});
