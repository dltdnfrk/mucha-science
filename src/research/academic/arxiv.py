"""arXiv search backed by the vendored DeepMind science-skills CLI.

The pipeline contract (``async search`` / ``async get_paper`` returning
:class:`EvidenceRef` items) is preserved; the in-process HTTP client is
replaced by ``third_party/science-skills/literature_search_arxiv/scripts/search_arxiv.py``
(Apache 2.0, Google LLC).  The CLI prints one JSON document per paper to
stdout, so the wrapper keeps the last (cumulative) document.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from src.evidence.artifact import EvidenceRef

from .common import compact_text, evidence_ref, normalize_doi, source_grade_for_paper

_ARXIV_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "third_party"
    / "science-skills"
    / "literature_search_arxiv"
    / "scripts"
    / "search_arxiv.py"
)
_CLI_TIMEOUT_SECONDS = 120


async def _run_arxiv_cli(args: list[str]) -> list[dict[str, Any]]:
    process = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: subprocess.run(
            [sys.executable, str(_ARXIV_SCRIPT), *args],
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_SECONDS,
        ),
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"search_arxiv CLI failed ({process.returncode}): {process.stderr.strip()[:300]}"
        )
    documents = [
        json.loads(line)
        for line in process.stdout.splitlines()
        if line.strip().startswith("{")
    ]
    if not documents:
        return []
    return documents[-1].get("papers") or []


def _to_evidence(paper: Mapping[str, Any]) -> EvidenceRef:
    arxiv_id = str(paper.get("id") or "")
    doi = normalize_doi(str(paper.get("doi") or ""))
    source_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""
    title = compact_text([str(paper.get("title") or "")])
    return evidence_ref(
        source="arxiv",
        paper_id=arxiv_id or doi or "unknown",
        raw=dict(paper),
        source_url=source_url,
        source_title=title,
        quote=compact_text([str(paper.get("summary") or "")]),
        source_grade=source_grade_for_paper(doi=doi),
        doi=doi,
        journal=compact_text([str(paper.get("journal_ref") or "")]),
    )


async def search(query: str, limit: int = 10) -> list[EvidenceRef]:
    if not query.strip():
        return []
    papers = await _run_arxiv_cli([
        "--query",
        query.strip(),
        "--max_results",
        str(limit),
    ])
    return [_to_evidence(paper) for paper in papers if paper.get("title")]


async def get_paper(paper_id: str) -> EvidenceRef | None:
    papers = await _run_arxiv_cli(["--id_list", paper_id])
    if not papers:
        return None
    return _to_evidence(papers[0])


async def get_citations(paper_id: str) -> list[EvidenceRef]:
    raise NotImplementedError(
        "arXiv citations are not exposed by the vendored science-skills "
        "search_arxiv CLI."
    )
