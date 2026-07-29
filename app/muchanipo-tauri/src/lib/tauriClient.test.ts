import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BackendEvent } from "./tauriClient";

const tauriMocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: tauriMocks.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: tauriMocks.listen }));

import { getBufferedEvents, onBackendEvent } from "./tauriClient";

type BackendListener = (event: { readonly payload: BackendEvent }) => void;

let backendListener: BackendListener | undefined;

beforeEach(() => {
  backendListener = undefined;
  tauriMocks.invoke.mockReset();
  tauriMocks.listen.mockReset();
  tauriMocks.listen.mockImplementation(
    (_eventName: string, listener: BackendListener) => {
      backendListener = listener;
      return Promise.resolve(() => {});
    },
  );
  vi.stubGlobal("window", { __TAURI_INTERNALS__: {} });
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
    tauriMocks.invoke.mockResolvedValue([
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
    expect(tauriMocks.invoke).toHaveBeenCalledWith(
      "get_buffered_events",
      { appRunId: "run-current" },
    );
  });
});
