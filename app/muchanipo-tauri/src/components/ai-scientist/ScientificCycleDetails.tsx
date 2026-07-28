import { useState } from "react";
import type { ScientificState } from "../../lib/scientificReducer";
import type { ScientificActionName } from "../../lib/types";
import type { ScientificEnvelope } from "../../lib/tauri";
import { FolioSection, RuleButton } from "./AiScientistPrimitives";

const RESPONSIBILITY_GATES = [
  "질문과 범위는 운영자가 검토합니다.",
  "가설의 주장에는 운영자의 책임이 명시됩니다.",
  "실험 지시는 이 앱 밖의 실행 환경으로 인계됩니다.",
  "외부 결과에는 사람이 제공한 출처와 책임이 연결됩니다.",
  "검증과 최종 판정은 사람이 내립니다.",
  "내보내기는 검토용 패키지이며 기관의 승인이 아닙니다.",
] as const;

const VALIDATION_DIMENSIONS = [
  { key: "empirical", label: "경험적 타당성" },
  { key: "methodological", label: "방법론적 타당성" },
  { key: "reproducibility", label: "재현 가능성" },
  { key: "ethical", label: "윤리성" },
] as const;

interface ScientificCycleDetailsProps {
  readonly actionError?: string;
  readonly errors: readonly ScientificEnvelope[];
  readonly onWorkflowAction: (
    name: ScientificActionName,
    payload: Record<string, unknown>,
  ) => void;
  readonly responses: readonly ScientificEnvelope[];
  readonly state: ScientificState;
  readonly workflowActions: readonly ScientificActionName[];
  readonly workflowUnavailableReason?: string;
}

