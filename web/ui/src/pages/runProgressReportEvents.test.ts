import type { Dispatch, SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { handleReportEvent } from "./runProgressReportEvents";
import type { ReportEventContext } from "./runProgressReportEvents";
import { initialStageState } from "./runProgressStages";
import type { ReportReadiness } from "./runProgressStorage";
import type { ResearchActivity } from "./runProgressTypes";

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

let storage: MemoryStorage;

beforeEach(() => {
  storage = new MemoryStorage();
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", {
    dispatchEvent: vi.fn(),
    localStorage: storage,
    setTimeout: vi.fn(() => 1),
  });
  vi.stubGlobal("CustomEvent", class {
    constructor(readonly type: string) {}
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("handleReportEvent quality boundary", () => {
  it("sanitizes pending Markdown and promotes it only after ready", () => {
    let finalReport = "";
    let readiness: ReportReadiness = "unknown";
    const context = createContext(
      (value) => {
        finalReport = reduceState(finalReport, value);
      },
      (value) => {
        readiness = reduceState(readiness, value);
      },
    );

    handleReportEvent({
      chapter_count: 1,
      event: "final_report",
      markdown:
        "[민감 링크](https://reader:password@example.org/paper?authorization=secret)",
      report_path: "/tmp/report.md",
    }, context);

    expect(finalReport).toBe("");
    expect(storage.getItem("run:run-quality:report")).toBeNull();
    expect(storage.getItem("run:run-quality:report_pending")).not.toContain("secret");
    expect(storage.getItem("run:run-quality:report_pending")).not.toContain("password");

    handleReportEvent({
      event: "done",
      research_quality_only: true,
      research_quality_readiness: "ready",
      status: "research_quality_ready",
    }, context);

    expect(readiness).toBe("ready");
    expect(finalReport).toContain("example.org/paper");
    expect(storage.getItem("run:run-quality:report")).toBe(finalReport);
    expect(storage.getItem("run:run-quality:report_pending")).toBeNull();
  });

  it.each(["needs_review", "blocked"] as const)(
    "withholds a pending report when quality is %s",
    (qualityReadiness) => {
      let finalReport = "";
      let readiness: ReportReadiness = "unknown";
      const context = createContext(
        (value) => {
          finalReport = reduceState(finalReport, value);
        },
        (value) => {
          readiness = reduceState(readiness, value);
        },
      );
      handleReportEvent({
        event: "final_report",
        markdown: "# 보류 보고서",
        report_path: "/tmp/report.md",
      }, context);

      handleReportEvent({
        event: "done",
        research_quality_only: true,
        research_quality_readiness: qualityReadiness,
      }, context);

      expect(readiness).toBe(qualityReadiness);
      expect(finalReport).toBe("");
      expect(storage.getItem("run:run-quality:report")).toBeNull();
      expect(storage.getItem("run:run-quality:quality_readiness"))
        .toBe(qualityReadiness);
    },
  );

  it("promotes a full-run report that completed with reviewable gaps", () => {
    let finalReport = "";
    let readiness: ReportReadiness = "unknown";
    const context = createContext(
      (value) => {
        finalReport = reduceState(finalReport, value);
      },
      (value) => {
        readiness = reduceState(readiness, value);
      },
    );
    handleReportEvent({
      event: "final_report",
      markdown: "# 검토 필요 보고서",
      report_path: "/tmp/report.md",
    }, context);

    handleReportEvent({
      event: "done",
      pipeline: "full",
      research_quality_readiness: "needs_review",
    }, context);

    expect(readiness).toBe("needs_review");
    expect(finalReport).toContain("검토 필요 보고서");
    expect(storage.getItem("run:run-quality:report")).toBe(finalReport);
    expect(storage.getItem("run:run-quality:report_pending")).toBeNull();
  });
});

function createContext(
  setFinalReport: Dispatch<SetStateAction<string>>,
  setReportReadiness: Dispatch<
    SetStateAction<"ready" | "needs_review" | "blocked" | "unknown" | "legacy">
  >,
): ReportEventContext {
  return {
    chunkKeysRef: { current: new Set() },
    finalReportReceivedRef: { current: false },
    isMounted: () => true,
    navigate: vi.fn() as unknown as NavigateFunction,
    navigationTimers: new Set(),
    runErrorRef: { current: null },
    runId: "run-quality",
    setFinalReport,
    setHitlPrompt: noopSetter(),
    setHitlSubmitting: noopSetter(),
    setInterviewPrompt: noopSetter(),
    setInterviewSubmitting: noopSetter(),
    setReportPreview: noopSetter(),
    setReportReadiness,
    setResearchActivity: noopSetter<ResearchActivity[]>(),
    setStages: noopSetter(),
  };
}

function noopSetter<Value>(): Dispatch<SetStateAction<Value>> {
  return () => undefined;
}

function reduceState<Value>(
  current: Value,
  value: SetStateAction<Value>,
): Value {
  return typeof value === "function"
    ? (value as (previous: Value) => Value)(current)
    : value;
}
