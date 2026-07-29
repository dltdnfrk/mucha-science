"""Citation-only search adapters for provider-native web grounding.

Provider-generated prose is never returned as evidence. A hit is emitted only
when the provider response includes machine-readable source metadata with an
HTTP(S) URL and text explicitly attached to that source.
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from src.execution.models import ModelResult, Provider


DEFAULT_LIMIT = 4
_TRUTHY = frozenset({"1", "true", "yes"})
_ANTHROPIC_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 4,
}


def search(
    query: str,
    *,
    providers: Iterable[Provider] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Collect only citation-backed provider search results."""
    normalized_query = " ".join(str(query or "").split())
    if not normalized_query:
        return []
    active_providers = tuple(providers) if providers is not None else _providers_from_environment()
    if not active_providers:
        return []

    hits: list[dict[str, Any]] = []
    for provider in active_providers:
        try:
            result = _call_provider(provider, normalized_query)
        except Exception:
            continue
        hits.extend(_hits_from_result(result))
    return _deduplicate(hits, max(1, int(limit)))


def _providers_from_environment() -> tuple[Provider, ...]:
    if os.getenv("MUCHANIPO_PROVIDER_SEARCH", "").strip().lower() not in _TRUTHY:
        return ()
    configured = {
        name.strip().lower()
        for name in os.getenv(
            "MUCHANIPO_PROVIDER_SEARCH_PROVIDERS",
            "gemini,anthropic",
        ).split(",")
        if name.strip()
    }
    providers: list[Provider] = []
    if "gemini" in configured:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            from src.execution.providers.gemini import GeminiProvider

            providers.append(
                GeminiProvider(api_key=api_key, offline=False, use_cli=False)
            )
    if "anthropic" in configured:
        api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
        if api_key:
            from src.execution.providers.anthropic import AnthropicProvider

            providers.append(
                AnthropicProvider(api_key=api_key, offline=False, use_cli=False)
            )
    return tuple(providers)


def _call_provider(provider: Provider, query: str) -> ModelResult:
    prompt = (
        "Search the web for evidence relevant to the research query below. "
        "Return only claims supported by the provider's native source citations.\n\n"
        f"Research query: {query}"
    )
    if str(getattr(provider, "name", "")).lower() == "anthropic":
        return provider.call(
            "research",
            prompt,
            tools=[dict(_ANTHROPIC_TOOL)],
            allow_fallback=False,
        )
    return provider.call("research", prompt, search_grounding=True)


def _hits_from_result(result: ModelResult) -> list[dict[str, Any]]:
    raw = _to_plain(result.raw)
    provider = str(result.provider or "").lower()
    if provider == "gemini":
        return _gemini_hits(raw, result)
    if provider == "anthropic":
        return _anthropic_hits(raw, result)
    return []


def _gemini_hits(raw: Any, result: ModelResult) -> list[dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return []
    candidates = raw.get("candidates")
    if not isinstance(candidates, list):
        return []
    hits: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        metadata = candidate.get("groundingMetadata")
        if not isinstance(metadata, Mapping):
            continue
        chunks = metadata.get("groundingChunks")
        supports = metadata.get("groundingSupports")
        if not isinstance(chunks, list) or not isinstance(supports, list):
            continue
        for support in supports:
            if not isinstance(support, Mapping):
                continue
            segment = support.get("segment")
            text = segment.get("text") if isinstance(segment, Mapping) else None
            if not isinstance(text, str) or not text.strip():
                continue
            indices = support.get("groundingChunkIndices")
            if not isinstance(indices, list):
                continue
            for index in indices:
                if not isinstance(index, int) or not 0 <= index < len(chunks):
                    continue
                chunk = chunks[index]
                web = chunk.get("web") if isinstance(chunk, Mapping) else None
                if not isinstance(web, Mapping):
                    continue
                hit = _citation_hit(
                    provider="gemini",
                    model=result.model,
                    url=web.get("uri"),
                    title=web.get("title"),
                    text=text,
                )
                if hit is not None:
                    hits.append(hit)
    return hits


def _anthropic_hits(raw: Any, result: ModelResult) -> list[dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return []
    content = raw.get("content")
    if not isinstance(content, list):
        return []
    hits: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        citations = block.get("citations")
        if not isinstance(citations, list):
            continue
        for citation in citations:
            if not isinstance(citation, Mapping):
                continue
            if citation.get("type") != "web_search_result_location":
                continue
            hit = _citation_hit(
                provider="anthropic",
                model=result.model,
                url=citation.get("url"),
                title=citation.get("title"),
                text=citation.get("cited_text"),
            )
            if hit is not None:
                hits.append(hit)
    return hits


def _citation_hit(
    *,
    provider: str,
    model: str,
    url: Any,
    title: Any,
    text: Any,
) -> dict[str, Any] | None:
    safe_url = _safe_url(url)
    cited_text = " ".join(text.split()) if isinstance(text, str) else ""
    if safe_url is None or not cited_text:
        return None
    source_title = " ".join(title.split()) if isinstance(title, str) else ""
    return {
        "kind": "provider_search",
        "provider": provider,
        "model": model,
        "url": safe_url,
        "title": source_title or safe_url,
        "text": cited_text,
        "score": 0.65,
    }


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _deduplicate(hits: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        key = str(hit["url"]).rstrip("/").casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(hit)
        if len(result) >= limit:
            break
    return result


def _to_plain(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_plain(model_dump())
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return {
            str(key): _to_plain(item)
            for key, item in attributes.items()
            if not str(key).startswith("_")
        }
    return None
