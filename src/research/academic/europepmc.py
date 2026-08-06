"""Europe PMC search backed by the vendored DeepMind science-skills CLI.

The pipeline contract (``async search`` / ``async get_paper`` returning
:class:`EvidenceRef` items) is preserved; the in-process HTTP client is
replaced by ``third_party/science-skills/literature_search_europepmc/scripts/europepmc_api.py``
(Apache 2.0, Google LLC).  The CLI writes the search result JSON to an
output file, so each call runs as a short-lived subprocess with a bounded
timeout.  The upstream search enforces an open-access filter.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from src.evidence.artifact import EvidenceRef

from .common import compact_text, evidence_ref, normalize_doi, source_grade_for_paper

_EUROPEPMC_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "third_party"
    / "science-skills"
    / "literature_search_europepmc"
    / "scripts"
    / "europepmc_api.py"
)
_CLI_TIMEOUT_SECONDS = 120


async def _run_europepmc_cli(args: list[str]) -> Any:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as output:
        output_path = output.name
    try:
        process = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, str(_EUROPEPMC_SCRIPT), "search", *args, "--output", output_path],
                capture_output=True,
                text=True,
                timeout=_CLI_TIMEOUT_SECONDS,
            ),
        )
        if process.returncode != 0:
            raise RuntimeError(
                f"europepmc CLI failed ({process.returncode}): {process.stderr.strip()[:300]}"
            )
        with open(output_path, encoding="utf-8") as handle:
            return json.load(handle)
    finally:
        os.unlink(output_path)


def _to_evidence(article: Mapping[str, Any]) -> EvidenceRef:
    source = str(article.get("source") or "")
    article_id = str(article.get("id") or "")
    doi = normalize_doi(str(article.get("doi") or ""))
    source_url = (
        f"https://europepmc.org/article/{source}/{article_id}"
        if source and article_id
        else (f"https://doi.org/{doi}" if doi else "")
    )
    title = compact_text([str(article.get("title") or "")])
    return evidence_ref(
        source="europepmc",
        paper_id=article_id or doi or "unknown",
        raw=dict(article),
        source_url=source_url,
        source_title=title,
        quote=compact_text([str(article.get("abstractText") or "")]),
        source_grade=source_grade_for_paper(doi=doi),
        doi=doi,
        journal=compact_text([str(article.get("journalTitle") or "")]),
    )


async def search(query: str, limit: int = 10) -> list[EvidenceRef]:
    if not query.strip():
        return []
    payload = await _run_europepmc_cli([query.strip(), "--max_results", str(limit)])
    articles = payload.get("results") if isinstance(payload, dict) else []
    return [_to_evidence(article) for article in articles if article]


async def get_paper(paper_id: str) -> EvidenceRef | None:
    payload = await _run_europepmc_cli([f"EXT_ID:{paper_id}", "--max_results", "1"])
    articles = payload.get("results") if isinstance(payload, dict) else []
    if not articles:
        return None
    return _to_evidence(articles[0])


async def get_citations(paper_id: str) -> list[EvidenceRef]:
    raise NotImplementedError(
        "Europe PMC citations are not exposed by the vendored science-skills "
        "europepmc_api search command."
    )
