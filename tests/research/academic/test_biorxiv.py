import asyncio
import json
import subprocess

import pytest

from src.research.academic import biorxiv

BIORXIV_PAPERS = [
    {
        "title": "Coral microbiome field study",
        "abstract": "We measured coral-associated bacteria across reefs.",
        "doi": "10.1101/2024.12.01.123456",
        "date": "2024-12-01",
        "category": "ecology",
    }
]


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_biorxiv_search_uses_date_window_and_keywords(monkeypatch):
    calls: list[list[str]] = []

    def capturing_run(args: list[str], **_: object):
        calls.append(args)
        return _completed(json.dumps(BIORXIV_PAPERS))

    monkeypatch.setattr(biorxiv.subprocess, "run", capturing_run)

    refs = asyncio.run(biorxiv.search("coral reef microbiome", limit=3))

    assert "--start_date" in calls[0]
    assert "--end_date" in calls[0]
    assert "--keywords" in calls[0]
    assert "coral" in calls[0]
    assert "--include_abstracts" in calls[0]
    assert len(refs) == 1
    ref = refs[0]
    assert ref.source_url == "https://doi.org/10.1101/2024.12.01.123456"
    assert ref.source_title == "Coral microbiome field study"
    assert ref.source_grade == "B"
    assert ref.provenance["kind"] == "biorxiv"


def test_biorxiv_search_empty_or_short_query_skips_cli(monkeypatch):
    def unexpected_run(*_: object):
        raise AssertionError("CLI must not run without usable keywords")

    monkeypatch.setattr(biorxiv.subprocess, "run", unexpected_run)

    assert asyncio.run(biorxiv.search("   ")) == []
    assert asyncio.run(biorxiv.search("a b")) == []


def test_biorxiv_cli_failure_raises(monkeypatch):
    def failing_run(args: list[str], **_: object):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(biorxiv.subprocess, "run", failing_run)

    with pytest.raises(RuntimeError, match="biorxiv CLI failed"):
        asyncio.run(biorxiv.search("coral reef"))


def test_biorxiv_get_paper_uses_doi_script(monkeypatch):
    calls: list[list[str]] = []

    def capturing_run(args: list[str], **_: object):
        calls.append(args)
        return _completed(json.dumps(BIORXIV_PAPERS[0]))

    monkeypatch.setattr(biorxiv.subprocess, "run", capturing_run)

    ref = asyncio.run(biorxiv.get_paper("10.1101/2024.12.01.123456"))

    assert ref is not None
    assert "--doi" in calls[0]
    assert calls[0][calls[0].index("--doi") + 1] == "10.1101/2024.12.01.123456"


def test_biorxiv_get_citations_not_supported():
    with pytest.raises(NotImplementedError):
        asyncio.run(biorxiv.get_citations("10.1101/2024.12.01.123456"))
