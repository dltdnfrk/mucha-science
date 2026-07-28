import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  hasReadyStoredReport,
  readStoredReportReadiness,
} from "./runProgressStorage";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

beforeEach(() => {
  vi.stubGlobal("localStorage", new MemoryStorage());
});

describe("stored report recovery boundary", () => {
  it.each(["needs_review", "blocked", "unknown"] as const)(
    "does not recover a persisted report with %s readiness",
    (readiness) => {
      localStorage.setItem("run:recovery:report", "# withheld");
      localStorage.setItem("run:recovery:report_path", "/tmp/report.md");
      if (readiness !== "unknown") {
        localStorage.setItem("run:recovery:quality_readiness", readiness);
      }

      expect(readStoredReportReadiness("recovery")).toBe(readiness);
      expect(hasReadyStoredReport("recovery")).toBe(false);
    },
  );

  it.each(["ready", "legacy"] as const)(
    "recovers a complete persisted report with explicit %s readiness",
    (readiness) => {
      localStorage.setItem("run:recovery:report", "# ready");
      localStorage.setItem("run:recovery:report_path", "/tmp/report.md");
      localStorage.setItem("run:recovery:quality_readiness", readiness);

      expect(hasReadyStoredReport("recovery")).toBe(true);
    },
  );
});
