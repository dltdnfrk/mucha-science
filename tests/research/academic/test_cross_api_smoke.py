import asyncio

import httpx

from src.evidence.artifact import EvidenceRef
from src.research.academic import (
    CoreClient,
    CrossRefClient,
    SemanticScholarClient,
    UnpaywallClient,
)


ARXIV_ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2501.00001v1</id>
    <title>Agent Memory</title>
    <summary>Memory systems for agents.</summary>
    <published>2025-01-01T00:00:00Z</published>
  </entry>
</feed>"""


def test_inprocess_clients_share_evidence_interface():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/graph/v1/paper/search":
            return httpx.Response(200, json={"data": [{"paperId": "S2", "title": "Semantic Scholar"}]})
        if path == "/v3/search/works":
            return httpx.Response(200, json={"results": [{"id": 1, "title": "CORE"}]})
        if path == "/works":
            return httpx.Response(200, json={"message": {"items": [{"DOI": "10.1/cross", "title": ["CrossRef"]}]}})
        if path == "/v2/search":
            return httpx.Response(200, json={"results": [{"response": {"doi": "10.1/oa", "title": "Unpaywall"}}]})
        raise AssertionError(f"unexpected request: {request.url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            clients = [
                SemanticScholarClient(client=http, min_interval_seconds=0),
                CoreClient(client=http, min_interval_seconds=0),
                CrossRefClient(client=http, email="dev@example.com"),
                UnpaywallClient(client=http, email="dev@example.com"),
            ]
            return [await client.search("agent memory", limit=1) for client in clients]

    batches = asyncio.run(run())
    evidence = [batch[0] for batch in batches]

    assert len(evidence) == 4
    assert all(isinstance(item, EvidenceRef) for item in evidence)
    assert {item.provenance["kind"] for item in evidence} == {
        "semantic_scholar",
        "core",
        "crossref",
        "unpaywall",
    }
    assert all(item.provenance["source_text"] for item in evidence)
