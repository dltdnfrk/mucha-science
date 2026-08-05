import { useMemo } from "react";
import {
  buildRunTimeline,
  type RunTimelineStage,
} from "../../lib/runTimeline";
import { ProcessDisclosure } from "./ResearchChatPrimitives";

export function RunTimeline({
  artifactIds,
  progress,
}: {
  readonly artifactIds: readonly string[];
  readonly progress: readonly string[];
}) {
  const timeline = useMemo(
    () => buildRunTimeline(progress, artifactIds),
    [artifactIds, progress],
  );
  const startedStages = timeline.stages.filter((stage) => stage.status === "completed");

  return (
    <div className="ms-run-timeline">
      <ol className="ms-run-timeline__stages">
        {timeline.stages.map((stage) => (
          <RunTimelineStageRow
            artifactCount={stage.id === "report" ? artifactIds.length : undefined}
            key={stage.id}
            stage={stage}
          />
        ))}
      </ol>
      {startedStages.length === 0 ? (
        <p>파이프라인 로그를 기다리고 있습니다.</p>
      ) : null}
      <ProcessDisclosure
        className="ms-run-timeline__raw"
        summary="원시 실행 이벤트"
        title="전체 진행 로그"
      >
        <ol className="ms-activity-log">
          {timeline.rawEvents.map((event, index) => (
            <li key={`${event}-${index}`}>
              <span className="ms-activity-log__marker" aria-hidden="true" />
              <span>{event}</span>
            </li>
          ))}
        </ol>
      </ProcessDisclosure>
    </div>
  );
}

function RunTimelineStageRow({
  artifactCount,
  stage,
}: {
  readonly artifactCount?: number;
  readonly stage: RunTimelineStage;
}) {
  return (
    <li
      className={`ms-run-timeline__stage ms-run-timeline__stage--${stage.status}`}
      data-stage={stage.id}
    >
      <span className="ms-run-timeline__dot" aria-hidden="true" />
      <div className="ms-run-timeline__copy">
        <strong className="ms-run-timeline__label">{stage.label}</strong>
        {stage.summary ? (
          <span className="ms-run-timeline__summary">
            {stage.summary}
            {artifactCount !== undefined && artifactCount > 0
              ? ` · 산출물 ${artifactCount}건`
              : null}
          </span>
        ) : null}
        {stage.keyEvents.length > 1 ? (
          <ul className="ms-run-timeline__events">
            {stage.keyEvents.slice(1).map((event, index) => (
              <li key={`${event}-${index}`}>{event}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  );
}
