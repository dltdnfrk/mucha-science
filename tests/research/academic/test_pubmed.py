import asyncio

import httpx

from src.research.academic.pubmed import PubMedClient


PUBMED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>Grounded biomedical evidence</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">First abstract section.</AbstractText>
          <AbstractText Label="RESULTS">Measured effect was significant.</AbstractText>
        </Abstract>
        <Journal><Title>Nature Medicine</Title></Journal>
        <ELocationID EIdType="doi">10.1000/pubmed-test</ELocationID>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_pubmed_search_resolves_ids_and_maps_article_metadata():
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.url.params["api_key"] == "ncbi-key"
        if request.url.path.endswith("/esearch.fcgi"):
            assert request.url.params["term"] == "grounded evidence"
            return httpx.Response(200, json={"esearchresult": {"idlist": ["12345678"]}})
        assert request.url.path.endswith("/efetch.fcgi")
        assert request.url.params["id"] == "12345678"
        return httpx.Response(200, text=PUBMED_XML)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = PubMedClient(client=http, api_key="ncbi-key", min_interval_seconds=0)
            return await client.search("grounded evidence", limit=1)

    results = asyncio.run(run())

    assert paths == [
        "/entrez/eutils/esearch.fcgi",
        "/entrez/eutils/efetch.fcgi",
    ]
    assert results[0].id == "pubmed:12345678"
    assert results[0].source_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert results[0].source_title == "Grounded biomedical evidence"
    assert results[0].quote == "First abstract section. Measured effect was significant."
    assert results[0].provenance["doi"] == "10.1000/pubmed-test"
    assert results[0].provenance["journal"] == "Nature Medicine"


def test_pubmed_search_returns_empty_without_ids():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"esearchresult": {"idlist": []}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = PubMedClient(client=http, min_interval_seconds=0)
            return await client.search("no result")

    assert asyncio.run(run()) == []