export function ScientificCycleDetails({
  actionError,
  errors,
  onWorkflowAction,
  responses,
  state,
  workflowActions,
  workflowUnavailableReason,
}: ScientificCycleDetailsProps) {
  const [selectedAction, setSelectedAction] =
    useState<ScientificActionName>("cycle.continue");
  const [actionPayload, setActionPayload] = useState("{}");
  const [payloadError, setPayloadError] = useState<string>();
  const validation = state.validation.at(-1);

  const submitWorkflowAction = () => {
    try {
      const parsed: unknown = JSON.parse(actionPayload);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        setPayloadError("작업 페이로드는 JSON 객체여야 합니다.");
        return;
      }
      setPayloadError(undefined);
      onWorkflowAction(selectedAction, parsed as Record<string, unknown>);
    } catch {
      setPayloadError("작업 페이로드에 올바른 JSON을 입력하세요.");
    }
  };

  return (
    <>
      <div className="ms-cycle-dual">
        <FolioSection
          description="여섯 단계 모두 사람의 책임 있는 판단이 필요합니다."
          kicker="책임"
          title="책임 확인 게이트"
        >
          <ol className="ms-responsibility-list">
            {RESPONSIBILITY_GATES.map((gate, index) => (
              <li key={gate}>
                <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                <span>{gate}</span>
              </li>
            ))}
          </ol>
        </FolioSection>
        <FolioSection
          description="V-레벨은 신뢰도 및 결과와 별개이며, 검증 상태는 서버가 보고합니다."
          kicker="평가"
          title="독립 검증"
          variant="evidence"
        >
          <dl className="ms-validation-list">
            {VALIDATION_DIMENSIONS.map((dimension) => (
              <div key={dimension.key}>
                <dt>{dimension.label}</dt>
                <dd>{validation?.[dimension.key] ?? "보고 없음"}</dd>
              </div>
            ))}
            <div><dt>V-레벨</dt><dd>{state.v_level ?? "보고 없음"}</dd></div>
            <div><dt>신뢰도</dt><dd>{state.confidence ?? "보고 없음"}</dd></div>
            <div><dt>결과</dt><dd>{state.outcome ?? "보고 없음"}</dd></div>
          </dl>
        </FolioSection>
      </div>

      <details className="ms-cycle-advanced" open={actionError ? true : undefined}>
        <summary>
          <span>고급 작업 및 진단</span>
          <small>서버 작업, 복구, 원시 메시지</small>
        </summary>
        <div className="ms-cycle-advanced__body">
          <div className="ms-cycle-dual">
            <FolioSection
              description="수명 주기의 적법성, 게이트, 참조, 리비전 검사는 서버가 결정합니다."
              kicker="서버 계약"
              title="서버가 결정하는 워크플로 작업"
            >
              <div className="ms-workflow-fields">
                <label htmlFor="ms-workflow-action">서버 제공 작업</label>
                <select
                  id="ms-workflow-action"
                  disabled={workflowActions.length === 0}
                  value={workflowActions.length === 0 ? "" : selectedAction}
                  onChange={(event) =>
                    setSelectedAction(event.target.value as ScientificActionName)}
                >
                  {workflowActions.length === 0
                    ? <option value="">서버가 제공한 작업 없음</option>
                    : null}
                  {workflowActions.map((name) =>
                    <option key={name} value={name}>{name}</option>)}
                </select>
                <label htmlFor="ms-workflow-payload">작업 페이로드</label>
                <textarea
                  id="ms-workflow-payload"
                  aria-describedby={payloadError ? "ms-workflow-payload-error" : undefined}
                  value={actionPayload}
                  onChange={(event) => {
                    setActionPayload(event.target.value);
                    setPayloadError(undefined);
                  }}
                />
                {payloadError
                  ? <p id="ms-workflow-payload-error" role="alert">{payloadError}</p>
                  : null}
                <RuleButton
                  aria-describedby="ms-workflow-status"
                  disabled={Boolean(workflowUnavailableReason) || workflowActions.length === 0}
                  onClick={submitWorkflowAction}
                  title={workflowUnavailableReason}
                >
                  서버 검증 작업 보내기
                </RuleButton>
                <p
                  id="ms-workflow-status"
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                >
                  {workflowUnavailableReason ?? "서버 검증 작업을 보낼 준비가 되었습니다."}
                </p>
                <p>
                  실제 실행은 앱 밖에서만 이루어집니다. 제출하는 결과는 이미 준비된 ID를
                  참조해야 하며, 이 클라이언트는 권한, 결과, 실제 작업을 직접 검증하지 않습니다.
                </p>
              </div>
            </FolioSection>
            <FolioSection
              description="이 앱은 작업을 준비하며, 실제 실행은 앱의 경계 밖에서 이루어집니다."
              kicker="외부 경계"
              title="외부 결과의 경계"
              variant="evidence"
            >
              <p className="ms-boundary-copy">
                이 클라이언트는 가설을 만들고 외부 실험에 넘길 작업을 묶습니다. 실제 작업을
                수행하거나 장비를 제어하지 않으며, 외부 결과를 스스로 검증하지 않습니다.
              </p>
            </FolioSection>
          </div>

          <div className="ms-cycle-dual">
            <FolioSection
              description={state.recovery
                ? `복구 필요: ${state.recovery.kind}, ${
                    state.recovery.kind === "replay"
                      ? `시퀀스 ${state.recovery.after_sequence} 이후`
                      : `리비전 ${state.recovery.at_revision} 시점`
                  }부터 다시 불러와야 합니다.`
                : "복구 요청이 없습니다."}
              kicker="복구"
              title="진단과 복구"
              variant="diagnostics"
            >
              <div className="ms-diagnostics">
                {state.diagnostics.length === 0 ? (
                  <p>진단 항목이 없습니다.</p>
                ) : (
                  <ul>
                    {state.diagnostics.map((diagnostic) => (
                      <li key={`${diagnostic.message_id}-${diagnostic.kind}-${diagnostic.detail}`}>
                        {diagnostic.kind}: {diagnostic.detail}
                      </li>
                    ))}
                  </ul>
                )}
                {actionError
                  ? <p className="ms-error-copy" role="alert">{actionError}</p>
                  : null}
              </div>
            </FolioSection>
            <FolioSection
              description="알 수 없는 서버 이벤트는 원시 프로토콜 데이터로 보존됩니다."
              kicker="프로토콜"
              title="원시 프로토콜의 한계"
              variant="diagnostics"
            >
              <div className="ms-diagnostics">
                <p>지원하지 않는 이벤트 {state.unsupported_events.length}건을 보존했습니다.</p>
                <p>원시 응답 {responses.length}건과 원시 오류 {errors.length}건을 보존했습니다.</p>
                <details>
                  <summary>원시 메시지 보기</summary>
                  <pre>{JSON.stringify({ responses, errors }, null, 2)}</pre>
                </details>
              </div>
            </FolioSection>
          </div>
        </div>
      </details>
    </>
  );
}
