import type { ResearchDepth } from "../lib/tauriClient";
import { readCredentialSetting } from "../lib/sessionCredentials";

type BackendMode = "cli" | "api";
export type ProviderChain = "mimo" | "opencode" | "mimo,opencode";

export type ExecutionPresentation = {
  readonly detail: string;
  readonly label: string;
};

export type ExecutionPresentationSettings = {
  readonly backendMode: string | null;
  readonly hasMiMoCredential: boolean;
  readonly hasOpenCodeGoCredential: boolean;
};

const CLI_PRESENTATION = {
  detail: "CLI 설정으로 라이브 연구를 요청할 수 있습니다. 아직 연구 실행 성공을 의미하지 않습니다.",
  label: "CLI 라이브 연구 요청",
} as const satisfies ExecutionPresentation;

const API_READY_PRESENTATION = {
  detail: "현재 세션의 MiMo 또는 OpenCode Go 자격 증명으로 API 연구를 요청할 수 있습니다.",
  label: "API 연구 요청 준비됨",
} as const satisfies ExecutionPresentation;

const API_CONNECTION_REQUIRED_PRESENTATION = {
  detail: "API 연구를 요청하려면 현재 세션에 MiMo 또는 OpenCode Go 자격 증명이 필요합니다.",
  label: "연결 필요",
} as const satisfies ExecutionPresentation;

class RunSettingsError extends Error {
  readonly name = "RunSettingsError";
}

function readBackendMode(): BackendMode {
  const value = localStorage.getItem("backend_mode");
  return value === "cli" ? "cli" : "api";
}

function readCredential(key: string): string {
  return readCredentialSetting(key);
}

function readProviderChain(
  hasMiMoCredential: boolean,
  hasOpenCodeCredential: boolean,
): ProviderChain {
  const stored = localStorage.getItem("provider_chain");
  if (stored === "mimo" || stored === "opencode" || stored === "mimo,opencode") {
    return stored;
  }
  if (hasMiMoCredential && hasOpenCodeCredential) return "mimo,opencode";
  if (hasMiMoCredential) return "mimo";
  return "opencode";
}

function requireSelectedCredential(
  provider: "MiMo" | "OpenCode Go",
  value: string,
): string {
  if (value) return value;
  throw new RunSettingsError(
    `${provider}를 선택했지만 현재 세션에 ${provider} API Key가 없습니다. 설정에서 키를 저장한 뒤 다시 시작하세요.`,
  );
}

function readOpenCodeModel(): string {
  const model = readCredential("opencode_model").trim() || "opencode/kimi-k2.6";
  if (model.startsWith("opencode/") || model.startsWith("opencode-go/")) return model;
  throw new RunSettingsError(
    "OpenCode 모델은 opencode/ 또는 opencode-go/ 접두어를 사용해야 합니다.",
  );
}

export function readExecutionPresentation({
  backendMode,
  hasMiMoCredential,
  hasOpenCodeGoCredential,
}: ExecutionPresentationSettings): ExecutionPresentation {
  switch (backendMode) {
    case "api":
      return hasMiMoCredential || hasOpenCodeGoCredential
        ? API_READY_PRESENTATION
        : API_CONNECTION_REQUIRED_PRESENTATION;
    case "cli":
      return CLI_PRESENTATION;
    default:
      return API_CONNECTION_REQUIRED_PRESENTATION;
  }
}

export function readEnvsFromSettings(): Record<string, string> {
  const backendMode = readBackendMode();
  const envs: Record<string, string> = {};
  if (backendMode === "cli") {
    envs["MUCHANIPO_USE_CLI"] = "1";
    envs["MUCHANIPO_ONLINE"] = "1";
    envs["MUCHANIPO_REQUIRE_LIVE"] = "1";
    envs["MUCHANIPO_SOURCE_RESEARCH"] = "1";
  } else {
    const mimoKey = readCredential("mimo_api_key").trim();
    const opencodeGoKey = readCredential("opencode_api_key").trim();
    const providerChain = readProviderChain(Boolean(mimoKey), Boolean(opencodeGoKey));
    envs["MUCHANIPO_ONLINE"] = "1";
    envs["MUCHANIPO_REQUIRE_LIVE"] = "1";
    envs["MUCHANIPO_SOURCE_RESEARCH"] = "1";
    envs["MUCHANIPO_VERIFICATION_ROUTING"] = "mimo_opencode_go_only";
    envs["MUCHANIPO_API_ROUTING"] = "mimo_opencode_go_only";
    envs["MUCHANIPO_MODEL_ROUTING"] = "mimo_opencode_go_only";
    envs["MUCHANIPO_INTERVIEW_COUNSELLING"] = "1";
    envs["MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK"] = "1";
    envs["MUCHANIPO_PREFER_CLI"] = "0";
    envs["OPENCODE_USE_CLI"] = "0";
    envs["MUCHANIPO_USE_CLI"] = "0";
    envs["MUCHANIPO_PROVIDER_CHAIN"] = providerChain;
    if (providerChain.includes("mimo")) {
      const selectedMiMoKey = requireSelectedCredential("MiMo", mimoKey);
      envs["XIAOMI_MIMO_API_KEY"] = selectedMiMoKey;
      envs["MIMO_API_KEY"] = selectedMiMoKey;
      envs["MIMO_MODEL"] = readCredential("mimo_model").trim() || "mimo-v2.5-pro";
      envs["MUCHANIPO_MIMO_MODEL"] = envs["MIMO_MODEL"];
      const baseUrl =
        readCredential("mimo_base_url").trim() || "https://token-plan-sgp.xiaomimimo.com/v1";
      envs["MIMO_BASE_URL"] = baseUrl;
      envs["XIAOMI_MIMO_BASE_URL"] = baseUrl;
    }
    if (providerChain.includes("opencode")) {
      const selectedOpenCodeKey = requireSelectedCredential("OpenCode Go", opencodeGoKey);
      envs["OPENCODE_API_KEY"] = selectedOpenCodeKey;
      envs["OPENCODE_GO_API_KEY"] = selectedOpenCodeKey;
      envs["MUCHANIPO_OPENCODE_MODEL"] = readOpenCodeModel();
    }
    const plannotatorKey = readCredential("plannotator_key").trim();
    if (plannotatorKey) envs["PLANNOTATOR_API_KEY"] = plannotatorKey;
  }
  const openAlexEmail = readCredential("openalex_email").trim();
  if (openAlexEmail) {
    envs["MUCHANIPO_CONTACT_EMAIL"] = openAlexEmail;
    envs["UNPAYWALL_EMAIL"] = openAlexEmail;
  }
  if (localStorage.getItem("council_visualizer") === "ollama") {
    envs["MUCHANIPO_COUNCIL_VISUALIZER"] = "ollama";
    envs["MUCHANIPO_COUNCIL_VISUALIZER_MODEL"] =
      localStorage.getItem("council_visualizer_model") || "qwen3.6-a3b:latest";
  }
  return envs;
}

export function readResearchDepth(): ResearchDepth {
  const value = localStorage.getItem("research_depth");
  return value === "shallow" || value === "deep" || value === "max" || value === "superdeep"
    ? value
    : "deep";
}
