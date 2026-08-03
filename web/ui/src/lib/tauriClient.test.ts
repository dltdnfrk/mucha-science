import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BackendEvent } from "./tauriClient";

const webPipelineMocks = vi.hoisted(() => ({
  getWebPipelineRuntimeStatus: vi.fn(),
  sendWebPipelineAction: vi.fn(),
  subscribeWebPipeline: vi.fn(),
}));

vi.mock("./webPipelineClient", () => webPipelineMocks);

import { getBufferedEvents, onBackendEvent } from "./tauriClient";

type BackendListener = (event: BackendEvent) => void;

let backendListener: BackendListener | undefined;

beforeEach(() => {
  backendListener = undefined;
  webPipelineMocks.subscribeWebPipeline.mockReset();
  webPipelineMocks.subscribeWebPipeline.mockImplementation(
    (_runId: string, listener: BackendListener) => {
      backendListener = listener;
      return Promise.resolve(() => {});
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("backend event run isolation", () => {
  it("subscribes to the current run through the live WebSocket pipeline", async () => {
    const received: BackendEvent[] = [];
    await onBackendEvent((event) => received.push(event), "run-current");

    expect(webPipelineMocks.subscribeWebPipeline).toHaveBeenCalledExactlyOnceWith(
      "run-current",
      expect.any(Function),
    );
    backendListener?.({ event: "warning", app_run_id: "run-current" });

    expect(received).toEqual([{ event: "warning", app_run_id: "run-current" }]);
  });

  it("does not make an obsolete HTTP replay request for a WebSocket run", async () => {
    const events = await getBufferedEvents("run-current");

    expect(events).toEqual([]);
  });
});
