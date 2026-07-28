from __future__ import annotations

import sys
from contextlib import suppress
from typing import IO

from .contracts import InterviewCapture


def conduct_interview(
    topic: str,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> InterviewCapture:
    from src.intake.idea_dump import IdeaDump
    from src.intent.interview_prompts import forcing_questions_korean, merge_answers_to_text
    from src.interview.session import InterviewSession

    inp = stdin or sys.stdin
    out = stdout or sys.stdout
    session = InterviewSession.from_idea(IdeaDump(raw_text=topic))
    plan = session.plan
    mode = plan.mode if plan is not None else "deep"
    question_bank = {item["id"]: item["question"] for item in forcing_questions_korean()}
    questions = session.clarifications_for_quick_mode() if mode == "quick" else []

    out.write("\n아이디어 심층 인터뷰\n")
    out.write("------------------\n")
    out.write("show-me-the-prd 방식으로 PRD, 기능명세, 유저플로우 seed를 먼저 좁힌 뒤 리서치를 시작합니다.\n")
    out.write("빈 줄 또는 'skip'은 해당 질문을 건너뜁니다.\n\n")
    out.flush()

    qa_pairs: list[dict[str, str]] = []
    asked: set[str] = set()
    for index in range(1, 7):
        question_data = _next_question(
            index=index,
            mode=mode,
            quick_questions=questions,
            session=session,
            asked=asked,
            question_bank=question_bank,
        )
        if question_data is None:
            break
        question_id, question = question_data
        out.write(f"{question}\n")
        answer = read_prompt(inp, out, "answer> ")
        if answer is None:
            out.write("\n인터뷰 입력이 종료되어 현재 답변까지만 반영합니다.\n")
            out.flush()
            break
        cleaned = answer.strip()
        if not cleaned or cleaned.lower() in {"skip", "pass", "건너뛰기"}:
            if mode != "quick" and session.rubric is not None:
                with suppress(KeyError):
                    session.rubric.update(question_id, "skipped", quality=0.7)
            out.write("skipped\n\n")
            out.flush()
            continue
        label = interview_answer_label(question_id)
        if label:
            session.answer(label, cleaned)
        qa_pairs.append({"id": question_id, "answer": cleaned})
        out.write("\n")
        out.flush()

    if not qa_pairs:
        out.write("인터뷰 답변이 없어 원 토픽으로 진행합니다.\n\n")
        out.flush()
        return InterviewCapture(topic, topic, mode, 0)

    pipeline_input = merge_answers_to_text(topic, qa_pairs)
    out.write(f"인터뷰 반영 완료: {len(qa_pairs)}개 답변, coverage={session.coverage_score:.2f}\n")
    out.write("이제 리서치 파이프라인을 시작합니다.\n\n")
    out.flush()
    return InterviewCapture(topic, pipeline_input, mode, len(qa_pairs))


def _next_question(
    *,
    index: int,
    mode: str,
    quick_questions: list[dict[str, str]],
    session,
    asked: set[str],
    question_bank: dict[str, str],
) -> tuple[str, str] | None:
    if mode == "quick":
        if index > len(quick_questions):
            return None
        question = quick_questions[index - 1]
        question_id = str(question.get("id") or f"Q{index}")
        return question_id, str(question.get("question") or "").strip()

    next_item = session.next_question()
    if next_item is None:
        return None
    if next_item.dimension_id in asked and session.rubric is not None:
        next_item = next(
            (
                candidate
                for candidate in session.rubric.items
                if candidate.dimension_id not in asked
            ),
            None,
        )
        if next_item is None:
            return None
    question_id = next_item.dimension_id
    asked.add(question_id)
    return question_id, question_bank.get(question_id, next_item.research_question).strip()


def interview_answer_label(question_id: str) -> str | None:
    return {
        "Q1_research_question": "research_question",
        "Q2_purpose": "purpose",
        "Q3_context": "context",
        "Q4_known": "known",
        "Q5_deliverable": "deliverable_type",
        "Q6_quality": "quality_bar",
        "clarify_timeframe": "quality_bar",
        "clarify_domain": "context",
        "clarify_evaluation": "quality_bar",
        "clarify_comparison": "context",
    }.get(question_id)


def read_prompt(inp: IO[str], out: IO[str], prompt: str) -> str | None:
    out.write(prompt)
    out.flush()
    line = inp.readline()
    return line if line else None
