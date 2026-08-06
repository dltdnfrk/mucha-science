import asyncio
import json
import subprocess

import pytest

from src.research.academic import openalex

OPENALEX_WORKS = {
    "meta": {"count": 1},
    "results": [
        {
            "id": "https://openalex.org/W123",
            "display_name": "Deep sea carbon capture",
            "doi": "https://doi.org/10.1234/openalex-test",
            "abstract_inverted_index": {
                "capture": [1],
                "carbon": [0],
            },
            "publication_year": 2024,
            "primary_location": {
                "source": {"display_name": "Nature Climate Change"},
            },
        },
    ],
}


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_openalex_search_invokes_cli_and_maps_works(monkeypatch):
    calls: list[list[str]] = []

    def capturing_run(args: list[str], **_: object):
        calls.append(args)
        return _completed(json.dumps(OPENALEX_WORKS))

    monkeypatch.setattr(openalex, "_openalex_key_present", lambda: True)
    monkeypatch.setattr(openalex.subprocess, "run", capturing_run)

    refs = asyncio.run(openalex.search("carbon capture", limit=3))

    assert calls[0][2] == "filter"
    assert calls[0][3] == "works"
    assert "--search" in calls[0]
    assert calls[0][calls[0].index("--search") + 1] == "carbon capture"
    assert len(refs) == 1
    ref = refs[0]
    assert ref.source_url == "https://doi.org/10.1234/openalex-test"
    assert ref.source_title == "Deep sea carbon capture"
    assert ref.quote == "carbon capture"
    assert ref.source_grade == "A"
    assert ref.provenance["kind"] == "openalex"


def test_openalex_search_empty_query_skips_cli(monkeypatch):
    def unexpected_run(*_: object):
        raise AssertionError("CLI must not run for an empty query")

    monkeypatch.setattr(openalex.subprocess, "run", unexpected_run)

    assert asyncio.run(openalex.search("  ")) == []


def test_openalex_cli_failure_raises(monkeypatch):
    def failing_run(args: list[str], **_: object):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="rate limited")

    monkeypatch.setattr(openalex, "_openalex_key_present", lambda: True)
    monkeypatch.setattr(openalex.subprocess, "run", failing_run)

    with pytest.raises(RuntimeError, match="openalex CLI failed"):
        asyncio.run(openalex.search("query"))


def test_openalex_targeting_queries_map_entities_without_async_loop(monkeypatch):
    from src.research.academic.openalex import query_institutions, query_journals, query_seed_papers

    def fake_get(self, endpoint: str, params: dict | None = None, **_: object):
        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"results": [{"display_name": f"entity-{endpoint}", "doi": "10.1/seed"}]}

        return Response()

    monkeypatch.setattr(openalex, "_skip_live_targeting", lambda: False)
    monkeypatch.setattr("httpx.Client.get", fake_get)

    institutions, provenance = query_institutions(["biology"])
    assert institutions == ["entity-/institutions"]
    assert provenance[0]["status"] == "ok"

    journals, _ = query_journals(["biology"])
    assert journals == ["entity-/sources"]

    papers, _ = query_seed_papers(["biology"])
    assert papers == ["10.1/seed"]


def test_openalex_targeting_skips_during_pytest(monkeypatch):
    from src.research.academic.openalex import query_institutions

    def unexpected_get(*_: object):
        raise AssertionError("targeting must not hit the network during pytest")

    monkeypatch.setattr(openalex, "_skip_live_targeting", lambda: True)
    monkeypatch.setattr("httpx.Client.get", unexpected_get)

    names, provenance = query_institutions(["biology"])
    assert names == []
    assert provenance[0]["status"] == "skipped"


def test_openalex_search_without_key_skips_cli(monkeypatch):
    def unexpected_run(*_: object):
        raise AssertionError("CLI must not run without an OpenAlex API key")

    monkeypatch.setattr(openalex, "_openalex_key_present", lambda: False)
    monkeypatch.setattr(openalex.subprocess, "run", unexpected_run)

    assert asyncio.run(openalex.search("carbon capture")) == []
    assert asyncio.run(openalex.get_paper("W123")) is None
