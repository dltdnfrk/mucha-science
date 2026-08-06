from src.evidence.artifact import EvidenceRef
from src.research.academic import sync_search


BACKEND_SOURCES = sync_search.ACADEMIC_SOURCE_NAMES


def test_default_limit_can_meet_minimum_evidence_floor() -> None:
    assert sync_search.DEFAULT_LIMIT >= 3


def _evidence(source: str) -> EvidenceRef:
    return EvidenceRef(
        id=f"{source}:test",
        source_url=f"https://example.test/{source}",
        source_title=source,
        quote=None,
        source_grade="A",
        provenance={
            "kind": source,
            "source_text": {"publication_year": 2024},
        },
    )


def _install_backends(monkeypatch, failing_sources: frozenset[str] = frozenset()) -> list[str]:
    calls: list[str] = []

    def make_backend(source: str):
        async def search(query: str, limit: int, **kwargs) -> list[EvidenceRef]:
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


def test_search_uses_all_backends_when_allowlist_is_unset(monkeypatch):
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


def test_selected_search_fns_includes_pubmed(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_ACADEMIC_SOURCES", "pubmed")

    assert sync_search._selected_search_fns() == (sync_search.pubmed_search,)


def test_biomedical_search_uses_filterable_sources_and_minimum_year(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def make_backend(source: str):
        async def search(query: str, limit: int, **kwargs) -> list[EvidenceRef]:
            calls.append((source, kwargs))
            return [_evidence(source)]

        return search

    monkeypatch.setattr(
        sync_search,
        "DEFAULT_SEARCH_FNS",
        tuple(make_backend(source) for source in BACKEND_SOURCES),
    )
    monkeypatch.setenv(
        "MUCHANIPO_ACADEMIC_SOURCES",
        "openalex,pubmed,crossref",
    )

    evidence = sync_search.search(
        "gut microbiome depression causal observational studies clinical trials since 2021",
        limit=1,
    )

    assert {source for source, _ in calls} == {"openalex", "pubmed"}
    assert {item.provenance["kind"] for item in evidence} == {"openalex", "pubmed"}
    assert dict(calls)["openalex"]["filter"] == "from_publication_date:2021-01-01"
    assert dict(calls)["pubmed"]["mindate"] == "2021"
    assert dict(calls)["pubmed"]["datetype"] == "pdat"
    assert dict(calls)["pubmed"]["sort"] == "relevance"


def test_biomedical_search_drops_backend_results_older_than_requested_window(monkeypatch):
    async def pubmed_search(query: str, limit: int, **kwargs) -> list[EvidenceRef]:
        return [
            EvidenceRef(
                id="pubmed:old",
                source_url="https://pubmed.ncbi.nlm.nih.gov/old/",
                source_title="Old trial",
                quote="gut microbiome depression clinical trial",
                source_grade="A",
                provenance={
                    "kind": "pubmed",
                    "source_text": {"publication_year": 2020},
                },
            ),
            EvidenceRef(
                id="pubmed:recent",
                source_url="https://pubmed.ncbi.nlm.nih.gov/recent/",
                source_title="Recent trial",
                quote="gut microbiome depression clinical trial",
                source_grade="A",
                provenance={
                    "kind": "pubmed",
                    "source_text": {"publication_year": 2024},
                },
            ),
        ]

    monkeypatch.setattr(
        sync_search,
        "DEFAULT_SEARCH_FNS",
        tuple(pubmed_search if source == "pubmed" else (lambda *args, **kwargs: None) for source in BACKEND_SOURCES),
    )
    monkeypatch.setenv("MUCHANIPO_ACADEMIC_SOURCES", "pubmed")

    evidence = sync_search.search(
        "gut microbiome depression causal observational studies clinical trials since 2021",
        limit=4,
    )

    assert [item.id for item in evidence] == ["pubmed:recent"]


def test_korean_biomedical_search_normalizes_backend_queries(monkeypatch):
    calls: dict[str, str] = {}

    def make_backend(source: str):
        async def search(query: str, limit: int, **kwargs) -> list[EvidenceRef]:
            calls[source] = query
            return [_evidence(source)]

        return search

    monkeypatch.setattr(
        sync_search,
        "DEFAULT_SEARCH_FNS",
        tuple(make_backend(source) for source in BACKEND_SOURCES),
    )
    monkeypatch.setenv("MUCHANIPO_ACADEMIC_SOURCES", "openalex,pubmed,crossref")

    sync_search.search(
        "최근 5년간 장내 미생물과 우울증의 인과 근거를 검토하고 관찰연구와 임상시험을 구분해줘.",
        limit=1,
    )

    assert set(calls) == {"openalex", "pubmed"}
    assert "장내" not in calls["openalex"]
    assert "gut microbiome depression" in calls["openalex"]
    assert '"gut microbiome"[Title/Abstract]' in calls["pubmed"]
