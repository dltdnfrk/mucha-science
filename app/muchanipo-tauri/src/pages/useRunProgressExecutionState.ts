import { useEffect, useRef, useState } from "react";
import type { RuntimeEvidence, StudioProvenance } from "./runProgressInteractionTypes";
import { initialStageState } from "./runProgressStages";
import type { Stage, StageState } from "./runProgressTypes";

export function useRunProgressExecutionState() {
  const [stages, setStages] = useState<Record<Stage, StageState>>(() => initialStageState());
  const [topic, setTopic] = useState("");
  const [studioProvenance, setStudioProvenance] = useState<StudioProvenance | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const runErrorRef = useRef<string | null>(null);
  const [runWarnings, setRunWarnings] = useState<string[]>([]);
  const [reportPreview, setReportPreview] = useState("");
  const [finalReport, setFinalReport] = useState("");
  const [runtimeEvidence, setRuntimeEvidence] = useState<RuntimeEvidence | null>(null);
  const [hasReceivedHeartbeat, setHasReceivedHeartbeat] = useState(false);
  const [aborting, setAborting] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const chunkKeysRef = useRef<Set<string>>(new Set());
  const finalReportReceivedRef = useRef(false);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const resetExecutionArtifacts = () => {
    chunkKeysRef.current.clear();
    finalReportReceivedRef.current = false;
    setStages(initialStageState());
    setReportPreview("");
    setFinalReport("");
    setRuntimeEvidence(null);
    setHasReceivedHeartbeat(false);
  };

  return {
    stages, setStages, topic, setTopic, studioProvenance, setStudioProvenance,
    runError, setRunError, runErrorRef, runWarnings, setRunWarnings,
    reportPreview, setReportPreview, finalReport, setFinalReport,
    runtimeEvidence, setRuntimeEvidence, hasReceivedHeartbeat, setHasReceivedHeartbeat,
    aborting, setAborting, now, chunkKeysRef, finalReportReceivedRef,
    resetExecutionArtifacts,
  };
}
