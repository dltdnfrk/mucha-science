import type {
  PipelineCancellationAcknowledgement,
  PipelineMode,
  PipelineRuntimeStatus,
  ResearchDepth,
} from "./pipelineExecutionClient";
import type { PipelineLaunchReceipt } from "./researchExecution";
import type { BackendAction, BackendEvent } from "./tauriClient";
import {
  parsePipelineCancellation,
  parsePipelineLaunchReceipt,
  parsePipelineRuntimeStatus,
  parseWebPipelineMessage,
  toWebBackendEvent,
  WEB_PIPELINE_PROTOCOL,
  WebPipelineProtocolError,
} from "./webPipelineProtocol";


type WebCommandParser<TResult> = (
  message: Record<string, unknown>,
) => TResult;

export class WebPipelineConnectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WebPipelineConnectionError";
  }
}

export function startWebPipeline(
  topic: string,
  pipeline: PipelineMode,
  depth: ResearchDepth,
  environment: Readonly<Record<string, string>>,
  appRunId: string,
): Promise<PipelineLaunchReceipt> {
  return requestWebCommand({
    protocol: WEB_PIPELINE_PROTOCOL,
    type: "run.start",
    run_id: appRunId,
    topic,
    pipeline,
    depth,
    environment,
  }, parsePipelineLaunchReceipt);
}

export function cancelWebPipeline(
  appRunId: string,
  generation: number,
): Promise<PipelineCancellationAcknowledgement> {
  return requestWebCommand({
    protocol: WEB_PIPELINE_PROTOCOL,
    type: "run.cancel",
    run_id: appRunId,
    generation,
  }, parsePipelineCancellation);
}

export async function sendWebPipelineAction(
  appRunId: string,
  generation: number,
  action: BackendAction,
): Promise<void> {
  await requestWebCommand({
    protocol: WEB_PIPELINE_PROTOCOL,
    type: "run.action",
    run_id: appRunId,
    generation,
    action,
  }, (message) => {
    if (
      message.protocol !== WEB_PIPELINE_PROTOCOL
      || message.type !== "run.action.accepted"
      || message.run_id !== appRunId
      || message.generation !== generation
    ) {
      throw new WebPipelineProtocolError("웹 연구 응답 전달 확인이 올바르지 않습니다.");
    }
  });
}

export function getWebPipelineRuntimeStatus(): Promise<PipelineRuntimeStatus> {
  return requestWebCommand({
    protocol: WEB_PIPELINE_PROTOCOL,
    type: "runtime.status",
  }, parsePipelineRuntimeStatus);
}

export function subscribeWebPipeline(
  appRunId: string,
  handler: (event: BackendEvent) => void,
): Promise<() => void> {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(webPipelineEndpoint());
    let opened = false;
    let detached = false;
    socket.onopen = () => {
      opened = true;
      socket.send(JSON.stringify({
        protocol: WEB_PIPELINE_PROTOCOL,
        type: "run.subscribe",
        run_id: appRunId,
        after_sequence: -1,
      }));
      resolve(() => {
        detached = true;
        socket.close();
      });
    };
    socket.onmessage = (event) => {
      try {
        const message = parseWebPipelineMessage(event.data);
        const backendEvent = toWebBackendEvent(message);
        if (backendEvent) handler(backendEvent);
      } catch (error) {
        if (error instanceof WebPipelineProtocolError) {
          handler({
            event: "pipeline_error",
            app_run_id: appRunId,
            message: error.message,
          });
          return;
        }
        throw error;
      }
    };
    socket.onerror = () => {
      if (!opened) {
        reject(new WebPipelineConnectionError(
          "웹 연구 서버에 연결하지 못했습니다. muchanipo-web 실행 상태를 확인하세요.",
        ));
      }
    };
    socket.onclose = () => {
      if (!opened && !detached) {
        reject(new WebPipelineConnectionError(
          "웹 연구 서버 연결이 시작되기 전에 종료되었습니다.",
        ));
      }
    };
  });
}

function requestWebCommand<TResult>(
  payload: Readonly<Record<string, unknown>>,
  parser: WebCommandParser<TResult>,
): Promise<TResult> {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(webPipelineEndpoint());
    let settled = false;
    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      socket.close();
      reject(error);
    };
    socket.onopen = () => {
      socket.send(JSON.stringify(payload));
    };
    socket.onmessage = (event) => {
      try {
        const result = parser(parseWebPipelineMessage(event.data));
        if (settled) return;
        settled = true;
        socket.close();
        resolve(result);
      } catch (error) {
        if (error instanceof Error) {
          fail(error);
          return;
        }
        throw error;
      }
    };
    socket.onerror = () => {
      fail(new WebPipelineConnectionError(
        "웹 연구 서버에 연결하지 못했습니다. muchanipo-web 실행 상태를 확인하세요.",
      ));
    };
    socket.onclose = () => {
      if (!settled) {
        fail(new WebPipelineConnectionError("웹 연구 서버가 응답 없이 연결을 종료했습니다."));
      }
    };
  });
}

function webPipelineEndpoint(): string {
  const configured = import.meta.env.VITE_MUCHA_SCIENCE_WS_URL?.trim();
  if (configured) return configured;
  const local = window.location.hostname === "127.0.0.1"
    || window.location.hostname === "localhost";
  if (local) return `ws://${window.location.hostname}:8765`;
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}/ws`;
}
