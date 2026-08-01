/** Browser transport for the Mucha Science server contract. */
export type UnlistenFn = () => void;

export interface ApiEvent<T> {
  payload: T;
}

export type ApiEventHandler<T> = (event: ApiEvent<T>) => void;

const DEFAULT_BASE_URL = "http://127.0.0.1:8787";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Execute a named backend command over HTTP. */
export async function invoke<TResult = void>(
  command: string,
  args: Record<string, unknown> = {},
): Promise<TResult> {
  const response = await fetch(`${apiBaseUrl()}/api/commands/${encodeURIComponent(command)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(detail || `Command ${command} failed with HTTP ${response.status}.`, response.status);
  }
  if (response.status === 204) return undefined as TResult;
  return await response.json() as TResult;
}

/** Subscribe to a named backend event channel over WebSocket. */
export function listen<T>(
  eventName: string,
  handler: ApiEventHandler<T>,
  options: { runId?: string } = {},
): Promise<UnlistenFn> {
  return new Promise((resolve, reject) => {
    const url = new URL("/api/events", websocketBaseUrl());
    url.searchParams.set("channel", eventName);
    if (options.runId) url.searchParams.set("run_id", options.runId);

    const socket = new WebSocket(url);
    let opened = false;
    let closedByClient = false;
    socket.onopen = () => {
      opened = true;
      resolve(() => {
        closedByClient = true;
        socket.close(1000, "subscription disposed");
      });
    };
    socket.onmessage = (message) => {
      try {
        const decoded: unknown = JSON.parse(String(message.data));
        handler({ payload: unwrapEventPayload<T>(decoded) });
      } catch (error) {
        console.error(`Invalid ${eventName} event payload`, error);
      }
    };
    socket.onerror = () => {
      if (!opened) reject(new ApiError(`Could not subscribe to ${eventName}.`));
    };
    socket.onclose = () => {
      if (!opened && !closedByClient) {
        reject(new ApiError(`The ${eventName} subscription closed before connecting.`));
      }
    };
  });
}

export function apiBaseUrl(): string {
  return normalizeBaseUrl(import.meta.env.VITE_MUCHA_SCIENCE_API_URL || DEFAULT_BASE_URL);
}

export function websocketBaseUrl(): string {
  const configured = import.meta.env.VITE_MUCHA_SCIENCE_WS_URL?.trim();
  const base = configured || apiBaseUrl();
  const url = new URL(base);
  if (url.protocol === "http:") url.protocol = "ws:";
  if (url.protocol === "https:") url.protocol = "wss:";
  return url.toString();
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function unwrapEventPayload<T>(message: unknown): T {
  if (
    typeof message === "object" &&
    message !== null &&
    "payload" in message
  ) {
    return (message as { payload: T }).payload;
  }
  return message as T;
}
