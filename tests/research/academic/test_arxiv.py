import asyncio
import json
import subprocess

import pytest

from src.research.academic import arxiv

ARXIV_PAPERS = [
    {
        "id": "2412.12345",
        "title": "Evidence-backed AI review",
        "summary": "We show that structured evidence improves review reliability.",
        "published": "2024-12-01T00:00:00Z",
        "authors": ["A. Author"],
        "pdf_url": "https://arxiv.org/pdf/2412.12345",
        "doi": "10.48550/arXiv.2412.12345",
        "journal_ref": None,
    }
]


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_arxiv_search_invokes_cli_and_maps_papers(monkeypatch):
    calls: list[list[str]] = []
    documents = "".join(json.dumps({"status": "success", "results_count": i + 1, "papers": ARXIV_PAPERS}) + "\n" for i in range(1))

    def capturing_run(args: list[str], **_: object):
        calls.append(args)
        return _completed(documents)

    monkeypatch.setattr(arxiv.subprocess, "run", capturing_run)

    refs = asyncio.run(arxiv.search("evidence review", limit=5))

    assert "--query" in calls[0]
    assert calls[0][calls[0].index("--query") + 1] == "evidence review"
    assert "--max_results" in calls[0]
    assert len(refs) == 1
    ref = refs[0]
    assert ref.source_url == "https://arxiv.org/abs/2412.12345"
    assert ref.source_title == "Evidence-backed AI review"
    assert "structured evidence" in (ref.quote or "")
    assert ref.source_grade == "A"
    assert ref.provenance["kind"] == "arxiv"


def test_arxiv_search_takes_last_cumulative_document(monkeypatch):
    documents = (
        json.dumps({"status": "success", "results_count": 1, "papers": ARXIV_PAPERS[:1]}) + "\n"
        + json.dumps({"status": "success", "results_count": 1, "papers": ARXIV_PAPERS}) + "\n"
    )

    def capturing_run(args: list[str], **_: object):
        return _completed(documents)

    monkeypatch.setattr(arxiv.subprocess, "run", capturing_run)

    refs = asyncio.run(arxiv.search("query", limit=5))
    assert len(refs) == 1


def test_arxiv_search_empty_query_skips_cli(monkeypatch):
    def unexpected_run(*_: object):
        raise AssertionError("CLI must not run for an empty query")

    monkeypatch.setattr(arxiv.subprocess, "run", unexpected_run)

    assert asyncio.run(arxiv.search("   ")) == []


def test_arxiv_cli_failure_raises(monkeypatch):
    def failing_run(args: list[str], **_: object):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(arxiv.subprocess, "run", failing_run)

    with pytest.raises(RuntimeError, match="search_arxiv CLI failed"):
        asyncio.run(arxiv.search("query"))


def test_arxiv_get_paper_uses_id_list(monkeypatch):
    calls: list[list[str]] = []

    def capturing_run(args: list[str], **_: object):
        calls.append(args)
        return _completed(json.dumps({"status": "success", "results_count": 1, "papers": ARXIV_PAPERS}) + "\n")

    monkeypatch.setattr(arxiv.subprocess, "run", capturing_run)

    ref = asyncio.run(arxiv.get_paper("2412.12345"))

    assert ref is not None
    assert "--id_list" in calls[0]
    assert calls[0][calls[0].index("--id_list") + 1] == "2412.12345"


def test_arxiv_get_citations_not_supported():
    with pytest.raises(NotImplementedError):
        asyncio.run(arxiv.get_citations("2412.12345"))
