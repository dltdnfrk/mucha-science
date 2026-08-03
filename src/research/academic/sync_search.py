"""Synchronous adapter for the async academic search clients."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import os
import threading
from typing import Any, Awaitable, Callable, List

from src.evidence.artifact import EvidenceRef

from .arxiv import search as arxiv_search
from .core import search as core_search
from .crossref import search as crossref_search
from .openalex import search as openalex_search
from .pubmed import search as pubmed_search
from .semantic_scholar import search as semantic_scholar_search
from .unpaywall import search as unpaywall_search


DEFAULT_LIMIT = 4
AsyncSearchFn = Callable[..., Awaitable[List[EvidenceRef]]]
ACADEMIC_SOURCE_NAMES = (
    "openalex",
    "pubmed",
    "semantic_scholar",
    "crossref",
    "core",
    "arxiv",
    "unpaywall",
)
DEFAULT_SEARCH_FNS = (
    openalex_search,
    pubmed_search,
    semantic_scholar_search,
    crossref_search,
    core_search,
    arxiv_search,
    unpaywall_search,
)


def _selected_search_fns() -> tuple[AsyncSearchFn, ...]:
    raw_allowlist = os.environ.get("MUCHANIPO_ACADEMIC_SOURCES")
    if raw_allowlist is None:
        return tuple(DEFAULT_SEARCH_FNS)
    selected = {
        item.strip().casefold().replace("-", "_")
        for item in raw_allowlist.split(",")
        if item.strip()
    }
    return tuple(
        search_fn
        for source_name, search_fn in zip(
            ACADEMIC_SOURCE_NAMES,
            DEFAULT_SEARCH_FNS,
            strict=False,
        )
        if source_name in selected
    )


def _selected_search_specs() -> tuple[tuple[str, AsyncSearchFn], ...]:
    selected = set(_selected_search_fns())
    return tuple(
        (source_name, search_fn)
        for source_name, search_fn in zip(
            ACADEMIC_SOURCE_NAMES,
            DEFAULT_SEARCH_FNS,
            strict=False,
        )
        if search_fn in selected
    )


def _search_kwargs(source_name: str, query: str) -> dict[str, Any]:
    from src.research.queries import minimum_publication_year

    minimum_year = minimum_publication_year(query)
    if minimum_year is None:
        return {}
    if source_name == "openalex":
        return {"filter": f"from_publication_date:{minimum_year}-01-01"}
    if source_name == "pubmed":
        return {
            "mindate": str(minimum_year),
            "maxdate": str(datetime.now(UTC).year),
            "datetype": "pdat",
            "sort": "relevance",
        }
    return {}


async def _search_one(
    source_name: str,
    search_fn: AsyncSearchFn,
    query: str,
    limit: int,
) -> list[EvidenceRef]:
    try:
        from src.research.queries import (
            biomedical_english_query,
            is_biomedical_query,
            pubmed_biomedical_query,
        )

        search_query = query
        if is_biomedical_query(query):
            if source_name == "pubmed":
                search_query = pubmed_biomedical_query(query)
            else:
                search_query = biomedical_english_query(query) or query
        return await search_fn(
            search_query,
            limit=limit,
            **_search_kwargs(source_name, query),
        )
    except Exception:  # noqa: BLE001 - one academic backend should not fail the whole search
        return []


async def _search_all(query: str, limit: int) -> list[EvidenceRef]:
    from src.research.queries import is_biomedical_query

    search_specs = _selected_search_specs()
    if is_biomedical_query(query):
        search_specs = tuple(
            spec for spec in search_specs if spec[0] in {"openalex", "pubmed"}
        )
    batches = await asyncio.gather(
        *(
            _search_one(source_name, search_fn, query, limit)
            for source_name, search_fn in search_specs
        )
    )
    evidence: list[EvidenceRef] = []
    for batch in batches:
        evidence.extend(batch)
    return evidence


def _run_sync(coro: Awaitable[list[EvidenceRef]]) -> list[EvidenceRef]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[EvidenceRef] = []
    error: BaseException | None = None

    def _runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive thread handoff
            error = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result


def search(query: str, limit: int = DEFAULT_LIMIT) -> list[EvidenceRef]:
    """Synchronously aggregate academic evidence across the existing async clients."""
    try:
        return _run_sync(_search_all(query, limit))
    except Exception:  # noqa: BLE001 - default live wiring must degrade gracefully
        return []
