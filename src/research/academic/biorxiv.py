"""bioRxiv search backed by the vendored DeepMind science-skills CLI.

The pipeline contract (``async search`` returning :class:`EvidenceRef`
items) is preserved; the in-process HTTP client is replaced by
``third_party/science-skills/literature_search_biorxiv/scripts/search_by_dates.py``
(Apache 2.0, Google LLC).  bioRxiv's public API only supports date-range
searches, so a query is searched over a trailing 180-day window with the
first keywords of the query as a local title/abstract filter.  Abstracts
are included in the CLI output.
"""

import asyncio
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from src.evidence.artifact import EvidenceRef

from .common import compact_text, evidence_ref, normalize_doi, source_grade_for_paper

_BIORXIV_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "third_party"
    / "science-skills"
    / "literature_search_biorxiv"
    / "scripts"
    / "search_by_dates.py"
)
_BIORXIV_DOI_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "third_party"
    / "science-skills"
    / "literature_search_biorxiv"
    / "scripts"
    / "search_by_doi.py"
)
_CLI_TIMEOUT_SECONDS = 120
_SEARCH_WINDOW_DAYS = 180
_MAX_KEYWORDS = 5


async def _run_cli(script: Path, args: list[str]) -> list[dict[str, Any]]:
    process = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_SECONDS,
        ),
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"biorxiv CLI failed ({process.returncode}): {process.stderr.strip()[:300]}"
        )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else [payload]


def _keywords_for_query(query: str) -> list[str]:
    return [word for word in query.split() if len(word) > 2][:_MAX_KEYWORDS]


def _to_evidence(paper: Mapping[str, Any]) -> EvidenceRef:
    doi = normalize_doi(str(paper.get("doi") or ""))
    source_url = f"https://doi.org/{doi}" if doi else ""
    title = compact_text([str(paper.get("title") or "")])
    return evidence_ref(
        source="biorxiv",
        paper_id=doi or str(paper.get("date") or "unknown"),
        raw=dict(paper),
        source_url=source_url,
        source_title=title,
        quote=compact_text([str(paper.get("abstract") or "")]),
        source_grade=source_grade_for_paper(doi=doi, peer_reviewed=False),
        doi=doi,
        institution="bioRxiv",
    )


async def search(query: str, limit: int = 10) -> list[EvidenceRef]:
    if not query.strip():
        return []
    keywords = _keywords_for_query(query)
    if not keywords:
        return []
    end = date.today()
    start = end - timedelta(days=_SEARCH_WINDOW_DAYS)
    papers = await _run_cli(
        _BIORXIV_SCRIPT,
        [
            "--start_date",
            start.isoformat(),
            "--end_date",
            end.isoformat(),
            "--keywords",
            *keywords,
            "--include_abstracts",
        ],
    )
    return [_to_evidence(paper) for paper in papers[:limit] if paper.get("title")]


async def get_paper(paper_id: str) -> EvidenceRef | None:
    papers = await _run_cli(_BIORXIV_DOI_SCRIPT, ["--doi", paper_id])
    if not papers:
        return None
    return _to_evidence(papers[0])


async def get_citations(paper_id: str) -> list[EvidenceRef]:
    raise NotImplementedError(
        "bioRxiv citations are not exposed by the vendored science-skills CLIs."
    )
