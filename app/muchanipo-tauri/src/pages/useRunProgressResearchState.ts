import { useState } from "react";
import type { DiscoveredSource, KnowledgeGap } from "../components/SourceDiscoveryPanel";
import { readStoredKnowledgeGaps, readStoredSources } from "./runProgressStorage";
import { EMPTY_RESEARCH_CONTRACT } from "./runProgressTypes";
import type { ResearchActivity, ResearchContractState } from "./runProgressTypes";

export function useRunProgressResearchState(runId?: string) {
  const [researchActivity, setResearchActivity] = useState<ResearchActivity[]>([]);
  const [researchContract, setResearchContract] =
    useState<ResearchContractState>(EMPTY_RESEARCH_CONTRACT);
  const [discoveredSources, setDiscoveredSources] =
    useState<Map<string, DiscoveredSource>>(() => readStoredSources(runId));
  const [knowledgeGaps, setKnowledgeGaps] =
    useState<KnowledgeGap[]>(() => readStoredKnowledgeGaps(runId));

  const resetResearchArtifacts = () => {
    setResearchActivity([]);
    setDiscoveredSources(new Map());
    setKnowledgeGaps([]);
  };

  return {
    researchActivity, setResearchActivity, researchContract, setResearchContract,
    discoveredSources, setDiscoveredSources, knowledgeGaps, setKnowledgeGaps,
    resetResearchArtifacts,
  };
}
