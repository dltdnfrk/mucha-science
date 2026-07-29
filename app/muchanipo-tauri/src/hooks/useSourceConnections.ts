import { useCallback, useEffect, useMemo, useState } from "react";
import {
  addCustomSource,
  buildSourceExecutionProfile,
  deserializeSourceConnections,
  getDefaultSourceConnections,
  serializeSourceConnections,
} from "../lib/sourceConnections";
import type {
  CustomSourceInput,
  SourceConnection,
  SourceExecutionProfile,
  SourceStatus,
} from "../lib/sourceConnections";

const SOURCE_METADATA_KEY = "mucha-science.source-connections.v1";
const SESSION_CREDENTIAL_PREFIX = "mucha-science.source-credential.v1.";

type StorageKind = "local" | "session";

export interface SourceConnectionsState {
  readonly sources: readonly SourceConnection[];
  readonly connectedSources: readonly SourceConnection[];
  readonly setSourceStatus: (sourceId: string, status: SourceStatus) => void;
  readonly addSource: (input: CustomSourceInput) => void;
  readonly buildExecutionProfile: () => SourceExecutionProfile;
  readonly saveSessionCredential: (sourceId: string, credential: string) => boolean;
  readonly hasSessionCredential: (sourceId: string) => boolean;
}

export function useSourceConnections(): SourceConnectionsState {
  const [sources, setSources] = useState<readonly SourceConnection[]>(initialSources);
  const [sessionCredentialIds, setSessionCredentialIds] = useState<readonly string[]>(
    () => sources.filter((source) => hasStoredCredential(source.id)).map((source) => source.id),
  );

  useEffect(() => {
    const storage = browserStorage("local");
    if (storage) writeStorage(storage, SOURCE_METADATA_KEY, serializeSourceConnections(sources));
  }, [sources]);

  const connectedSources = useMemo(
    () => sources.filter((source) => source.status === "connected"),
    [sources],
  );

  const setSourceStatus = useCallback((sourceId: string, status: SourceStatus) => {
    setSources((current) => current.map((source) => (
      source.id === sourceId ? { ...source, status } : source
    )));
  }, []);

  const addSource = useCallback((input: CustomSourceInput) => {
    const nextSources = addCustomSource(sources, input);
    setSources(nextSources);
  }, [sources]);

  const buildExecutionProfile = useCallback(
    () => buildSourceExecutionProfile(sources, readSessionCredential),
    [sources],
  );

  const saveSessionCredential = useCallback((sourceId: string, credential: string): boolean => {
    const storage = browserStorage("session");
    if (!storage) return false;

    const key = `${SESSION_CREDENTIAL_PREFIX}${sourceId}`;
    const saved = credential.trim()
      ? writeStorage(storage, key, credential)
      : removeStorage(storage, key);
    if (!saved) return false;

    setSessionCredentialIds((current) => (
      credential.trim()
        ? current.includes(sourceId) ? current : [...current, sourceId]
        : current.filter((id) => id !== sourceId)
    ));
    return true;
  }, []);

  const hasSessionCredential = useCallback(
    (sourceId: string) => sessionCredentialIds.includes(sourceId),
    [sessionCredentialIds],
  );

  return {
    sources,
    connectedSources,
    setSourceStatus,
    addSource,
    buildExecutionProfile,
    saveSessionCredential,
    hasSessionCredential,
  };
}

function initialSources(): readonly SourceConnection[] {
  const storage = browserStorage("local");
  const serialized = storage ? readStorage(storage, SOURCE_METADATA_KEY) : null;
  return serialized === null ? defaultEnabledSources() : deserializeSourceConnections(serialized);
}

function defaultEnabledSources(): readonly SourceConnection[] {
  return getDefaultSourceConnections().map((source) => (
    source.access.kind === "open" ? { ...source, status: "connected" } : source
  ));
}

function hasStoredCredential(sourceId: string): boolean {
  const storage = browserStorage("session");
  return storage ? Boolean(readStorage(storage, `${SESSION_CREDENTIAL_PREFIX}${sourceId}`)) : false;
}

function readSessionCredential(sourceId: string): string | undefined {
  try {
    const storage = browserStorage("session");
    if (!storage) return undefined;
    return readStorage(storage, `${SESSION_CREDENTIAL_PREFIX}${sourceId}`)?.trim() || undefined;
  } catch (error) {
    if (error instanceof Error) return undefined;
    return undefined;
  }
}

function browserStorage(kind: StorageKind): Storage | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch (error) {
    if (error instanceof Error) return undefined;
    throw error;
  }
}

function readStorage(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch (error) {
    if (error instanceof Error) return null;
    throw error;
  }
}

function writeStorage(storage: Storage, key: string, value: string): boolean {
  try {
    storage.setItem(key, value);
    return true;
  } catch (error) {
    if (error instanceof Error) return false;
    throw error;
  }
}

function removeStorage(storage: Storage, key: string): boolean {
  try {
    storage.removeItem(key);
    return true;
  } catch (error) {
    if (error instanceof Error) return false;
    throw error;
  }
}
