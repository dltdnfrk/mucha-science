import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from src.research.academic import europepmc

EUROPEPMC_RESULTS = {
    "hitCount": 1,
    "results": [
        {
            "id": "PMC123456",
            "source": "PMC",
            "pmid": "11223344",
            "title": "Open-access evidence review",
            "authorString": "Kim J",
            "journalTitle": "eLife",
            "abstractText": "BACKGROUND: Review of open evidence.\nRESULTS: Positive.",
            "doi": "10.7554/eLife.00123",
        }
    ],
}


def _fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    output_path = args[args.index("--output") + 1]
    Path(output_path).write_text(json.dumps(EUROPEPMC_RESULTS), encoding="utf-8")
    return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")


def test_europepmc_search_invokes_cli_and_maps_articles(monkeypatch):
    calls: list[list[str]] = []

    def capturing_run(args: list[str], **kwargs: object):
        calls.append(args)
        return _fake_run(args, **kwargs)

    monkeypatch.setattr(europepmc.subprocess, "run", capturing_run)

    refs = asyncio.run(europepmc.search("open evidence", limit=3))

    assert calls[0][2] == "search"
    assert calls[0][3] == "open evidence"
    assert "--max_results" in calls[0]
    assert "--output" in calls[0]
    assert len(refs) == 1
    ref = refs[0]
    assert ref.source_url == "https://europepmc.org/article/PMC/PMC123456"
    assert ref.source_title == "Open-access evidence review"
    assert "Positive" in (ref.quote or "")
    assert ref.source_grade == "A"
    assert ref.provenance["kind"] == "europepmc"


def test_europepmc_search_empty_query_skips_cli(monkeypatch):
    def unexpected_run(*_: object):
        raise AssertionError("CLI must not run for an empty query")

    monkeypatch.setattr(europepmc.subprocess, "run", unexpected_run)

    assert asyncio.run(europepmc.search("   ")) == []


def test_europepmc_cli_failure_raises(monkeypatch):
    def failing_run(args: list[str], **_: object):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(europepmc.subprocess, "run", failing_run)

    with pytest.raises(RuntimeError, match="europepmc CLI failed"):
        asyncio.run(europepmc.search("query"))


def test_europepmc_get_paper_uses_ext_id(monkeypatch):
    calls: list[list[str]] = []

    def capturing_run(args: list[str], **kwargs: object):
        calls.append(args)
        return _fake_run(args, **kwargs)

    monkeypatch.setattr(europepmc.subprocess, "run", capturing_run)

    ref = asyncio.run(europepmc.get_paper("PMC123456"))

    assert ref is not None
    assert calls[0][3] == "EXT_ID:PMC123456"


def test_europepmc_get_citations_not_supported():
    with pytest.raises(NotImplementedError):
        asyncio.run(europepmc.get_citations("PMC123456"))
