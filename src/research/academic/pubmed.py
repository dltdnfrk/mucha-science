"""PubMed/NCBI E-utilities literature search integration."""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from src.evidence.artifact import EvidenceRef

from .common import AcademicHttpClient, compact_text, evidence_ref, normalize_doi, source_grade_for_paper


PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedClient:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        api_key: str | None = None,
        min_interval_seconds: float | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("MUCHANIPO_NCBI_API_KEY")
            or os.getenv("NCBI_API_KEY")
        )
        interval = (
            min_interval_seconds
            if min_interval_seconds is not None
            else (0.11 if self.api_key else 0.34)
        )
        self.http = AcademicHttpClient(
            base_url=PUBMED_BASE_URL,
            headers={"User-Agent": "mucha-science/0.1"},
            max_concurrency=1,
            min_interval_seconds=interval,
            client=client,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def search(self, query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": limit,
            **kwargs,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        payload = await self.http.get_json("/esearch.fcgi", params=params)
        ids = _pubmed_ids(payload)
        if not ids:
            return []
        return await self._fetch(ids)

    async def get_paper(self, paper_id: str) -> EvidenceRef | None:
        results = await self._fetch([_strip_pubmed_id(paper_id)])
        return results[0] if results else None

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[EvidenceRef]:
        return []

    async def _fetch(self, ids: list[str]) -> list[EvidenceRef]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "xml",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        response = await self.http.get("/efetch.fcgi", params=params)
        return [_to_evidence(article) for article in _articles(response.text)]


def _pubmed_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    result = payload.get("esearchresult")
    ids = result.get("idlist") if isinstance(result, dict) else None
    if not isinstance(ids, list):
        return []
    return [str(item).strip() for item in ids if str(item).strip()]


def _articles(xml_text: str) -> list[ET.Element]:
    root = ET.fromstring(xml_text)
    return list(root.findall("./PubmedArticle"))


def _to_evidence(article: ET.Element) -> EvidenceRef:
    pmid = _node_text(article.find("./MedlineCitation/PMID")) or "unknown"
    title = _node_text(article.find("./MedlineCitation/Article/ArticleTitle"))
    abstract = compact_text(
        [
            _node_text(node)
            for node in article.findall("./MedlineCitation/Article/Abstract/AbstractText")
        ]
    )
    journal = _node_text(article.find("./MedlineCitation/Article/Journal/Title"))
    doi = normalize_doi(_doi(article))
    raw = {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "journal": journal,
        "doi": doi,
    }
    return evidence_ref(
        source="pubmed",
        paper_id=pmid,
        raw=raw,
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        source_title=title,
        quote=abstract,
        source_grade=source_grade_for_paper(doi=doi),
        doi=doi,
        journal=journal,
        access_status="abstract_only" if abstract else "metadata_only",
    )


def _doi(article: ET.Element) -> str | None:
    for node in article.findall("./MedlineCitation/Article/ELocationID"):
        if node.attrib.get("EIdType", "").lower() == "doi":
            return _node_text(node)
    for node in article.findall("./PubmedData/ArticleIdList/ArticleId"):
        if node.attrib.get("IdType", "").lower() == "doi":
            return _node_text(node)
    return None


def _node_text(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    text = " ".join("".join(node.itertext()).split())
    return text or None


def _strip_pubmed_id(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1]


async def search(query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
    client = PubMedClient()
    try:
        return await client.search(query, limit, **kwargs)
    finally:
        await client.aclose()


async def get_paper(paper_id: str) -> EvidenceRef | None:
    client = PubMedClient()
    try:
        return await client.get_paper(paper_id)
    finally:
        await client.aclose()


async def get_citations(paper_id: str, limit: int = 50) -> list[EvidenceRef]:
    client = PubMedClient()
    try:
        return await client.get_citations(paper_id, limit)
    finally:
        await client.aclose()
