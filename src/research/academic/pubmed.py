"""PubMed search backed by the vendored DeepMind science-skills CLI.

The pipeline contract (``async search`` / ``async get_paper`` returning
:class:`EvidenceRef` items) is preserved; the in-process HTTP client is
replaced by ``third_party/science-skills/pubmed_database/scripts/pubmed_api.py``
(Apache 2.0, Google LLC).  The CLI writes JSON to an output file, so each
call runs as a short-lived subprocess with a bounded timeout.  PubMed
citations are not exposed by the vendored CLI, so ``get_citations`` raises
:class:`NotImplementedError` instead of silently degrading.
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

_PUBMED_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "third_party"
    / "science-skills"
    / "pubmed_database"
    / "scripts"
    / "pubmed_api.py"
)
_CLI_TIMEOUT_SECONDS = 120


async def _run_pubmed_cli(args: list[str]) -> Any:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as output:
        output_path = output.name
    try:
        process = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, str(_PUBMED_SCRIPT), output_path, *args],
                capture_output=True,
                text=True,
                timeout=_CLI_TIMEOUT_SECONDS,
            ),
        )
        if process.returncode != 0:
            raise RuntimeError(
                f"pubmed_api CLI failed ({process.returncode}): {process.stderr.strip()[:300]}"
            )
        with open(output_path, encoding="utf-8") as handle:
            return json.load(handle)
    finally:
        os.unlink(output_path)


def _to_evidence(article: Mapping[str, Any]) -> EvidenceRef:
    pmid = str(article.get("pmid") or "")
    doi = normalize_doi(str(article.get("doi") or ""))
    source_url = (
        f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        if pmid
        else (f"https://doi.org/{doi}" if doi else "")
    )
    title = compact_text([str(article.get("title") or "")])
    return evidence_ref(
        source="pubmed",
        paper_id=pmid or doi or "unknown",
        raw=dict(article),
        source_url=source_url,
        source_title=title,
        quote=compact_text([str(article.get("abstract") or "")]),
        source_grade=source_grade_for_paper(doi=doi),
        doi=doi,
        journal=compact_text([str(article.get("journal") or "")]),
    )


async def search(query: str, limit: int = 10) -> list[EvidenceRef]:
    if not query.strip():
        return []
    pmids = await _run_pubmed_cli([
        "search_pubmed",
        query.strip(),
        "--max_results",
        str(limit),
    ])
    if not pmids:
        return []
    articles = await _run_pubmed_cli([
        "fetch_article_abstracts",
        "--pmids",
        ",".join(str(pmid) for pmid in pmids[:limit]),
    ])
    return [_to_evidence(article) for article in articles if article]


async def get_paper(paper_id: str) -> EvidenceRef | None:
    articles = await _run_pubmed_cli(["fetch_article_abstracts", "--pmids", paper_id])
    if not articles:
        return None
    return _to_evidence(articles[0])


async def get_citations(paper_id: str) -> list[EvidenceRef]:
    raise NotImplementedError(
        "PubMed citations require the NCBI E-utilities citedby query, which the "
        "vendored science-skills pubmed_api CLI does not expose."
    )
