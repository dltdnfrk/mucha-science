from __future__ import annotations

from src.research.planner import ResearchPlanner
from src.research.runner import WebResearchRunner
from src.interview.brief import ResearchBrief


def test_runtime_gather_fuses_duplicate_provider_results_deterministically() -> None:
    # Given: two providers return the same DOI under different paper IDs.
    query = "Drug X blood pressure trial"
    runner = WebResearchRunner(
        academic_search=lambda _query: [
            {
                "paper_id": "academic-alpha",
                "doi": "DOI:10.1000/ALPHA",
                "title": "Alpha trial",
                "text": "Drug X blood pressure trial evidence",
                "score": 0.1,
            },
            {
                "paper_id": "academic-beta",
                "title": "Beta trial",
                "text": "Drug X blood pressure trial evidence",
                "score": 0.9,
            },
        ],
        web_search=lambda _query: [
            {
                "paper_id": "web-alpha",
                "doi": "https://doi.org/10.1000/alpha",
                "title": "Alpha publisher page",
                "text": "Drug X blood pressure trial evidence",
                "score": 0.2,
            }
        ],
        vault_search=lambda _query: [],
        insight_forge_search=lambda _query: [],
        emit_empty_fallback=False,
    )
    plan = ResearchPlanner().plan(
        ResearchBrief(raw_idea=query, research_question=query, purpose="test"),
        max_queries=1,
    )

    # When: the real gathering seam ranks the provider results.
    first = runner.run(plan)
    second = runner.run(plan)

    # Then: the duplicate is fused once and exposes deterministic contributions.
    assert [item.source_title for item in first[0].support] == [
        "Alpha trial",
        "Beta trial",
    ]
    assert [item.source_title for item in second[0].support] == [
        "Alpha trial",
        "Beta trial",
    ]
    assert first[0].support[0].provenance["rrf_contributions"] == [
        {"provider": "academic", "rank": 1},
        {"provider": "web", "rank": 1},
    ]
