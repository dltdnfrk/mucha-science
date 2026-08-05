import { useMemo, useState } from "react";
import { SafeReportMarkdown } from "../SafeReportMarkdown";
import {
  artifactKindLabel,
  getArtifact,
  listArtifacts,
  type ResearchArtifact,
} from "../../lib/researchArtifactLibrary";

export function LibraryPanel() {
  const artifacts = useMemo(() => listArtifacts(), []);
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const selected = selectedId === undefined ? undefined : getArtifact(selectedId);

  if (selected) {
    return (
      <ArtifactViewer
        artifact={selected}
        onBack={() => setSelectedId(undefined)}
      />
    );
  }

  if (artifacts.length === 0) {
    return (
      <section className="ms-library" data-library-empty>
        <p className="ms-library__empty">
          저장된 산출물이 없습니다. 연구 실행이 완료되면 보고서·출처 검토·품질 요약이 여기에 쌓입니다.
        </p>
      </section>
    );
  }

  return (
    <section className="ms-library" aria-label="연구 산출물 라이브러리">
      <div className="ms-library__grid">
        {artifacts.map((artifact) => (
          <button
            className="ms-library__card"
            key={artifact.id}
            onClick={() => setSelectedId(artifact.id)}
            type="button"
          >
            <span className="ms-library__kind">{artifactKindLabel(artifact.kind)}</span>
            <strong className="ms-library__title">{artifact.title}</strong>
            <span className="ms-library__session">{artifact.sessionTitle}</span>
            <time className="ms-library__time" dateTime={new Date(artifact.committedAt).toISOString()}>
              {new Date(artifact.committedAt).toLocaleString()}
            </time>
          </button>
        ))}
      </div>
    </section>
  );
}

function ArtifactViewer({
  artifact,
  onBack,
}: {
  readonly artifact: ResearchArtifact;
  readonly onBack: () => void;
}) {
  return (
    <section className="ms-library" data-library-viewer>
      <div className="ms-library__viewer-head">
        <button className="ms-text-link" onClick={onBack} type="button">← 라이브러리로</button>
        <h2 className="ms-library__viewer-title">
          {artifactKindLabel(artifact.kind)} · {artifact.title}
        </h2>
        <span className="ms-library__viewer-meta">
          {artifact.sessionTitle} · v{artifact.version}
        </span>
      </div>
      <div className="ms-library__viewer-body">
        {artifact.contentType === "markdown" ? (
          <div className="ms-report-markdown">
            <SafeReportMarkdown markdown={artifact.content} />
          </div>
        ) : (
          <pre className="ms-library__pre">{artifact.content}</pre>
        )}
      </div>
    </section>
  );
}
