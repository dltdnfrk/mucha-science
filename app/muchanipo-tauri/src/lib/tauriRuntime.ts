export function isTauriRuntime(): boolean {
  if (typeof window === "undefined") return false;
  const tauriWindow = window as Window & {
    __TAURI__?: unknown;
    __TAURI_INTERNALS__?: unknown;
  };
  return Boolean(tauriWindow.__TAURI__ || tauriWindow.__TAURI_INTERNALS__);
}

export function tauriOnlyError(action: string): Error {
  return new Error(`${action}은 Tauri 데스크톱 앱에서만 사용할 수 있습니다.`);
}
