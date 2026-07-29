import { describe, expect, it } from "vitest";
import {
  isSafeExternalHttpUrl,
  sanitizeExternalReference,
} from "./safeExternalUrl";

describe("external URL safety", () => {
  it.each([
    "https://reader:password@example.org/paper",
    "https://example.org/paper?api_key=secret",
    "https://example.org/paper?access-token=secret",
  ])("rejects credential-bearing external URLs: %s", (value) => {
    expect(isSafeExternalHttpUrl(value)).toBe(false);
  });

  it("removes credentials while preserving non-sensitive URL context", () => {
    expect(sanitizeExternalReference(
      "https://reader:password@example.org/paper?api_key=secret&view=full#evidence",
    )).toBe("https://example.org/paper?view=full#evidence");
  });

  it("leaves non-HTTP research identifiers unchanged", () => {
    expect(sanitizeExternalReference("doi:10.1038/s41586-019-1666-6"))
      .toBe("doi:10.1038/s41586-019-1666-6");
  });
});
