import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelPipeline, submitIdea } from "./pipelineExecutionClient";

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
    this.onmessage?.(new MessageEvent("message", {
      data: JSON.stringify(value),
    }));
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("window", {
    location: {
      host: "127.0.0.1:4173",
      hostname: "127.0.0.1",
      protocol: "http:",
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("browser pipeline execution routing", () => {
  it("routes submitIdea through the web runtime outside Tauri", async () => {
    const launched = submitIdea(
      "웹 실행 질문",
      "full",
      "shallow",
      { MUCHANIPO_OFFLINE: "1" },
      "run_00000000000000000000000000000001",
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    socket.open();
    expect(JSON.parse(socket.sent[0] ?? "")).toMatchObject({
      protocol: "mucha-science.web.v1",
      type: "run.start",
      run_id: "run_00000000000000000000000000000001",
    });
    socket.message({
      protocol: "mucha-science.web.v1",
      type: "run.started",
      receipt: launchReceipt(),
    });

    await expect(launched).resolves.toMatchObject({
      app_run_id: "run_00000000000000000000000000000001",
      generation: 1,
    });
  });

  it("routes cancellation through the same web runtime", async () => {
    const cancelled = cancelPipeline(
      "run_00000000000000000000000000000001",
      1,
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    socket.open();
    expect(JSON.parse(socket.sent[0] ?? "")).toMatchObject({
      protocol: "mucha-science.web.v1",
      type: "run.cancel",
      run_id: "run_00000000000000000000000000000001",
      generation: 1,
    });
    socket.message({
      protocol: "mucha-science.web.v1",
      type: "run.cancelled",
      acknowledgement: {
        acknowledged: true,
        app_run_id: "run_00000000000000000000000000000001",
        generation: 1,
        kill_sent: false,
        reaped: true,
        termination_observed: true,
      },
    });

    await expect(cancelled).resolves.toMatchObject({
      acknowledged: true,
      reaped: true,
    });
  });
});

function launchReceipt() {
  return {
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
  };
}
