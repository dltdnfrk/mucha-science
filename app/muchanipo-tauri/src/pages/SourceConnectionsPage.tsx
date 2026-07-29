import { useState } from "react";
import { FolioSection, ResearchMasthead, RuleButton } from "../components/ai-scientist/AiScientistPrimitives";
import { SOURCE_ACCESS_KINDS } from "../lib/sourceConnections";
import type { SourceAccessKind } from "../lib/sourceConnections";
import type { SourceConnectionsState } from "../hooks/useSourceConnections";
import { SourceConnectionRow } from "./SourceConnectionRow";

type SourceDraft = {
  readonly access: SourceAccessKind;
  readonly description: string;
  readonly name: string;
  readonly url: string;
};

type SourceFormError = {
  readonly field?: "name" | "url";
  readonly message: string;
};

const emptyDraft: SourceDraft = { name: "", url: "", description: "", access: "open" };
const sourceErrorIds = { name: "source-name-error", url: "source-url-error" } as const;

interface SourceConnectionsPageProps {
  readonly compact?: boolean;
  readonly sourceConnections: SourceConnectionsState;
}

export function SourceConnectionsPage({
  compact = false,
  sourceConnections,
}: SourceConnectionsPageProps) {
  const {
    addSource,
    connectedSources,
    hasSessionCredential,
    saveSessionCredential,
    setSourceStatus,
    sources,
  } = sourceConnections;
  const [draft, setDraft] = useState<SourceDraft>(emptyDraft);
  const [formError, setFormError] = useState<SourceFormError>();

  const addCustomSource = () => {
    const validationError = validateDraft(draft);
    if (validationError) {
      setFormError(validationError);
      return;
    }
    try {
      addSource({ ...draft, id: nextSourceId(draft.name, sources) });
      setDraft(emptyDraft);
      setFormError(undefined);
    } catch (error) {
      if (error instanceof Error) {
        setFormError({ message: "출처를 추가하지 못했습니다. 이름과 주소를 다시 확인하세요." });
        return;
      }
      throw error;
    }
  };
  const formErrorId = formError?.field ? sourceErrorIds[formError.field] : undefined;

  const content = (
    <>
      <header className="ms-sources__intro">
        <h1 id="source-connections-heading">연구 출처</h1>
        <p>검색에 사용할 학술 데이터베이스를 선택하세요. API 키는 현재 세션에만 유지됩니다.</p>
        <p className="ms-sources__summary" role="status" aria-live="polite">{connectedSources.length}개 사용 중</p>
      </header>

      <FolioSection
        description="사용할 출처와 연결 상태를 관리합니다. 여기의 상태는 검색 결과가 아니라 실행 전 설정입니다."
        title="기본 출처"
        variant="evidence"
      >
        <div className="ms-source-list">
          {sources.map((source) => (
            <SourceConnectionRow
              hasSessionCredential={hasSessionCredential}
              key={source.id}
              onSaveCredential={saveSessionCredential}
              onSetStatus={setSourceStatus}
              source={source}
            />
          ))}
        </div>
      </FolioSection>

      <FolioSection
        description="출처 정보만 저장합니다. API 키나 비밀값은 여기에 저장하지 않습니다."
        title="직접 추가"
      >
        <form className="ms-source-form" onSubmit={(event) => { event.preventDefault(); addCustomSource(); }}>
          <div className="ms-source-form__grid">
            <label>출처 이름<input aria-describedby={formError?.field === "name" ? sourceErrorIds.name : undefined} aria-invalid={formError?.field === "name" ? "true" : undefined} onChange={(event) => setDraft({ ...draft, name: event.target.value })} value={draft.name} /></label>
            <label>접근 방식<select onChange={(event) => setDraft({ ...draft, access: sourceAccessKind(event.target.value) })} value={draft.access}>{SOURCE_ACCESS_KINDS.map((kind) => <option key={kind} value={kind}>{accessLabel(kind)}</option>)}</select></label>
          </div>
          <label>주소<input aria-describedby={formError?.field === "url" ? sourceErrorIds.url : undefined} aria-invalid={formError?.field === "url" ? "true" : undefined} inputMode="url" onChange={(event) => setDraft({ ...draft, url: event.target.value })} placeholder="https://example.org/api" value={draft.url} /></label>
          <label>설명 <span>선택</span><textarea onChange={(event) => setDraft({ ...draft, description: event.target.value })} value={draft.description} /></label>
          {formError ? <p className="ms-source-form__error" id={formErrorId} role="alert">{formError.message}</p> : null}
          <RuleButton type="submit" variant="primary">출처 추가</RuleButton>
        </form>
      </FolioSection>
    </>
  );

  if (compact) {
    return (
      <div className="ms-sources ms-sources--compact" aria-labelledby="source-connections-heading">
        {content}
      </div>
    );
  }

  return (
    <>
      <ResearchMasthead
        cycleLabel="데이터 출처"
        protocolLabel="문헌·데이터 API"
        utility={<a className="ms-text-link" href="#/scientific">연구로 돌아가기</a>}
      />
      <main className="ms-sources" aria-labelledby="source-connections-heading">
        {content}
      </main>
    </>
  );
}

function validateDraft(draft: SourceDraft): SourceFormError | undefined {
  if (!draft.name.trim()) return { field: "name", message: "출처 이름을 입력하세요." };
  if (!draft.url.trim()) return { field: "url", message: "출처 주소를 입력하세요." };
  try {
    const url = new URL(draft.url);
    return url.protocol === "http:" || url.protocol === "https:"
      ? undefined
      : { field: "url", message: "http 또는 https 주소를 입력하세요." };
  } catch (error) {
    if (error instanceof TypeError) return { field: "url", message: "올바른 주소 형식이 아닙니다." };
    throw error;
  }
}

function nextSourceId(name: string, sources: readonly { readonly id: string }[]): string {
  const base = name.trim().toLowerCase().replaceAll(/[^a-z0-9]+/g, "-").replaceAll(/(^-|-$)/g, "") || "custom-source";
  let candidate = base;
  let suffix = 2;
  while (sources.some((source) => source.id === candidate)) {
    candidate = `${base}-${suffix}`;
    suffix += 1;
  }
  return candidate;
}

function sourceAccessKind(value: string): SourceAccessKind {
  return SOURCE_ACCESS_KINDS.find((kind) => kind === value) ?? "open";
}

function accessLabel(kind: SourceAccessKind): string {
  if (kind === "open") return "공개";
  if (kind === "api-key") return "API 키";
  return "사용자 설정";
}
