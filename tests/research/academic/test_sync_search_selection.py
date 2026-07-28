from src.evidence.artifact import EvidenceRef
from src.research.academic import sync_search


BACKEND_SOURCES = (
    "openalex",
    "semantic_scholar",
    "crossref",
    "core",
    "arxiv",
    "unpaywall",
)


def _evidence(source: str) -> EvidenceRef:
    return EvidenceRef(
        id=f"{source}:test",
        source_url=f"https://example.test/{source}",
        source_title=source,
        quote=None,
        source_grade="A",
        provenance={"kind": source},
    )


def _install_backends(monkeypatch, failing_sources: frozenset[str] = frozenset()) -> list[str]:
    calls: list[str] = []

    def make_backend(source: str):
        async def search(query: str, limit: int) -> list[EvidenceRef]:
            calls.append(source)
            if source in failing_sources:
                raise RuntimeError(f"{source} unavailable")
            return [_evidence(source)]

        search.__name__ = f"{source}_search"
        return search

    monkeypatch.setattr(
        sync_search,
        "DEFAULT_SEARCH_FNS",
        tuple(make_backend(source) for source in BACKEND_SOURCES),
    )
    return calls


def test_search_uses_only_allowlisted_academic_backends(monkeypatch):
    # Given: network-free backends and a selected known subset.
    calls = _install_backends(monkeypatch)
    monkeypatch.setenv("MUCHANIPO_ACADEMIC_SOURCES", "openalex,arxiv")

    # When: the synchronous academic search runs.
    evidence = sync_search.search("agent memory", limit=1)

    # Then: only the selected backend callables contribute evidence.
    assert set(calls) == {"openalex", "arxiv"}
    assert {item.provenance["kind"] for item in evidence} == {"openalex", "arxiv"}


def test_search_invokes_no_backend_for_unsupported_only_allowlist(monkeypatch):
    # Given: network-free backends and only unsupported source names.
    calls = _install_backends(monkeypatch)
    monkeypatch.setenv("MUCHANIPO_ACADEMIC_SOURCES", "unknown,unsupported")

    # When: the synchronous academic search runs.
    evidence = sync_search.search("agent memory", limit=1)

    # Then: it returns no evidence rather than falling back to every backend.
    assert calls == []
    assert evidence == []


def test_search_uses_all_six_backends_when_allowlist_is_unset(monkeypatch):
    # Given: network-free backends and no transient allowlist.
    calls = _install_backends(monkeypatch)
    monkeypatch.delenv("MUCHANIPO_ACADEMIC_SOURCES", raising=False)

    # When: the synchronous academic search runs.
    evidence = sync_search.search("agent memory", limit=1)

    # Then: the existing six-backend behavior is preserved.
    assert set(calls) == set(BACKEND_SOURCES)
    assert {item.provenance["kind"] for item in evidence} == set(BACKEND_SOURCES)


def test_search_keeps_allowlisted_backend_failure_isolated(monkeypatch):
    # Given: one selected backend fails while another selected backend succeeds.
    calls = _install_backends(monkeypatch, failing_sources=frozenset({"openalex"}))
    monkeypatch.setenv("MUCHANIPO_ACADEMIC_SOURCES", "openalex,arxiv")

    # When: the synchronous academic search runs.
    evidence = sync_search.search("agent memory", limit=1)

    # Then: the successful selected backend still returns its evidence.
    assert set(calls) == {"openalex", "arxiv"}
    assert [item.provenance["kind"] for item in evidence] == ["arxiv"]
