import { useState } from "react";
import type { PersonaPoolSummary } from "../components/PersonaPoolCard";
import type { CouncilActivity } from "./runProgressInteractionTypes";
import type { TokenCard } from "./runProgressTypes";

export function useRunProgressCouncilState() {
  const [councilRound, setCouncilRound] = useState(0);
  const [tokenCards, setTokenCards] = useState<TokenCard[]>([]);
  const [councilActivity, setCouncilActivity] = useState<CouncilActivity[]>([]);
  const [councilPersonas, setCouncilPersonas] = useState<string[]>([]);
  const [personaPool, setPersonaPool] = useState<PersonaPoolSummary | null>(null);

  const resetCouncilArtifacts = () => {
    setCouncilRound(0);
    setTokenCards([]);
    setCouncilActivity([]);
    setCouncilPersonas([]);
    setPersonaPool(null);
  };

  return {
    councilRound, setCouncilRound, tokenCards, setTokenCards,
    councilActivity, setCouncilActivity, councilPersonas, setCouncilPersonas,
    personaPool, setPersonaPool, resetCouncilArtifacts,
  };
}
