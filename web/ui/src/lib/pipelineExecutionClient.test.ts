import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelPipeline, submitIdea } from "./pipelineExecutionClient";

const { cancelWebPipeline, startWebPipeline } = vi.hoisted(() => ({
  cancelWebPipeline: vi.fn(),
  startWebPipeline: vi.fn(),
}));

beforeEach(() => {
  cancelWebPipeline.mockReset();
  startWebPipeline.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

vi.mock("./webPipelineClient", () => ({
  cancelWebPipeline,
  startWebPipeline,
}));

describe("browser pipeline execution routing", () => {
  it("submits an online source-research run through the WebSocket pipeline", async () => {
    startWebPipeline.mockResolvedValue(launchReceipt());

    await expect(submitIdea(
      "웹 실행 질문",
      "full",
      "shallow",
      {
        MUCHANIPO_ONLINE: "1",
        MUCHANIPO_SOURCE_RESEARCH: "1",
      },
      "run_00000000000000000000000000000001",
    )).resolves.toMatchObject({
      app_run_id: "run_00000000000000000000000000000001",
      generation: 1,
    });

    expect(startWebPipeline).toHaveBeenCalledExactlyOnceWith(
      "웹 실행 질문",
      "full",
      "shallow",
      {
        MUCHANIPO_ONLINE: "1",
        MUCHANIPO_SOURCE_RESEARCH: "1",
      },
      "run_00000000000000000000000000000001",
    );
  });

  it("cancels through the WebSocket pipeline", async () => {
    cancelWebPipeline.mockResolvedValue({
      acknowledged: true,
      app_run_id: "run_00000000000000000000000000000001",
      generation: 1,
      kill_sent: false,
      reaped: true,
      termination_observed: true,
    });

    await expect(cancelPipeline(
      "run_00000000000000000000000000000001",
      1,
    )).resolves.toMatchObject({ acknowledged: true, reaped: true });

    expect(cancelWebPipeline).toHaveBeenCalledExactlyOnceWith(
      "run_00000000000000000000000000000001",
      1,
    );
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
