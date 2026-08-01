import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelPipeline, submitIdea } from "./pipelineExecutionClient";

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("browser pipeline execution routing", () => {
  it("submits an idea through the HTTP command API", async () => {
    fetchMock.mockResolvedValue(jsonResponse(launchReceipt()));

    await expect(submitIdea(
      "웹 실행 질문",
      "full",
      "shallow",
      { MUCHANIPO_OFFLINE: "1" },
      "run_00000000000000000000000000000001",
    )).resolves.toMatchObject({
      app_run_id: "run_00000000000000000000000000000001",
      generation: 1,
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("http://127.0.0.1:8787/api/commands/start_pipeline");
    expect(JSON.parse(String(init?.body))).toEqual({
      topic: "웹 실행 질문",
      pipeline: "full",
      depth: "shallow",
      envs: { MUCHANIPO_OFFLINE: "1" },
      appRunId: "run_00000000000000000000000000000001",
    });
  });

  it("cancels through the same HTTP command API", async () => {
    fetchMock.mockResolvedValue(jsonResponse({
      acknowledged: true,
      app_run_id: "run_00000000000000000000000000000001",
      generation: 1,
      kill_sent: false,
      reaped: true,
      termination_observed: true,
    }));

    await expect(cancelPipeline(
      "run_00000000000000000000000000000001",
      1,
    )).resolves.toMatchObject({ acknowledged: true, reaped: true });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("http://127.0.0.1:8787/api/commands/cancel_pipeline");
    expect(JSON.parse(String(init?.body))).toEqual({
      appRunId: "run_00000000000000000000000000000001",
      generation: 1,
    });
  });
});

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

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
