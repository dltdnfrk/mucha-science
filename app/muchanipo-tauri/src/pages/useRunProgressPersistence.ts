import { useEffect, type Dispatch, type SetStateAction } from "react";
import type { DiscoveredSource, KnowledgeGap } from "../components/SourceDiscoveryPanel";
import { sanitizeMarkdownExternalReferences } from "../lib/safeExternalUrl";
import type { StudioProvenance } from "./runProgressInteractionTypes";
import { persistRunValue, readRunIdentity } from "./runProgressStorage";

type PersistenceProps = {
  readonly runId?: string;
  readonly sources: Map<string, DiscoveredSource>;
  readonly gaps: KnowledgeGap[];
  readonly reportPreview: string;
  readonly setTopic: Dispatch<SetStateAction<string>>;
  readonly setStudioProvenance: Dispatch<SetStateAction<StudioProvenance | null>>;
};

export function useRunProgressPersistence(props: PersistenceProps): void {
  useEffect(() => {
    if (!props.runId) return;
    const identity = readRunIdentity(props.runId);
    props.setTopic(identity.topic);
    if (identity.provenance) props.setStudioProvenance(identity.provenance);
  }, [props.runId]);

  useEffect(() => {
    if (!props.runId) return;
    persistRunValue(
      props.runId,
      "sources",
      JSON.stringify(Array.from(props.sources.entries())),
    );
  }, [props.runId, props.sources]);

  useEffect(() => {
    if (!props.runId) return;
    persistRunValue(props.runId, "gaps", JSON.stringify(props.gaps));
  }, [props.gaps, props.runId]);

  useEffect(() => {
    if (!props.runId || !props.reportPreview) return;
    persistRunValue(
      props.runId,
      "report_pending",
      sanitizeMarkdownExternalReferences(props.reportPreview),
    );
  }, [props.reportPreview, props.runId]);
}
