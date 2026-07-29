import type { DiscoveredSource, KnowledgeGap } from "../components/SourceDiscoveryPanel";
import { sanitizeMarkdownExternalReferences } from "../lib/safeExternalUrl";
import type { StudioProvenance } from "./runProgressInteractionTypes";

export type ReportReadiness =
  | "ready"
  | "needs_review"
  | "blocked"
  | "unknown"
  | "legacy";

const STORED_REPORT_READINESS = new Set<ReportReadiness>([
  "ready",
  "needs_review",
  "blocked",
  "legacy",
]);

function ignoreStorageError(error: unknown): void {
  if (!(error instanceof Error)) throw error;
}

export function readStoredSources(runId?: string): Map<string, DiscoveredSource> {
  if (!runId) return new Map();
  try {
    const raw = localStorage.getItem(`run:${runId}:sources`);
    return raw ? new Map(JSON.parse(raw) as [string, DiscoveredSource][]) : new Map();
  } catch (error) {
    ignoreStorageError(error);
    return new Map();
  }
}

export function readStoredKnowledgeGaps(runId?: string): KnowledgeGap[] {
  if (!runId) return [];
  try {
    const raw = localStorage.getItem(`run:${runId}:gaps`);
    return raw ? JSON.parse(raw) as KnowledgeGap[] : [];
  } catch (error) {
    ignoreStorageError(error);
    return [];
  }
}

export function readRunIdentity(runId: string): {
  readonly topic: string;
  readonly provenance: StudioProvenance | null;
} {
  try {
    const studioId = localStorage.getItem(`run:${runId}:studioId`);
    const studioModel = localStorage.getItem(`run:${runId}:studioModel`);
    const studioBrief = localStorage.getItem(`run:${runId}:studioBrief`);
    const provenance: StudioProvenance = {
      ...(studioId ? { studioId } : {}),
      ...(studioModel ? { studioModel } : {}),
      ...(studioBrief ? { studioBrief } : {}),
    };
    return {
      topic: localStorage.getItem(`run:${runId}:topic`) || "",
      provenance: studioId || studioModel || studioBrief ? provenance : null,
    };
  } catch (error) {
    ignoreStorageError(error);
    return { topic: "", provenance: null };
  }
}

export function persistRunValue(runId: string, suffix: string, value: string): void {
  try {
    localStorage.setItem(`run:${runId}:${suffix}`, value);
  } catch (error) {
    ignoreStorageError(error);
  }
}

export function readReportReadiness(value: unknown): ReportReadiness {
  return typeof value === "string"
    && STORED_REPORT_READINESS.has(value as ReportReadiness)
    ? value as ReportReadiness
    : "unknown";
}

export function readStoredReportReadiness(runId: string): ReportReadiness {
  try {
    return readReportReadiness(
      localStorage.getItem(`run:${runId}:quality_readiness`),
    );
  } catch (error) {
    ignoreStorageError(error);
    return "unknown";
  }
}

export function hasReadyStoredReport(runId: string): boolean {
  try {
    const readiness = readStoredReportReadiness(runId);
    return Boolean(
      localStorage.getItem(`run:${runId}:report`)
      && localStorage.getItem(`run:${runId}:report_path`)
      && (readiness === "ready" || readiness === "legacy"),
    );
  } catch (error) {
    ignoreStorageError(error);
    return false;
  }
}

export function persistReportReadiness(
  runId: string,
  value: unknown,
): ReportReadiness {
  const readiness = readReportReadiness(value);
  persistRunValue(runId, "quality_readiness", readiness);
  return readiness;
}

export function persistPendingReport(
  runId: string,
  report: {
    readonly markdown: string;
    readonly reportPath: string;
    readonly vaultPath?: string;
    readonly chapterCount?: number;
  },
): string {
  const markdown = sanitizeMarkdownExternalReferences(report.markdown);
  try {
    for (const suffix of ["report", "report_path", "vault_path", "chapter_count"]) {
      localStorage.removeItem(`run:${runId}:${suffix}`);
    }
    if (markdown) localStorage.setItem(`run:${runId}:report_pending`, markdown);
    localStorage.setItem(`run:${runId}:report_path_pending`, report.reportPath);
    if (report.vaultPath) {
      localStorage.setItem(`run:${runId}:vault_path_pending`, report.vaultPath);
    }
    localStorage.setItem(
      `run:${runId}:chapter_count_pending`,
      String(report.chapterCount ?? 0),
    );
  } catch (error) {
    ignoreStorageError(error);
  }
  return markdown;
}

export function promotePendingReport(runId: string): string {
  try {
    const markdown = localStorage.getItem(`run:${runId}:report_pending`) ?? "";
    const reportPath = localStorage.getItem(`run:${runId}:report_path_pending`) ?? "";
    if (!markdown || !reportPath) return "";
    const vaultPath = localStorage.getItem(`run:${runId}:vault_path_pending`) ?? "";
    const chapterCount = localStorage.getItem(`run:${runId}:chapter_count_pending`) ?? "0";
    localStorage.setItem(`run:${runId}:report`, markdown);
    localStorage.setItem(`run:${runId}:report_path`, reportPath);
    if (vaultPath) localStorage.setItem(`run:${runId}:vault_path`, vaultPath);
    localStorage.setItem(`run:${runId}:chapter_count`, chapterCount);
    for (const suffix of [
      "report_pending",
      "report_path_pending",
      "vault_path_pending",
      "chapter_count_pending",
    ]) {
      localStorage.removeItem(`run:${runId}:${suffix}`);
    }
    return markdown;
  } catch (error) {
    ignoreStorageError(error);
    return "";
  }
}
