import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from src.research.academic import pubmed

PUBMED_ARTICLES = [
    {
        "pmid": "12345678",
        "title": "Grounded biomedical evidence",
        "authors": ["Doe J"],
        "journal": "Nature Medicine",
        "pubdate": "2024 Mar 12",
        "doi": "10.1000/pubmed-test",
        "abstract": "BACKGROUND: First section.\nRESULTS: Measured effect was significant.",
    },
]


def _fake_pubmed_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    output_path = args[2]
    func = args[3]
    if func == "search_pubmed":
        payload = ["12345678"]
    else:
        payload = PUBMED_ARTICLES
    Path(output_path).write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")


def test_pubmed_search_invokes_cli_and_maps_articles(monkeypatch):
    calls: list[list[str]] = []

    def capturing_run(args: list[str], **kwargs: object):
        calls.append(args)
        return _fake_pubmed_run(args, **kwargs)

    monkeypatch.setattr(pubmed.subprocess, "run", capturing_run)

    refs = asyncio.run(pubmed.search("BRCA1 breast cancer", limit=5))

    assert calls[0][3] == "search_pubmed"
    assert calls[0][4] == "BRCA1 breast cancer"
    assert "--max_results" in calls[0]
    assert calls[1][3] == "fetch_article_abstracts"
    assert calls[1][5] == "12345678"
    assert len(refs) == 1
    ref = refs[0]
    assert ref.source_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert ref.source_title == "Grounded biomedical evidence"
    assert "Measured effect was significant" in (ref.quote or "")
    assert ref.source_grade == "A"
    assert ref.provenance["kind"] == "pubmed"


def test_pubmed_search_empty_query_skips_cli(monkeypatch):
    def unexpected_run(*_: object):
        raise AssertionError("CLI must not run for an empty query")

    monkeypatch.setattr(pubmed.subprocess, "run", unexpected_run)

    assert asyncio.run(pubmed.search("   ")) == []


def test_pubmed_search_no_hits_returns_empty(monkeypatch):
    def no_hits_run(args: list[str], **_: object):
        Path(args[2]).write_text("[]", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(pubmed.subprocess, "run", no_hits_run)

    assert asyncio.run(pubmed.search("nothing found")) == []


def test_pubmed_cli_failure_raises(monkeypatch):
    def failing_run(args: list[str], **_: object):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(pubmed.subprocess, "run", failing_run)

    with pytest.raises(RuntimeError, match="pubmed_api CLI failed"):
        asyncio.run(pubmed.search("query"))


def test_pubmed_get_paper_maps_single_article(monkeypatch):
    monkeypatch.setattr(pubmed.subprocess, "run", _fake_pubmed_run)

    ref = asyncio.run(pubmed.get_paper("12345678"))

    assert ref is not None
    assert ref.source_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"


def test_pubmed_get_citations_not_supported():
    with pytest.raises(NotImplementedError):
        asyncio.run(pubmed.get_citations("12345678"))
