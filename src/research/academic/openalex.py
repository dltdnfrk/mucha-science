"""OpenAlex search backed by the vendored DeepMind science-skills CLI.

The pipeline contract (``async search`` / ``async get_paper`` returning
:class:`EvidenceRef` items) is preserved; the in-process HTTP client is
replaced by ``third_party/science-skills/literature_search_openalex/openalex_cli.py``
(Apache 2.0, Google LLC).  The CLI prints the OpenAlex API response JSON to
stdout; the wrapper extracts the ``results`` list.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import httpx

from src.evidence.artifact import EvidenceRef

from .common import (
    compact_text,
    contact_email,
    evidence_ref,
    normalize_doi,
    source_grade_for_paper,
)

_OPENALEX_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "third_party"
    / "science-skills"
    / "literature_search_openalex"
    / "openalex_cli.py"
)
_CLI_TIMEOUT_SECONDS = 120
OPENALEX_BASE_URL = "https://api.openalex.org"
OPENALEX_TARGETING_TIMEOUT_SEC = 5.0


async def _run_openalex_cli(args: list[str]) -> Any:
    if not _openalex_key_present():
        return None
    process = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: subprocess.run(
            [sys.executable, str(_OPENALEX_SCRIPT), *args],
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_SECONDS,
        ),
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"openalex CLI failed ({process.returncode}): {process.stderr.strip()[:300]}"
        )
    return json.loads(process.stdout)


def _openalex_key_present() -> bool:
    if os.environ.get("OPENALEX_API_KEY", "").strip():
        return True
    try:
        from dotenv import dotenv_values

        home_env = dotenv_values(os.path.expanduser("~/.env"))
        return bool((home_env.get("OPENALEX_API_KEY") or "").strip())
    except Exception:
        return False


def _abstract_from_inverted_index(inverted: Any) -> str:
    if not isinstance(inverted, dict) or not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indices in inverted.items():
        for index in indices:
            positions.append((int(index), str(word)))
    return " ".join(word for _, word in sorted(positions))


def _journal_for_work(work: Mapping[str, Any]) -> str:
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return compact_text([str(source.get("display_name") or "")])


def _to_evidence(work: Mapping[str, Any]) -> EvidenceRef:
    work_id = str(work.get("id") or "")
    doi = normalize_doi(str(work.get("doi") or ""))
    title = compact_text([str(work.get("display_name") or work.get("title") or "")])
    abstract = _abstract_from_inverted_index(work.get("abstract_inverted_index"))
    return evidence_ref(
        source="openalex",
        paper_id=work_id or doi or "unknown",
        raw=dict(work),
        source_url=doi and f"https://doi.org/{doi}" or work_id,
        source_title=title,
        quote=compact_text([abstract]),
        source_grade=source_grade_for_paper(doi=doi),
        doi=doi,
        journal=_journal_for_work(work),
    )


async def search(query: str, limit: int = 10) -> list[EvidenceRef]:
    if not query.strip():
        return []
    response = await _run_openalex_cli([
        "filter",
        "works",
        "--search",
        query.strip(),
        "--per-page",
        str(limit),
    ])
    if response is None:
        return []
    works = response.get("results") if isinstance(response, dict) else response
    if not isinstance(works, list):
        return []
    return [_to_evidence(work) for work in works if work]


async def get_paper(paper_id: str) -> EvidenceRef | None:
    response = await _run_openalex_cli(["resolve", paper_id])
    if response is None:
        return None
    if not isinstance(response, dict) or not response.get("id"):
        return None
    return _to_evidence(response)


async def get_citations(paper_id: str) -> list[EvidenceRef]:
    raise NotImplementedError(
        "OpenAlex citations are not exposed by the vendored science-skills "
        "openalex_cli filter command."
    )


def query_institutions(domains: list[str], limit: int = 5) -> tuple[list[str], list[dict[str, Any]]]:
    """Return OpenAlex institutions for targeting-map construction."""
    return _query_targeting_names("/institutions", domains, limit=limit, field="display_name")


def query_journals(domains: list[str], limit: int = 5) -> tuple[list[str], list[dict[str, Any]]]:
    """Return OpenAlex journal/source names for targeting-map construction."""
    return _query_targeting_names("/sources", domains, limit=limit, field="display_name", filters="type:journal")


def query_seed_papers(domains: list[str], limit: int = 5) -> tuple[list[str], list[dict[str, Any]]]:
    """Return OpenAlex DOI/title seed papers for targeting-map construction."""
    return _query_targeting_names("/works", domains, limit=limit, field="doi_or_title")


def _query_targeting_names(
    endpoint: str,
    domains: list[str],
    *,
    limit: int,
    field: str,
    filters: str | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    if _skip_live_targeting():
        return [], [
            {
                "source": "openalex",
                "endpoint": endpoint,
                "status": "skipped",
                "reason": "disabled during pytest unless MUCHANIPO_ACADEMIC_TARGETING=1",
            }
        ]

    names: list[str] = []
    provenance: list[dict[str, Any]] = []
    seen: set[str] = set()
    safe_limit = max(1, limit)
    email = contact_email()
    with httpx.Client(
        base_url=OPENALEX_BASE_URL,
        headers={
            "User-Agent": f"muchanipo/0.1 (mailto:{email})",
            "From": email,
        },
        timeout=OPENALEX_TARGETING_TIMEOUT_SEC,
    ) as client:
        for domain in domains or ["general"]:
            params: dict[str, Any] = {
                "search": domain,
                "per-page": safe_limit,
                "mailto": email,
            }
            if filters:
                params["filter"] = filters
            try:
                response = client.get(endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:  # noqa: BLE001 - targeting must degrade gracefully
                provenance.append(
                    {
                        "source": "openalex",
                        "endpoint": endpoint,
                        "query": domain,
                        "status": "error",
                        "error": str(exc).splitlines()[0][:160],
                    }
                )
                continue
            results = payload.get("results", []) if isinstance(payload, dict) else []
            for item in results:
                if not isinstance(item, dict):
                    continue
                name = _targeting_name(item, field=field)
                if not name or name in seen:
                    continue
                seen.add(name)
                names.append(name)
            provenance.append(
                {
                    "source": "openalex",
                    "endpoint": endpoint,
                    "query": domain,
                    "status": "ok",
                    "count": len(results),
                }
            )
    return names[:safe_limit], provenance


def _targeting_name(item: dict[str, Any], *, field: str) -> str:
    if field == "doi_or_title":
        return str(normalize_doi(item.get("doi")) or item.get("display_name") or "").strip()
    return str(item.get(field) or "").strip()


def _skip_live_targeting() -> bool:
    if os.environ.get("MUCHANIPO_ACADEMIC_TARGETING", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    if os.environ.get("MUCHANIPO_ACADEMIC_TARGETING", "").strip().lower() in {"0", "false", "no", "off"}:
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))
