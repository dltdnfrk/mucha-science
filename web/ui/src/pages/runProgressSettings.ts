import type { ResearchDepth } from "../lib/tauriClient";
import { readCredentialSetting } from "../lib/sessionCredentials";

type BackendMode = "offline" | "cli" | "api";

export type ExecutionPresentation = {
  readonly detail: string;
  readonly label: string;
};

export type ExecutionPresentationSettings = {
  readonly backendMode: string | null;
  readonly hasMiMoCredential: boolean;
  readonly hasOpenCodeGoCredential: boolean;
};

const OFFLINE_PRESENTATION = {
  detail: "외부 또는 웹 검색을 수행하지 않습니다.",
  label: "오프라인 데모",
} as const satisfies ExecutionPresentation;

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
  return value === "cli" || value === "api" || value === "offline" ? value : "offline";
}

function readCredential(key: string): string {
  return readCredentialSetting(key);
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
    case "offline":
    default:
      return OFFLINE_PRESENTATION;
  }
}

export function readEnvsFromSettings(): Record<string, string> {
  const backendMode = readBackendMode();
  const envs: Record<string, string> = {};
  if (backendMode === "offline") {
    envs["MUCHANIPO_OFFLINE"] = "1";
  } else if (backendMode === "cli") {
    envs["MUCHANIPO_USE_CLI"] = "1";
    envs["MUCHANIPO_ONLINE"] = "1";
    envs["MUCHANIPO_REQUIRE_LIVE"] = "1";
    envs["MUCHANIPO_SOURCE_RESEARCH"] = "1";
  } else {
    const mimoKey = readCredential("mimo_api_key").trim();
    const opencodeGoKey = readCredential("opencode_api_key").trim();
    if (!mimoKey && !opencodeGoKey) {
      throw new RunSettingsError(
        "API 실행 모드인데 현재 세션에 MiMo 또는 OpenCode Go API Key가 없습니다. 설정에서 둘 중 하나 이상을 저장한 뒤 다시 시작하세요.",
      );
    }
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
    if (mimoKey) {
      envs["XIAOMI_MIMO_API_KEY"] = mimoKey;
      envs["MIMO_API_KEY"] = mimoKey;
      envs["MIMO_MODEL"] = readCredential("mimo_model").trim() || "mimo-v2.5-pro";
      envs["MUCHANIPO_MIMO_MODEL"] = envs["MIMO_MODEL"];
      const baseUrl =
        readCredential("mimo_base_url").trim() || "https://token-plan-sgp.xiaomimimo.com/v1";
      envs["MIMO_BASE_URL"] = baseUrl;
      envs["XIAOMI_MIMO_BASE_URL"] = baseUrl;
      envs["MUCHANIPO_PROVIDER_CHAIN"] = opencodeGoKey ? "mimo,opencode" : "mimo";
    }
    if (opencodeGoKey) {
      envs["OPENCODE_API_KEY"] = opencodeGoKey;
      envs["OPENCODE_GO_API_KEY"] = opencodeGoKey;
    }
    const plannotatorKey = readCredential("plannotator_key").trim();
    if (plannotatorKey) envs["PLANNOTATOR_API_KEY"] = plannotatorKey;
  }
  if (backendMode !== "offline") {
    const openAlexEmail = readCredential("openalex_email").trim();
    if (openAlexEmail) {
      envs["MUCHANIPO_CONTACT_EMAIL"] = openAlexEmail;
      envs["UNPAYWALL_EMAIL"] = openAlexEmail;
    }
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
