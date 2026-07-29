const SENSITIVE_QUERY_MARKERS = [
  "apikey",
  "accesstoken",
  "authtoken",
  "authorization",
  "bearer",
  "credential",
  "password",
  "secret",
  "signature",
  "token",
] as const;

const SENSITIVE_QUERY_KEYS = new Set(["auth", "key"]);

const HTTP_URL_IN_TEXT = /https?:\/\/[^\s<>{}\[\]()"']+/giu;

export function isSafeExternalHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:")
      && parsed.username.length === 0
      && parsed.password.length === 0
      && [...parsed.searchParams.keys()].every((key) => !isSensitiveQueryKey(key))
      && !hasSensitiveFragmentParameter(parsed.hash)
    );
  } catch {
    return false;
  }
}

export function sanitizeExternalReference(value: string): string {
  if (isSafeExternalHttpUrl(value)) return value;

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return value;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return value;

  parsed.username = "";
  parsed.password = "";
  for (const key of [...parsed.searchParams.keys()]) {
    if (isSensitiveQueryKey(key)) parsed.searchParams.delete(key);
  }
  parsed.hash = sanitizeFragment(parsed.hash);
  return parsed.toString();
}

export function sanitizeMarkdownExternalReferences(value: string): string {
  return value.replace(
    HTTP_URL_IN_TEXT,
    (url) => sanitizeExternalReference(url),
  );
}

function isSensitiveQueryKey(key: string): boolean {
  const normalized = key.toLowerCase().replaceAll(/[-_.]/g, "");
  return (
    SENSITIVE_QUERY_KEYS.has(normalized)
    || SENSITIVE_QUERY_MARKERS.some((marker) => normalized.includes(marker))
  );
}

function hasSensitiveFragmentParameter(hash: string): boolean {
  if (!hash.includes("=")) return false;
  return [...new URLSearchParams(hash.slice(1)).keys()].some(isSensitiveQueryKey);
}

function sanitizeFragment(hash: string): string {
  if (!hasSensitiveFragmentParameter(hash)) return hash;
  const parameters = new URLSearchParams(hash.slice(1));
  for (const key of [...parameters.keys()]) {
    if (isSensitiveQueryKey(key)) parameters.delete(key);
  }
  const safeFragment = parameters.toString();
  return safeFragment ? `#${safeFragment}` : "";
}
