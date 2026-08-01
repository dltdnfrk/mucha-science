import { useState } from "react";
import { RuleButton } from "../components/ai-scientist/AiScientistPrimitives";
import type { SourceConnection } from "../lib/sourceConnections";

interface SourceConnectionRowProps {
  readonly hasSessionCredential: (sourceId: string) => boolean;
  readonly onSaveCredential: (sourceId: string, credential: string) => boolean;
  readonly onSetStatus: (sourceId: string, status: "connected" | "disconnected") => void;
  readonly source: SourceConnection;
}

export function SourceConnectionRow({
  hasSessionCredential,
  onSaveCredential,
  onSetStatus,
  source,
}: SourceConnectionRowProps) {
  const [credentialError, setCredentialError] = useState<string>();
  const isApiKey = source.access.kind === "api-key";
  const isEnabled = source.status === "connected";
  const status = isEnabled
    ? isApiKey ? "연결됨 · 이번 세션" : "사용 설정됨"
    : isApiKey ? "연결 안 됨" : "사용 해제됨";

  const toggleOpenSource = () => {
    onSetStatus(source.id, isEnabled ? "disconnected" : "connected");
  };

  const connect = (form: HTMLFormElement) => {
    const credential = new FormData(form).get("credential");
    if (typeof credential !== "string" || !credential.trim()) {
      setCredentialError("연결하려면 API 키를 입력하세요.");
      return;
    }
    if (!onSaveCredential(source.id, credential)) {
      setCredentialError("이 브라우저에서는 세션 저장소를 사용할 수 없습니다.");
      return;
    }
    setCredentialError(undefined);
    onSetStatus(source.id, "connected");
    form.reset();
  };

  const disconnect = () => {
    onSaveCredential(source.id, "");
    setCredentialError(undefined);
    onSetStatus(source.id, "disconnected");
  };

  return (
    <article className="ms-source-row">
      <div className="ms-source-row__identity">
        <p>{source.access.kind === "api-key" ? "API 키" : source.access.kind === "open" ? "공개" : "사용자 설정"}</p>
        <h3>{source.name}</h3>
        <a className="ms-text-link" href={source.url} rel="noreferrer" target="_blank">{source.url}</a>
        {source.description ? <span>{source.description}</span> : null}
      </div>
      <div className="ms-source-row__state">
        <strong>{status}</strong>
        {isApiKey && hasSessionCredential(source.id) ? <span>키가 이번 앱 세션에만 유지됩니다.</span> : null}
      </div>
      <div className="ms-source-row__action">
        {isApiKey && !isEnabled ? (
          <form onSubmit={(event) => { event.preventDefault(); connect(event.currentTarget); }}>
            <label htmlFor={`credential-${source.id}`}>API 키</label>
            <input id={`credential-${source.id}`} name="credential" type="password" autoComplete="off" />
            <RuleButton type="submit" variant="primary">연결</RuleButton>
            <p>키는 이번 앱 세션에만 유지됩니다.</p>
            {credentialError ? <p role="alert">{credentialError}</p> : null}
          </form>
        ) : isApiKey ? (
          <RuleButton onClick={disconnect} variant="neutral">연결 해제</RuleButton>
        ) : (
          <RuleButton onClick={toggleOpenSource} variant={isEnabled ? "neutral" : "primary"}>
            {isEnabled ? "사용 해제" : "사용 설정"}
          </RuleButton>
        )}
      </div>
    </article>
  );
}
