from src.research.queries import (
    biomedical_english_query,
    is_biomedical_query,
    minimum_publication_year,
    pubmed_biomedical_query,
)
from src.interview.brief import ResearchBrief
from src.research.planner import ResearchPlanner


TOPIC = (
    "최근 5년간 장내 미생물과 우울증의 인과 근거를 검토해줘. "
    "관찰연구와 임상시험을 구분해줘."
)


def test_biomedical_query_is_english_and_preserves_study_designs() -> None:
    query = biomedical_english_query(TOPIC, current_year=2026)

    assert "gut microbiome" in query
    assert "depression" in query
    assert "causal" in query
    assert "observational studies" in query
    assert "clinical trials" in query
    assert "2021" in query


def test_recent_year_window_becomes_structured_minimum_year() -> None:
    assert minimum_publication_year(TOPIC, current_year=2026) == 2021
    assert minimum_publication_year(
        "Find biomedical studies published since 2021.",
        current_year=2026,
    ) == 2021


def test_biomedical_intent_does_not_match_product_research() -> None:
    assert is_biomedical_query(TOPIC)
    assert not is_biomedical_query("B2B SaaS 결제 기능의 시장성을 조사해줘.")


def test_research_plan_prioritizes_english_biomedical_query() -> None:
    plan = ResearchPlanner().plan(
        ResearchBrief(
            raw_idea=TOPIC,
            research_question=TOPIC,
            purpose="근거 검토",
            original_topic=TOPIC,
        ),
        max_queries=4,
    )

    assert any(
        "gut microbiome" in query and "published since 2021" in query
        for query in plan.queries
    )


def test_pubmed_query_uses_topic_fields_without_generic_suffixes() -> None:
    query = pubmed_biomedical_query(
        f"{TOPIC} official statistics peer reviewed evidence",
        current_year=2026,
    )

    assert '"gut microbiome"[Title/Abstract]' in query
    assert '"depression"[Title/Abstract]' in query
    assert "systematic review[Publication Type]" in query
    assert "2021:2026[Date - Publication]" in query
    assert "official statistics" not in query


def test_pubmed_query_specializes_observational_route() -> None:
    query = pubmed_biomedical_query(
        f"{TOPIC} definitions scope methods constraints",
        current_year=2026,
    )

    assert '"observational study"[Title/Abstract]' in query
    assert "clinical trial[Publication Type]" not in query


def test_pubmed_query_specializes_randomized_trial_route() -> None:
    query = pubmed_biomedical_query(
        f"{TOPIC} source-backed examples case studies",
        current_year=2026,
    )

    assert "randomized controlled trial[Publication Type]" in query
    assert '"observational study"[Title/Abstract]' not in query
