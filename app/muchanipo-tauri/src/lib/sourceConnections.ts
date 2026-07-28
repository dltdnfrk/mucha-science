import { getDefaultSourceConnections } from "./sourceConnectionCatalog";
import { isSafeExternalHttpUrl } from "./safeExternalUrl";

export const SOURCE_STATUSES = [
  "connected",
  "disconnected",
  "connecting",
  "error",
  "unavailable",
] as const;

export type SourceStatus = (typeof SOURCE_STATUSES)[number];

export const SOURCE_ACCESS_KINDS = ["open", "api-key", "custom"] as const;

export type SourceAccessKind = (typeof SOURCE_ACCESS_KINDS)[number];

export type SourceAccess = {
  readonly kind: SourceAccessKind;
};

export type SourceConnection = {
  readonly id: string;
  readonly name: string;
  readonly url: string;
  readonly description?: string;
  readonly status: SourceStatus;
  readonly access: SourceAccess;
};

export type CustomSourceInput = {
  readonly id: string;
  readonly name: string;
  readonly url: string;
  readonly description?: string;
  readonly status?: SourceStatus;
  readonly access?: SourceAccess | SourceAccessKind;
  readonly apiKey?: string;
  readonly secret?: string;
};

export {
  buildSourceExecutionProfile,
  composeResearchExecutionEnvironment,
} from "./sourceExecutionProfile";
export type {
  BackendAcademicSourceId,
  SkippedSource,
  SourceCredentialEnvironment,
  SourceCredentialReader,
  SourceExecutionEnvironment,
  SourceExecutionExport,
  SourceExecutionProfile,
  SourceExecutionPublicMetadata,
  SourceExecutionSource,
} from "./sourceExecutionProfile";
export { getDefaultSourceConnections } from "./sourceConnectionCatalog";

export function addCustomSource(
  sources: readonly SourceConnection[],
  input: CustomSourceInput,
): readonly SourceConnection[] {
  const source = normalizeCustomSource(input);
  const duplicate = sources.some((candidate) => normalizeId(candidate.id) === source.id);
  if (duplicate) {
    throw new Error(`Source id already exists: ${source.id}`);
  }
  return [...sources, source];
}

export function serializeSourceConnections(sources: readonly SourceConnection[]): string {
  return JSON.stringify(sources.map(toPersistedSource));
}

export function deserializeSourceConnections(value: unknown): readonly SourceConnection[] {
  if (typeof value !== "string") return getDefaultSourceConnections();

  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    if (error instanceof SyntaxError) return getDefaultSourceConnections();
    throw error;
  }

  const persistedSources = readPersistedSources(parsed);
  if (!persistedSources) return getDefaultSourceConnections();

  const restored = persistedSources.map(readPersistedSource);
  if (restored.some((source) => source === null)) return getDefaultSourceConnections();

  const connections = restored.filter((source): source is SourceConnection => source !== null);
  const ids = new Set<string>();
  if (connections.length !== persistedSources.length) return getDefaultSourceConnections();
  for (const connection of connections) {
    if (ids.has(connection.id)) return getDefaultSourceConnections();
    ids.add(connection.id);
  }
  return mergeCatalogSources(connections);
}

function mergeCatalogSources(
  persisted: readonly SourceConnection[],
): readonly SourceConnection[] {
  const defaults = getDefaultSourceConnections();
  const defaultIds = new Set(defaults.map((source) => source.id));
  const byId = new Map(persisted.map((source) => [source.id, source]));
  return [
    ...defaults.map((source) => {
      const previous = byId.get(source.id);
      return previous ? { ...source, status: previous.status } : source;
    }),
    ...persisted.filter((source) => !defaultIds.has(source.id)),
  ];
}

function normalizeCustomSource(input: CustomSourceInput): SourceConnection {
  const id = normalizeId(input.id);
  const name = normalizeName(input.name);
  const url = normalizeUrl(input.url);
  const description = normalizeOptionalText(input.description);
  const source: SourceConnection = {
    id,
    name,
    url,
    status: input.status ?? "disconnected",
    access: normalizeAccess(input.access, input.apiKey, input.secret),
    ...(description === undefined ? {} : { description }),
  };
  return source;
}

function normalizeId(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (!normalized) throw new Error("Source id must not be empty");
  return normalized;
}

function normalizeName(value: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error("Source name must not be empty");
  return normalized;
}

function normalizeUrl(value: string): string {
  const normalized = value.trim();
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch (error) {
    if (error instanceof TypeError) throw new Error("Source URL must be a valid http(s) URL");
    throw error;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Source URL must be a valid http(s) URL");
  }
  if (!isSafeExternalHttpUrl(normalized)) {
    throw new Error(
      "Source URL must not include credentials or sensitive query parameters",
    );
  }
  return normalized;
}

function normalizeOptionalText(value: string | undefined): string | undefined {
  const normalized = value?.trim();
  return normalized ? normalized : undefined;
}

function normalizeAccess(
  value: SourceAccess | SourceAccessKind | undefined,
  apiKey: string | undefined,
  secret: string | undefined,
): SourceAccess {
  if (typeof value === "string" && isSourceAccessKind(value)) return { kind: value };
  if (isSourceAccess(value)) return { kind: value.kind };
  if (apiKey?.trim() || secret?.trim()) return { kind: "api-key" };
  return { kind: "custom" };
}

function toPersistedSource(source: SourceConnection): SourceConnection {
  const description = normalizeOptionalText(source.description);
  return {
    id: normalizeId(source.id),
    name: normalizeName(source.name),
    url: normalizeUrl(source.url),
    status: source.status,
    access: { kind: source.access.kind },
    ...(description === undefined ? {} : { description }),
  };
}

function readPersistedSources(value: unknown): readonly unknown[] | undefined {
  if (Array.isArray(value)) return value;
  if (!isRecord(value)) return undefined;
  const sources = value.sources;
  return Array.isArray(sources) ? sources : undefined;
}

function readPersistedSource(value: unknown): SourceConnection | null {
  if (!isRecord(value)) return null;
  if (typeof value.id !== "string" || typeof value.name !== "string" || typeof value.url !== "string") return null;
  if (!isSourceStatus(value.status)) return null;
  const access = readPersistedAccess(value.access);
  if (access === null) return null;

  try {
    const id = normalizeId(value.id);
    const name = normalizeName(value.name);
    const url = normalizeUrl(value.url);
    const description = typeof value.description === "string" ? normalizeOptionalText(value.description) : undefined;
    return {
      id,
      name,
      url,
      status: value.status,
      access,
      ...(description === undefined ? {} : { description }),
    };
  } catch (error) {
    if (error instanceof Error) return null;
    throw error;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isSourceStatus(value: unknown): value is SourceStatus {
  return typeof value === "string" && SOURCE_STATUSES.some((status) => status === value);
}

function isSourceAccessKind(value: unknown): value is SourceAccessKind {
  return typeof value === "string" && SOURCE_ACCESS_KINDS.some((kind) => kind === value);
}

function isSourceAccess(value: unknown): value is SourceAccess {
  return isRecord(value) && isSourceAccessKind(value.kind);
}

function readPersistedAccess(value: unknown): SourceAccess | null {
  if (isSourceAccess(value)) return { kind: value.kind };
  if (isSourceAccessKind(value)) return { kind: value };
  return null;
}
