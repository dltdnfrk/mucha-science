import type { SourceStatus } from "./sourceConnections";

const EXECUTABLE_CATALOG_SOURCES = [
  { sourceId: "openalex", backendId: "openalex" },
  { sourceId: "crossref", backendId: "crossref" },
  {
    sourceId: "semantic-scholar",
    backendId: "semantic_scholar",
    credentialEnvironmentKey: "SEMANTIC_SCHOLAR_API_KEY",
  },
  {
    sourceId: "pubmed-ncbi",
    backendId: "pubmed",
    credentialEnvironmentKey: "MUCHANIPO_NCBI_API_KEY",
  },
  { sourceId: "arxiv", backendId: "arxiv" },
  {
    sourceId: "core",
    backendId: "core",
    credentialEnvironmentKey: "MUCHANIPO_CORE_API_KEY",
  },
  { sourceId: "unpaywall", backendId: "unpaywall" },
] as const;

const CATALOG_SOURCE_IDS = new Set([
  "openalex",
  "crossref",
  "pubmed-ncbi",
  "arxiv",
  "semantic-scholar",
  "core",
  "unpaywall",
  "springer-nature",
  "elsevier",
  "oasis",
]);

type ExecutableCatalogSource = (typeof EXECUTABLE_CATALOG_SOURCES)[number];

export type BackendAcademicSourceId = ExecutableCatalogSource["backendId"];

export type SourceCredentialReader = (sourceId: string) => string | undefined;

export type SourceExecutionSource = {
  readonly id: string;
  readonly name: string;
  readonly url: string;
  readonly status: SourceStatus;
  readonly access: {
    readonly kind: string;
  };
};

export type SourceExecutionEnvironment = {
  readonly MUCHANIPO_SOURCE_RESEARCH: "0" | "1";
  readonly MUCHANIPO_ACADEMIC_SOURCES?: string;
};

export type SourceCredentialEnvironment = {
  readonly SEMANTIC_SCHOLAR_API_KEY?: string;
  readonly MUCHANIPO_NCBI_API_KEY?: string;
  readonly MUCHANIPO_CORE_API_KEY?: string;
};

export type SkippedSource = {
  readonly id: string;
  readonly name: string;
  readonly reason: string;
};

export type SourceExecutionPublicMetadata = {
  readonly sourceAllowlist: readonly BackendAcademicSourceId[];
  readonly skippedSources: readonly SkippedSource[];
};

export type SourceExecutionExport = {
  readonly sourceAllowlist: readonly BackendAcademicSourceId[];
  readonly environment: SourceExecutionEnvironment;
  readonly skippedSources: readonly SkippedSource[];
};

export type SourceExecutionProfile = {
  readonly sourceAllowlist: readonly BackendAcademicSourceId[];
  readonly environment: SourceExecutionEnvironment;
  readonly skippedSources: readonly SkippedSource[];
  readonly publicMetadata: SourceExecutionPublicMetadata;
  readonly exportSafe: SourceExecutionExport;
  readonly getTransientCredentialEnvironment: () => SourceCredentialEnvironment;
};

export function buildSourceExecutionProfile(
  sources: readonly SourceExecutionSource[],
  readCredential: SourceCredentialReader,
): SourceExecutionProfile {
  const credentialEnvironment: Record<string, string> = {};
  const sourceAllowlist = EXECUTABLE_CATALOG_SOURCES.flatMap((catalogSource) => {
    const source = sources.find(
      (candidate) => candidate.id === catalogSource.sourceId && candidate.status === "connected",
    );
    if (!source) return [];
    if ("credentialEnvironmentKey" in catalogSource) {
      const credential = readCredential(source.id)?.trim();
      if (credential) {
        credentialEnvironment[catalogSource.credentialEnvironmentKey] = credential;
      }
    }
    return [catalogSource.backendId];
  });
  const environment = buildEnvironment(sourceAllowlist);
  const skippedSources = sources.flatMap(toSkippedSource);
  const publicMetadata: SourceExecutionPublicMetadata = {
    sourceAllowlist: [...sourceAllowlist],
    skippedSources: [...skippedSources],
  };
  const exportSafe: SourceExecutionExport = {
    sourceAllowlist: [...sourceAllowlist],
    environment: { ...environment },
    skippedSources: [...skippedSources],
  };
  const profile: SourceExecutionProfile = {
    sourceAllowlist,
    environment,
    skippedSources,
    publicMetadata,
    exportSafe,
    getTransientCredentialEnvironment: () => ({ ...credentialEnvironment }),
  };
  Object.defineProperty(profile, "getTransientCredentialEnvironment", { enumerable: false });
  return profile;
}

export function composeResearchExecutionEnvironment(
  modelEnvironment: Readonly<Record<string, string>>,
  sourceProfile: SourceExecutionProfile,
): Record<string, string> {
  if (isEnabled(modelEnvironment.MUCHANIPO_OFFLINE)) {
    return {
      ...modelEnvironment,
      MUCHANIPO_SOURCE_RESEARCH: "0",
    };
  }
  return {
    ...modelEnvironment,
    ...sourceProfile.environment,
    ...sourceProfile.getTransientCredentialEnvironment(),
  };
}

function isEnabled(value: string | undefined): boolean {
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

function buildEnvironment(
  sourceAllowlist: readonly BackendAcademicSourceId[],
): SourceExecutionEnvironment {
  if (sourceAllowlist.length === 0) {
    return { MUCHANIPO_SOURCE_RESEARCH: "0" };
  }
  return {
    MUCHANIPO_SOURCE_RESEARCH: "1",
    MUCHANIPO_ACADEMIC_SOURCES: sourceAllowlist.join(","),
  };
}

function toSkippedSource(source: SourceExecutionSource): readonly SkippedSource[] {
  if (source.status !== "connected" || isExecutableSource(source.id)) return [];
  if (CATALOG_SOURCE_IDS.has(source.id)) {
    return [{
      id: source.id,
      name: source.name,
      reason: "백엔드에서 지원하지 않는 카탈로그 소스입니다.",
    }];
  }
  if (!usesHttps(source.url)) {
    return [{
      id: source.id,
      name: source.name,
      reason: "HTTPS가 아닌 사용자 정의 소스는 실행할 수 없습니다.",
    }];
  }
  return [{
    id: source.id,
    name: source.name,
    reason: "사용자 정의 소스용 백엔드 커넥터가 없습니다.",
  }];
}

function isExecutableSource(sourceId: string): boolean {
  return EXECUTABLE_CATALOG_SOURCES.some((source) => source.sourceId === sourceId);
}

function usesHttps(value: string): boolean {
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}
