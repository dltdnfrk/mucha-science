import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readEnvsFromSettings } from "./runProgressSettings";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

beforeEach(() => {
  vi.stubGlobal("localStorage", new MemoryStorage());
  vi.stubGlobal("sessionStorage", new MemoryStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("readEnvsFromSettings", () => {
  it("builds the MiMo provider environment with defaults and no unrelated provider secrets", () => {
    localStorage.setItem("backend_mode", "api");
    sessionStorage.setItem("mimo_api_key", " mimo-secret ");
    sessionStorage.setItem("anthropic_api_key", "anthropic-secret");
    sessionStorage.setItem("gemini_api_key", "gemini-secret");
    sessionStorage.setItem("kimi_api_key", "kimi-secret");
    sessionStorage.setItem("openai_api_key", "openai-secret");

    const envs = readEnvsFromSettings();

    expect(envs).toEqual(expect.objectContaining({
      XIAOMI_MIMO_API_KEY: "mimo-secret",
      MIMO_API_KEY: "mimo-secret",
      MIMO_MODEL: "mimo-v2.5-pro",
      MUCHANIPO_MIMO_MODEL: "mimo-v2.5-pro",
      MIMO_BASE_URL: "https://token-plan-sgp.xiaomimimo.com/v1",
      XIAOMI_MIMO_BASE_URL: "https://token-plan-sgp.xiaomimimo.com/v1",
      MUCHANIPO_PROVIDER_CHAIN: "mimo",
      MUCHANIPO_VERIFICATION_ROUTING: "mimo_opencode_go_only",
      MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK: "1",
      OPENCODE_USE_CLI: "0",
    }));
    expect(envs).not.toHaveProperty("ANTHROPIC_API_KEY");
    expect(envs).not.toHaveProperty("GEMINI_API_KEY");
    expect(envs).not.toHaveProperty("KIMI_API_KEY");
    expect(envs).not.toHaveProperty("OPENAI_API_KEY");
  });

  it("accepts OpenCode Go alone and publishes both supported credential aliases", () => {
    localStorage.setItem("backend_mode", "api");
    sessionStorage.setItem("opencode_api_key", " opencode-secret ");

    const envs = readEnvsFromSettings();

    expect(envs["OPENCODE_API_KEY"]).toBe("opencode-secret");
    expect(envs["OPENCODE_GO_API_KEY"]).toBe("opencode-secret");
    expect(envs).not.toHaveProperty("XIAOMI_MIMO_API_KEY");
    expect(envs).not.toHaveProperty("MIMO_API_KEY");
  });

  it("orders MiMo before OpenCode when both providers are configured", () => {
    localStorage.setItem("backend_mode", "api");
    sessionStorage.setItem("mimo_api_key", "mimo-secret");
    sessionStorage.setItem("opencode_api_key", "opencode-secret");

    const envs = readEnvsFromSettings();

    expect(envs["MUCHANIPO_PROVIDER_CHAIN"]).toBe("mimo,opencode");
  });

  it("honors an explicit OpenCode provider and model selection", () => {
    localStorage.setItem("backend_mode", "api");
    localStorage.setItem("provider_chain", "opencode");
    localStorage.setItem("credential:opencode_model", "opencode/kimi-k2.6");
    sessionStorage.setItem("opencode_api_key", "opencode-secret");

    const envs = readEnvsFromSettings();

    expect(envs).toEqual(expect.objectContaining({
      MUCHANIPO_PROVIDER_CHAIN: "opencode",
      MUCHANIPO_OPENCODE_MODEL: "opencode/kimi-k2.6",
      OPENCODE_API_KEY: "opencode-secret",
      OPENCODE_GO_API_KEY: "opencode-secret",
    }));
    expect(envs).not.toHaveProperty("XIAOMI_MIMO_API_KEY");
  });

  it("rejects a selected provider when its session credential is missing", () => {
    localStorage.setItem("backend_mode", "api");
    localStorage.setItem("provider_chain", "mimo");
    sessionStorage.setItem("opencode_api_key", "opencode-secret");

    expect(() => readEnvsFromSettings()).toThrow(
      /MiMo.*API Key/i,
    );
  });

  it("rejects an OpenCode model outside the supported namespace", () => {
    localStorage.setItem("backend_mode", "api");
    localStorage.setItem("provider_chain", "opencode");
    localStorage.setItem("credential:opencode_model", "kimi-k2.6");
    sessionStorage.setItem("opencode_api_key", "opencode-secret");

    expect(() => readEnvsFromSettings()).toThrow(
      /opencode\//i,
    );
  });

  it("blocks API execution when neither supported provider is configured", () => {
    localStorage.setItem("backend_mode", "api");

    expect(() => readEnvsFromSettings()).toThrow();
  });

  it("never restores provider credentials from persistent local storage", () => {
    localStorage.setItem("backend_mode", "api");
    localStorage.setItem("credential:mimo_api_key", "persisted-secret");
    localStorage.setItem("credential:opencode_api_key", "persisted-fallback-secret");

    expect(() => readEnvsFromSettings()).toThrow();
  });
});
