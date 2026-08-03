from src.intent.interview_prompts import assess
from src.muchanipo.server import _serve_interview_question_count


EXPLICIT_BIOMEDICAL_QUESTION = (
    "최근 5년간 장내 미생물과 우울증의 인과 근거를 검토해줘. "
    "관찰연구와 임상시험을 구분하고 근거의 강도와 한계를 표로 정리해줘."
)


def test_explicit_scientific_question_skips_browser_prd_interview() -> None:
    assessment = assess(EXPLICIT_BIOMEDICAL_QUESTION)

    assert assessment.mode == "quick"
    assert _serve_interview_question_count(
        EXPLICIT_BIOMEDICAL_QUESTION,
        depth="shallow",
    ) == 0


def test_ambiguous_scientific_quick_question_caps_clarifications() -> None:
    assert 0 <= _serve_interview_question_count(
        "장내 미생물과 우울증의 관계를 연구해줘.",
        depth="shallow",
    ) <= 2


def test_product_prd_flow_keeps_deep_interview() -> None:
    assert _serve_interview_question_count(
        "신규 B2B SaaS 결제 기능의 PRD를 작성해줘.",
        depth="deep",
    ) == 6
