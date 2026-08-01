import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BackendEvent } from "./tauriClient";

const apiMocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
}));

vi.mock("../api/client", () => apiMocks);

import { getBufferedEvents, onBackendEvent } from "./tauriClient";

type BackendListener = (event: { readonly payload: BackendEvent }) => void;

let backendListener: BackendListener | undefined;

beforeEach(() => {
  backendListener = undefined;
  apiMocks.invoke.mockReset();
  apiMocks.listen.mockReset();
  apiMocks.listen.mockImplementation(
    (_eventName: string, listener: BackendListener) => {
      backendListener = listener;
      return Promise.resolve(() => {});
    },
  );

});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("backend event run isolation", () => {
  it("delivers only current-run events from a live subscription", async () => {
    const received: BackendEvent[] = [];
    await onBackendEvent((event) => received.push(event), "run-current");

    backendListener?.({ payload: { event: "warning", app_run_id: "run-stale" } });
    backendListener?.({ payload: { event: "warning" } });
    backendListener?.({ payload: { event: "warning", app_run_id: "run-current" } });

    expect(received).toEqual([{ event: "warning", app_run_id: "run-current" }]);
  });

  it("replays only parseable current-run buffered events in backend order", async () => {
    apiMocks.invoke.mockResolvedValue([
      JSON.stringify({ event: "run_started", app_run_id: "run-current" }),
      JSON.stringify({ event: "warning", app_run_id: "run-stale" }),
      "{malformed",
      JSON.stringify({ event: "done", app_run_id: "run-current" }),
    ]);

    const events = await getBufferedEvents("run-current");

    expect(events).toEqual([
      { event: "run_started", app_run_id: "run-current" },
      { event: "done", app_run_id: "run-current" },
    ]);
    expect(apiMocks.invoke).toHaveBeenCalledWith(
      "get_buffered_events",
      { appRunId: "run-current" },
    );
  });
});
