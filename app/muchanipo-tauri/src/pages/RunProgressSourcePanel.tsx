import SourceDiscoveryPanel, {
  type DiscoveredSource,
  type KnowledgeGap,
} from "../components/SourceDiscoveryPanel";

type RunProgressSourcePanelProps = {
  readonly sources: ReadonlyMap<string, DiscoveredSource>;
  readonly gaps: readonly KnowledgeGap[];
};

export function RunProgressSourcePanel({ sources, gaps }: RunProgressSourcePanelProps) {
  if (sources.size === 0 && gaps.length === 0) return null;
  return (
    <div className="fade-in mb-6 overflow-hidden rounded-lg border border-white/5 bg-white/[0.02] shadow-[var(--shadow-paper)]">
      <SourceDiscoveryPanel
        sources={Array.from(sources.values()).sort(
          (left, right) => right.firstSeenAt - left.firstSeenAt,
        )}
        gaps={[...gaps]}
      />
    </div>
  );
}
