import { useState } from "react";
import { initialScientificState } from "../lib/scientificReducer";
import { supportsScientificAction } from "../lib/tauri";
import type {
  ScientificActionPayloadMap,
} from "../lib/types";
import { ScientificPageView } from "./ScientificPageView";
import {
  VALIDATION_DETAIL_ACTIONS,
} from "./scientificPageProtocol";
import { useScientificProtocolRuntime } from "./useScientificProtocolRuntime";

interface ScientificPageProps {
  readonly isBrowserPreview: boolean;
}

export default function ScientificPage({
  isBrowserPreview,
}: ScientificPageProps) {
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState<string>();
  const {
    abortPayload,
    abortPayloadRef,
    actionError,
    capabilities,
    clientInstanceId,
    committedMessageIds,
    creationIdempotencyKey,
    cycleId,
    dispatch,
    errors,
    pendingStartMessageIds,
    requestOrdinal,
    responses,
    retiredCycleIds,
    send,
    setAbortPayload,
    setActionError,
    setStartRequested,
    startRequested,
    startRequestInFlight,
    state,
    stateRef,
  } = useScientificProtocolRuntime();

  const startCycle = () => {
    setActionError("검증 화면은 저장된 사이클의 상세 및 재실행만 제공합니다.");
  };

  const recoveryAction = state.recovery?.kind === "snapshot" ? "cycle.resume" : "cycle.replay";
  const recoveryUnavailableReason =
    !state.recovery
      ? "서버의 복구 요청이 없습니다."
      : !cycleId.current
        ? "서버가 사이클 ID를 발급할 때까지 기다리는 중입니다."
        : !supportsScientificAction(capabilities, recoveryAction)
          ? `서버가 ${recoveryAction} 작업을 제공하지 않았습니다.`
          : undefined;
  const abortUnavailableReason =
    !cycleId.current
      ? "서버가 사이클 ID를 발급할 때까지 기다리는 중입니다."
      : !supportsScientificAction(capabilities, "cycle.abort")
        ? "서버가 cycle.abort 작업을 제공하지 않았습니다."
        : !abortPayload ||
            abortPayload.cycleId !== cycleId.current ||
            abortPayload.revision !== state.revision ||
            abortPayload.payload.expected_revision !== state.revision
          ? "서버가 현재 사이클을 중단하는 데 필요한 메타데이터를 보내지 않았습니다."
          : undefined;
  const exportUnavailableReason =
    !cycleId.current
      ? "서버가 사이클 ID를 발급할 때까지 기다리는 중입니다."
      : !supportsScientificAction(capabilities, "export.create")
        ? "서버가 export.create 작업을 제공하지 않았습니다."
        : !state.export_allowed
          ? "서버가 내보내기 조건 충족을 아직 보고하지 않았습니다."
          : undefined;
  const terminalCycle = state.events.some(
    (event) => event.type === "cycle.completed" || event.type === "cycle.aborted",
  );
  const resetUnavailableReason =
    !cycleId.current
      ? "초기화할 활성 사이클이 없습니다."
      : !terminalCycle
        ? "새 사이클을 시작하려면 서버가 완료 또는 중단 상태를 먼저 보고해야 합니다."
        : undefined;

  const resetCycle = () => {
    if (resetUnavailableReason) return;
    const activeCycleId = cycleId.current;
    if (!activeCycleId) return;
    retiredCycleIds.current.add(activeCycleId);
    cycleId.current = undefined;
    pendingStartMessageIds.current.clear();
    startRequestInFlight.current = false;
    creationIdempotencyKey.current = undefined;
    abortPayloadRef.current = undefined;
    committedMessageIds.current.clear();
    stateRef.current = initialScientificState;
    setAbortPayload(undefined);
    setActionError(undefined);
    setQuestion("");
    setSubmittedQuestion(undefined);
    setStartRequested(false);
    dispatch({ resetScientificPage: true });
  };

  const recoverCycle = () => {
    if (!state.recovery || recoveryUnavailableReason) {
      return;
    }
    const checkpoint = state.checkpoint;
    if (!checkpoint || checkpoint.cycle_id !== cycleId.current) {
      setActionError("복구하려면 현재 사이클과 일치하는 서버 체크포인트가 필요합니다.");
      return;
    }
    const ordinal = ++requestOrdinal.current;
    void send(recoveryAction, recoveryAction === "cycle.resume"
      ? {
        client_instance_id: clientInstanceId.current,
        request_ordinal: ordinal,
        cycle_id: cycleId.current,
        cursor: checkpoint,
        projection: "scientific-cycle.v1",
      }
      : {
        client_instance_id: clientInstanceId.current,
        request_ordinal: ordinal,
        cursor: checkpoint,
        max_events: 128,
      });
  };

  const abortCycle = () => {
    if (abortPayloadRef.current && !abortUnavailableReason) {
      void send("cycle.abort", abortPayloadRef.current.payload);
    }
  };

  return (
    <ScientificPageView
      key={submittedQuestion ?? "empty"}
      actionError={actionError}
      abortUnavailableReason={abortUnavailableReason}
      errors={errors}
      exportUnavailableReason={exportUnavailableReason}
      hasActiveCycle={Boolean(cycleId.current || startRequested || state.events.length > 0)}
      isBrowserPreview={isBrowserPreview}
      onAbort={abortCycle}
      onExport={() => {
        if (!exportUnavailableReason) {
          void send("export.create", {
            expected_revision: state.revision,
            format: "scientific-export.v1",
            artifact_ids: [],
            report_body_id: null,
            redaction_profile_id: null,
            external_reference_ids: [],
          });
        }
      }}
      onQuestionChange={setQuestion}
      onRecover={recoverCycle}
      onReset={resetCycle}
      onStart={startCycle}
      onWorkflowAction={(name, payload) => {
        void send(name, {
          ...payload,
          ...(name === "export.create" && payload.expected_revision === undefined
            ? {
                expected_revision: state.revision,
                format: "scientific-export.v1",
                artifact_ids: [],
                report_body_id: null,
                redaction_profile_id: null,
                external_reference_ids: [],
              }
            : {}),
        } as ScientificActionPayloadMap[typeof name]);
      }}
      question={question}
      recoveryUnavailableReason={recoveryUnavailableReason}
      resetUnavailableReason={resetUnavailableReason}
      responses={responses}
      startUnavailableReason={
        "새 연구 실행은 연구 대화에서만 시작할 수 있습니다."
      }
      state={state}
      startRequested={startRequested}
      submittedQuestion={submittedQuestion}
      workflowActions={VALIDATION_DETAIL_ACTIONS.filter((name) =>
        supportsScientificAction(capabilities, name))}
      workflowUnavailableReason={
        !cycleId.current
          ? "서버가 사이클 ID를 발급할 때까지 기다리는 중입니다."
          : state.integrity_latched || state.recovery
            ? "워크플로 작업을 보내기 전에 서버 기준 상태를 재실행하거나 이어서 불러오세요."
            : terminalCycle
              ? "서버가 이 사이클의 종료를 보고했습니다."
              : undefined
      }
    />
  );
}
