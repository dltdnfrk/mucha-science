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

export interface MuniStudy {
  study_id: string;
  target_crop: string;
  target_pathogen: string;
  purpose: string;
  created_at: string;
  pack_ref: string | null;
}

export type MuniJobStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED";

export interface MuniCollectionJob {
  job_id: string;
  study_ref: string;
  source_ref: string;
  status: MuniJobStatus;
  started_at: string | null;
  finished_at: string | null;
  result_ref: string | null;
  reason: string | null;
}

export interface MuniCandidateItem {
  candidate_id?: string;
  disposition?: string;
  rank?: number | null;
  composite_score_ppm?: number | null;
  reasons?: string[];
}

export interface MuniCandidateSet {
  set_id: string;
  workflow_ref: string;
  kind: "DIAGNOSTIC_DISCOVERY" | "COMPOUND_SCREENING";
  items: MuniCandidateItem[];
  count: number;
  ranked: MuniCandidateItem[];
  excluded: MuniCandidateItem[];
  abstained: MuniCandidateItem[];
}

export interface MuniReview {
  review_id: string;
  candidate_set_ref: string;
  reviewer: string;
  decision: "APPROVED" | "REJECTED" | "NEEDS_MORE";
  note: string;
  decided_at: string;
}

export interface MuniHandoff {
  handoff_id: string;
  review_ref: string;
  artifact_paths: string[];
  disclaimer: string;
}

export async function createMuniStudy(input: {
  target_crop: string;
  target_pathogen: string;
  purpose: string;
  pack_ref?: string;
}): Promise<MuniStudy> {
  return requestJson("/api/muni/studies", { method: "POST", body: JSON.stringify(input) });
}

export async function listMuniStudies(): Promise<MuniStudy[]> {
  return (await requestJson<{ studies: MuniStudy[] }>("/api/muni/studies")).studies;
}

export function collectMuniStudy(studyId: string): Promise<{ jobs: MuniCollectionJob[] }> {
  return requestJson(`/api/muni/studies/${encodeURIComponent(studyId)}/collection`, { method: "POST" });
}

export function runMuniDiagnostic(studyId: string): Promise<MuniCandidateSet> {
  return requestJson(`/api/muni/studies/${encodeURIComponent(studyId)}/workflows/diagnostic/run`, { method: "POST" });
}

export function runMuniScreening(studyId: string, purpose: string): Promise<MuniCandidateSet> {
  return requestJson(`/api/muni/studies/${encodeURIComponent(studyId)}/workflows/screening/run`, {
    method: "POST",
    body: JSON.stringify({ purpose }),
  });
}

export async function getMuniCandidates(studyId: string): Promise<MuniCandidateSet[]> {
  return (await requestJson<{ candidate_sets: MuniCandidateSet[] }>(
    `/api/muni/studies/${encodeURIComponent(studyId)}/candidates`,
  )).candidate_sets;
}

export function reviewMuniCandidate(
  setId: string,
  input: { reviewer: string; decision: MuniReview["decision"]; note: string },
): Promise<MuniReview> {
  return requestJson(`/api/muni/candidates/${encodeURIComponent(setId)}/review`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createMuniHandoff(reviewId: string): Promise<MuniHandoff> {
  return requestJson(`/api/muni/reviews/${encodeURIComponent(reviewId)}/handoff`, { method: "POST" });
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  const response = await fetch(`${apiBaseUrl()}${path}`, { ...init, headers });
  const text = await response.text();
  if (!response.ok) {
    let message = text || `Request failed with HTTP ${response.status}.`;
    try {
      const payload = JSON.parse(text) as { error?: { message?: string } };
      message = payload.error?.message || message;
    } catch {
      // Preserve the server response when it is not JSON.
    }
    throw new ApiError(message, response.status);
  }
  return (text ? JSON.parse(text) : undefined) as T;
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
