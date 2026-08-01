import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import ChapterCard from "../components/ChapterCard";
import EvidenceIndexPanel from "../components/EvidenceIndexPanel";
import { SafeReportMarkdown } from "../components/SafeReportMarkdown";
import SourceDiscoveryPanel, {
  type DiscoveredSource,
  type KnowledgeGap,
} from "../components/SourceDiscoveryPanel";
import { parseChapterMarkdown } from "../lib/parseChapterMarkdown";
import { parseEvidenceIndex } from "../lib/reportPresentation";
import {
  getBufferedEvents,
  onBackendEvent,
  type BackendEvent,
  type Chapter,
} from "../lib/tauriClient";
import { sanitizeMarkdownExternalReferences } from "../lib/safeExternalUrl";
import {
  hasReadyStoredReport,
  persistPendingReport,
  persistReportReadiness,
  promotePendingReport,
} from "./runProgressStorage";

export default function ReportView() {
  const { runId } = useParams<{ runId: string }>();
  const [markdown, setMarkdown] = useState<string>("");
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [showRaw, setShowRaw] = useState(false);
  const [topic, setTopic] = useState<string>("");
  const [discoveredSources, setDiscoveredSources] = useState<DiscoveredSource[]>([]);
  const [knowledgeGaps, setKnowledgeGaps] = useState<KnowledgeGap[]>([]);
  const chunkKeysRef = useRef<Set<string>>(new Set());
  const finalReportReceivedRef = useRef(false);

  useEffect(() => {
    if (!runId) return;
    let mounted = true;
    let unlisten: (() => void) | undefined;
    const applyMarkdown = (md: string) => {
      if (!mounted) return;
      setMarkdown(md);
      setChapters(parseChapterMarkdown(md));
    };
    const appendChunk = (chunk: string) => {
      const safeChunk = sanitizeMarkdownExternalReferences(chunk);
      const key = safeChunk.trim();
      if (!key || finalReportReceivedRef.current || chunkKeysRef.current.has(key)) return;
      chunkKeysRef.current.add(key);
      const current = localStorage.getItem(`run:${runId}:report_pending`) || "";
      const next = `${current}${current ? "\n\n" : ""}${safeChunk}`;
      localStorage.setItem(`run:${runId}:report_pending`, next);
    };
    const handleEvent = (event: BackendEvent) => {
      if (!runId) return;
      if (event.event === "final_report") {
        const markdown = String(event.markdown ?? "");
        if (markdown) {
          finalReportReceivedRef.current = true;
          chunkKeysRef.current.clear();
          persistPendingReport(runId, {
            chapterCount: Number(event.chapter_count ?? 0),
            markdown,
            reportPath: String(event.report_path ?? ""),
            vaultPath: String(event.vault_path ?? ""),
          });
        }
        return;
      }
      if (event.event === "done") {
        const readiness = persistReportReadiness(
          runId,
          event.research_quality_readiness,
        );
        if (readiness === "ready" || readiness === "legacy") {
          const promoted = promotePendingReport(runId);
          if (promoted) applyMarkdown(promoted);
        }
        return;
      }
      if (event.event === "report_chunk") {
        const chunk = String(event.markdown ?? event.delta ?? "");
        if (!chunk) return;
        appendChunk(chunk);
      }
    };
    try {
      const md = hasReadyStoredReport(runId)
        ? localStorage.getItem(`run:${runId}:report`) || ""
        : "";
      applyMarkdown(md);
      setTopic(localStorage.getItem(`run:${runId}:topic`) || "");
      const rawSources = localStorage.getItem(`run:${runId}:sources`);
      if (rawSources) {
        const parsed = JSON.parse(rawSources) as [string, DiscoveredSource][];
        setDiscoveredSources(Array.from(new Map(parsed).values()).sort((a, b) => b.firstSeenAt - a.firstSeenAt));
      } else if (md) {
        const parsed = parseEvidenceIndex(md);
        if (parsed.sources.length > 0) {
          setDiscoveredSources(
            parsed.sources.map(
              (src, index): DiscoveredSource => ({
                key: src.id || `report-source-${index}`,
                title: src.title,
                url: src.url,
                grade: src.grade,
                accessStatus: src.accessStatus,
                status: "accepted",
                firstSeenAt: 0,
              }),
            ),
          );
        }
      }
      const rawGaps = localStorage.getItem(`run:${runId}:gaps`);
      if (rawGaps) setKnowledgeGaps(JSON.parse(rawGaps) as KnowledgeGap[]);
    } catch {
      /* ignore */
    }
    onBackendEvent(handleEvent, runId).then(async (cleanup) => {
      if (!mounted) {
        cleanup();
        return;
      }
      unlisten = cleanup;
      try {
        const history = await getBufferedEvents(runId);
        for (const event of history) handleEvent(event);
      } catch {
        /* non-fatal */
      }
    });
    return () => {
      mounted = false;
      unlisten?.();
    };
  }, [runId]);

  const exportMarkdown = () => {
    if (!markdown) return;
    const blob = new Blob([markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const name = topic ? topic.replace(/\s+/g, "_") : runId || "report";
    a.href = url;
    a.download = `${name}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  if (!markdown) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-4">
        <svg className="h-5 w-5 animate-spin text-white/60" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.3" strokeWidth="3" />
          <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
        <p className="text-sm text-tertiary">보고서를 불러오는 중…</p>
      </div>
    );
  }

  return (
    <div className="report-reader min-h-screen px-6 py-8">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <header className="fade-in mb-8 grid gap-5 border-b border-white/10 pb-6 md:grid-cols-[1fr_auto] md:items-end">
          <div>
            <p className="atlas-label mb-2">
              MBB 6-chapter report
            </p>
            <h1 className="display-serif max-w-4xl text-[34px] font-semibold leading-tight text-white md:text-[46px]">
              {topic || "리서치 보고서"}
            </h1>
            <p className="mt-3 font-mono text-xs text-tertiary">{runId}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowRaw((s) => !s)}
              className="rounded-md border border-white/10 bg-transparent px-3.5 py-2 text-xs text-secondary transition hover:bg-white/5 hover:text-white"
            >
              {showRaw ? "카드 보기" : "원본 Markdown"}
            </button>
            <button
              onClick={exportMarkdown}
              className="rounded-md bg-white px-3.5 py-2 text-xs font-medium text-black transition hover:opacity-90"
            >
              다운로드
            </button>
          </div>
        </header>

        {/* Body */}
        {(discoveredSources.length > 0 || knowledgeGaps.length > 0) && (
          <div className="mb-6 overflow-hidden rounded-lg border border-white/5 bg-white/[0.02] shadow-[var(--shadow-paper)]">
            <SourceDiscoveryPanel sources={discoveredSources} gaps={knowledgeGaps} compact />
          </div>
        )}

        {showRaw ? (
          <div className="space-y-4">
            <EvidenceIndexPanel markdown={markdown} compact />
            <div className="chapter-card p-6 md:p-8">
              <div className="report-prose max-w-none">
            <SafeReportMarkdown markdown={markdown} />
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <EvidenceIndexPanel markdown={markdown} compact />
            {chapters.length > 0 ? (
              chapters.map((chapter) => (
                <ChapterCard
                  key={chapter.chapter_no}
                  chapter={chapter}
                  highlightScr={chapter.chapter_no === 1}
                />
              ))
            ) : (
              <div className="chapter-card p-6">
                <p className="text-sm text-tertiary">
                  파싱된 챕터가 없습니다. 원본 Markdown을 확인해주세요.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
