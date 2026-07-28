import type {
  ResearchActivity,
  ResearchActivityProjection,
  ResearchCounterSearch,
} from "./researchActivity";

export function reduceResearchActivity(
  current: ResearchActivity,
  projections: readonly ResearchActivityProjection[],
): ResearchActivity {
  return projections.reduce(reduceProjection, current);
}

function reduceProjection(
  current: ResearchActivity,
  projection: ResearchActivityProjection,
): ResearchActivity {
  switch (projection.kind) {
    case "provider":
      return { ...current, providers: upsert(current.providers, projection, "attemptId") };
    case "route":
      return { ...current, routes: upsert(current.routes, projection, "routeId") };
    case "evidence":
      return { ...current, evidence: upsert(current.evidence, projection, "sourceId") };
    case "claim":
      return { ...current, claims: upsert(current.claims, projection, "claimId") };
    case "quality":
      return { ...current, quality: projection };
    case "counter_started":
      return {
        ...current,
        counterSearch: {
          batchSize: projection.batchSize,
          evaluated: 0,
          executed: 0,
          noNovelty: false,
          status: "running",
        },
      };
    case "counter_executed":
      return updateCounter(current, "executed");
    case "counter_evaluated":
      return updateCounter(current, "evaluated");
    case "counter_completed": {
      const counter = current.counterSearch ?? runningCounter();
      return {
        ...current,
        counterSearch: {
          ...counter,
          noNovelty: projection.noNovelty,
          status: "completed",
          stopReason: projection.stopReason,
        },
      };
    }
    case "cancellation_acknowledged":
      return { ...current, cancellationAcknowledged: true };
  }
}

function updateCounter(
  current: ResearchActivity,
  field: "evaluated" | "executed",
): ResearchActivity {
  const counter = current.counterSearch ?? runningCounter();
  return { ...current, counterSearch: { ...counter, [field]: counter[field] + 1 } };
}

function runningCounter(): ResearchCounterSearch {
  return { batchSize: 0, evaluated: 0, executed: 0, noNovelty: false, status: "running" };
}

function upsert<
  Item extends Readonly<Record<Key, string>>,
  Key extends keyof Item,
>(items: readonly Item[], next: Item, key: Key): readonly Item[] {
  return [...items.filter((item) => item[key] !== next[key]), next];
}
