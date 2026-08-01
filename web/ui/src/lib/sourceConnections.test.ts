import { describe, expect, it } from "vitest";
import {
  addCustomSource,
  deserializeSourceConnections,
  getDefaultSourceConnections,
  serializeSourceConnections,
} from "./sourceConnections";

describe("source connection registry", () => {
  it("exposes the built-in research source connections", () => {
    const sourceNames = getDefaultSourceConnections().map((source) => source.name);

    expect(sourceNames).toEqual(
      expect.arrayContaining([
        "OpenAlex",
        "Crossref",
        "PubMed/NCBI",
        "Semantic Scholar",
        "Springer Nature",
        "Elsevier",
        "OASIS",
      ]),
    );
  });

  it("round-trips custom metadata and connection state through persisted data", () => {
    const sources = addCustomSource(getDefaultSourceConnections(), {
      id: "custom-lab-index",
      name: "Custom Lab Index",
      url: "https://lab.example.org/index",
      description: "A user-managed literature index",
      status: "connected",
    });

    const restored = deserializeSourceConnections(serializeSourceConnections(sources));
    const restoredCustomSource = restored.find((source) => source.id === "custom-lab-index");

    expect(restoredCustomSource).toEqual(
      expect.objectContaining({
        id: "custom-lab-index",
        name: "Custom Lab Index",
        url: "https://lab.example.org/index",
        description: "A user-managed literature index",
        status: "connected",
      }),
    );
  });

  it("rejects a custom source with an empty name", () => {
    expect(() =>
      addCustomSource(getDefaultSourceConnections(), {
        id: "missing-name",
        name: "   ",
        url: "https://example.org/api",
      }),
    ).toThrow();
  });

  it("rejects a custom source with an invalid URL", () => {
    expect(() =>
      addCustomSource(getDefaultSourceConnections(), {
        id: "invalid-url",
        name: "Invalid URL Source",
        url: "not-a-url",
      }),
    ).toThrow();
  });

  it("never serializes API keys or secrets", () => {
    const sources = addCustomSource(getDefaultSourceConnections(), {
      id: "credentialed-source",
      name: "Credentialed Source",
      url: "https://private.example.org/api",
      apiKey: "api-key-must-not-persist",
      secret: "secret-must-not-persist",
    });

    const serialized = serializeSourceConnections(sources);

    expect(serialized).not.toContain("api-key-must-not-persist");
    expect(serialized).not.toContain("secret-must-not-persist");
    expect(serialized).not.toContain("apiKey");
    expect(serialized).not.toContain("secret");
  });

  it("allows arbitrary custom source definitions", () => {
    const sources = addCustomSource(getDefaultSourceConnections(), {
      id: "community-index",
      name: "Community Index",
      url: "https://community.example.org/search",
    });

    expect(sources.some((source) => source.id === "community-index")).toBe(true);
  });
});
