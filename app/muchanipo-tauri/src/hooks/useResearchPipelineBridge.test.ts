import { describe, expect, it, vi } from "vitest";
import type { BackendEvent } from "../lib/tauriClient";

const bridgeHarness = vi.hoisted(() => {
  let handler: ((event: BackendEvent) => void) | undefined;
  const unlisten = vi.fn();
  const onBackendEvent = vi.fn(async (nextHandler: (event: BackendEvent) => void) => {
    handler = nextHandler;
    return unlisten;
  });

  return {
    emit(event: BackendEvent): void {
      if (!handler) throw new Error("backend event handler was not attached");
      handler(event);
    },
    getBufferedEvents: vi.fn(async () => [] as BackendEvent[]),
    onBackendEvent,
    reset(): void {
      handler = undefined;
      unlisten.mockClear();
      onBackendEvent.mockClear();
    },
    sendAction: vi.fn(),
    unlisten,
  };
});

vi.mock("react", () => ({
  useCallback: <Callback>(callback: Callback) => callback,
  useEffect: () => undefined,
  useRef: <Value>(initialValue?: Value) => ({ current: initialValue }),
  useState: <Value>(initialValue?: Value) => [initialValue, () => undefined],
}));

vi.mock("../lib/tauriClient", () => ({
  getBufferedEvents: bridgeHarness.getBufferedEvents,
  onBackendEvent: bridgeHarness.onBackendEvent,
  sendAction: bridgeHarness.sendAction,
}));

import { useResearchPipelineBridge } from "./useResearchPipelineBridge";

const runId = "app-run-terminal-generation";
const turnId = "turn-terminal-generation";
const generation = 7;

const terminalCases = [
  ["done", "complete"],
  ["error", "error"],
  ["pipeline_error", "error"],
] as const;

describe("useResearchPipelineBridge terminal generation admission", () => {
  it.each(terminalCases)("does not terminalize %s until its current generation arrives", async (event, status) => {
    // Given
    bridgeHarness.reset();
    const onConversationEvent = vi.fn();
    const onError = vi.fn();
    const onTerminal = vi.fn();
    const bridge = useResearchPipelineBridge({ onConversationEvent, onError, onTerminal });
    const current = {
      event,
      app_run_id: runId,
      generation,
    } satisfies BackendEvent;
    const stale = { ...current, generation: generation - 1 };
    const missing = { event, app_run_id: runId } satisfies BackendEvent;

    await bridge.attachRun(runId, turnId, generation);

    // When
    bridgeHarness.emit(stale);
    bridgeHarness.emit(missing);

    // Then
    expect(onTerminal).not.toHaveBeenCalled();
    expect(bridgeHarness.unlisten).not.toHaveBeenCalled();

    // When
    bridgeHarness.emit(current);
    bridgeHarness.emit(current);

    // Then
    expect(onTerminal).toHaveBeenCalledTimes(1);
    expect(onTerminal).toHaveBeenCalledWith(runId, turnId, status);
    expect(bridgeHarness.unlisten).toHaveBeenCalledTimes(1);
    expect(onConversationEvent).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });
});
