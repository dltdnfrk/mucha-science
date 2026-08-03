import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  startWebPipeline,
  subscribeWebPipeline,
} from "./webPipelineClient";


class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly sent: string[] = [];
  closed = false;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  send(value: string): void {
    this.sent.push(value);
  }

  open(): void {
    this.onopen?.(new Event("open"));
  }

  message(value: unknown): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(value) }));
  }

  disconnect(): void {
    this.onclose?.(new Event("close") as CloseEvent);
  }
}


beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("window", {
    location: {
      host: "127.0.0.1:1420",
      hostname: "127.0.0.1",
      protocol: "http:",
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("web pipeline launch", () => {
  it("sends the browser run contract and returns its generation receipt", async () => {
    const result = startWebPipeline(
      "브라우저 연구 질문",
      "full",
      "deep",
      { MUCHANIPO_SOURCE_RESEARCH: "1" },
      "run_00000000000000000000000000000001",
    );
    const socket = FakeWebSocket.instances[0];
    if (!socket) throw new Error("websocket was not created");

    expect(socket.url).toBe("ws://127.0.0.1:8765/api/pipeline");
    socket.open();
    expect(JSON.parse(socket.sent[0] ?? "")).toEqual({
      protocol: "mucha-science.web.v1",
      type: "run.start",
      run_id: "run_00000000000000000000000000000001",
      topic: "브라우저 연구 질문",
      pipeline: "full",
      depth: "deep",
      environment: { MUCHANIPO_SOURCE_RESEARCH: "1" },
    });
    socket.message({
      protocol: "mucha-science.web.v1",
      type: "run.started",
      receipt: {
        app_run_id: "run_00000000000000000000000000000001",
        executable_digest: "managed-by-web-runtime",
        executable_path: "/python",
        generation: 1,
        identity: null,
        launch_nonce: "web-run",
        owner_boot_id: "web-runtime",
        phase: "running",
        reaped: false,
        reserved_at_unix_ms: 1,
        terminal_kind: null,
        termination_kill_sent: false,
        termination_observed: false,
      },
    });

    await expect(result).resolves.toMatchObject({
      app_run_id: "run_00000000000000000000000000000001",
      generation: 1,
      phase: "running",
    });
    expect(socket.closed).toBe(true);
  });
});

describe("web pipeline subscription", () => {
  it("replays browser events and detaches without a desktop event bridge", async () => {
    const received: unknown[] = [];
    const subscription = subscribeWebPipeline(
      "run_00000000000000000000000000000001",
      (event) => received.push(event),
    );
    const socket = FakeWebSocket.instances[0];
    if (!socket) throw new Error("websocket was not created");

    socket.open();
    const detach = await subscription;
    socket.message({
      event: "research_progress",
      app_run_id: "run_00000000000000000000000000000001",
      generation: 1,
      sequence: 3,
      status: "searching",
    });

    expect(received).toEqual([{
      event: "research_progress",
      app_run_id: "run_00000000000000000000000000000001",
      generation: 1,
      sequence: 3,
      status: "searching",
    }]);
    detach();
    expect(socket.closed).toBe(true);
  });

  it("turns an unexpected open-socket disconnect into a terminal pipeline error", async () => {
    const received: unknown[] = [];
    const subscription = subscribeWebPipeline(
      "run_00000000000000000000000000000001",
      (event) => received.push(event),
    );
    const socket = FakeWebSocket.instances[0];
    if (!socket) throw new Error("websocket was not created");

    socket.open();
    await subscription;
    socket.disconnect();

    expect(received).toEqual([{
      event: "pipeline_error",
      app_run_id: "run_00000000000000000000000000000001",
      message: "웹 연구 서버 연결이 예기치 않게 종료되었습니다.",
    }]);
  });
});
