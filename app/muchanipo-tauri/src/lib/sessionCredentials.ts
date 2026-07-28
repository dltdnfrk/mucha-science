const SESSION_ONLY_CREDENTIAL_KEYS = new Set([
  "mimo_api_key",
  "anthropic_api_key",
  "openai_api_key",
  "gemini_api_key",
  "kimi_api_key",
  "opencode_api_key",
  "plannotator_key",
]);

export function readCredentialSetting(key: string): string {
  if (SESSION_ONLY_CREDENTIAL_KEYS.has(key)) {
    removeLegacyPersistentCredential(key);
    return sessionStorage.getItem(key) ?? "";
  }
  return localStorage.getItem(`credential:${key}`)
    ?? sessionStorage.getItem(key)
    ?? "";
}

export function writeCredentialSetting(key: string, value: string): void {
  if (SESSION_ONLY_CREDENTIAL_KEYS.has(key)) {
    removeLegacyPersistentCredential(key);
    if (value) sessionStorage.setItem(key, value);
    else sessionStorage.removeItem(key);
    return;
  }
  if (value) localStorage.setItem(`credential:${key}`, value);
  else localStorage.removeItem(`credential:${key}`);
  sessionStorage.removeItem(key);
}

export function purgeLegacyPersistentCredentials(): void {
  for (const key of SESSION_ONLY_CREDENTIAL_KEYS) {
    removeLegacyPersistentCredential(key);
  }
}

function removeLegacyPersistentCredential(key: string): void {
  localStorage.removeItem(`credential:${key}`);
}
