"""Read-only practice responses and immutable question snapshots.

Write transactions and grading belong in services.practice. Response builders
only read current validity and source status; historical snapshots stay intact.
"""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from capstone.db.models import (
    Attempt,
    Chapter,
    Document,
    PracticeItem,
    Question,
    WrongQuestion,
)


def snapshot(question):
    return deepcopy(
        {
            **question.content,
            "chapter_id": str(question.chapter_id) if question.chapter_id else None,
            "difficulty": question.difficulty,
            "source_info": question.source_info,
        }
    )


def attempt_info(session, attempt, item=None):
    item = item or session.get(PracticeItem, attempt.practice_item_id)
    question = session.get(Question, attempt.question_id)
    wrong = session.scalar(
        select(WrongQuestion).where(
            WrongQuestion.user_id == attempt.user_id,
            WrongQuestion.question_id == attempt.question_id,
        )
    )
    return {
        "id": attempt.id,
        "practice_item_id": item.id,
        "answer": attempt.answer,
        "is_correct": attempt.is_correct,
        "hinted": attempt.hinted,
        "category": attempt.category,
        "is_valid": attempt.is_valid and question.is_valid,
        "created_at": attempt.created_at,
        "reference_answer": item.snapshot["answer"],
        "explanation": item.snapshot["explanation"],
        "source_info": current_source_info(session, item.snapshot["source_info"]),
        "wrong_question_id": wrong.id if wrong else None,
    }


def item_info(session, item):
    question = session.get(Question, item.question_id)
    content = item.snapshot
    attempt = session.scalar(select(Attempt).where(Attempt.practice_item_id == item.id))
    return {
        "id": item.id,
        "position": item.position,
        "question_id": item.question_id,
        "type": content["type"],
        "stem": content["stem"],
        "options": content["options"],
        "difficulty": content["difficulty"],
        "chapter_id": question.chapter_id,
        "hinted": item.hinted_at is not None,
        "hint": content["hint"] if item.hinted_at else None,
        "is_valid": question.is_valid,
        "disabled_reason": question.disabled_reason,
        "attempt": attempt_info(session, attempt, item) if attempt else None,
    }


def practice_info(session, practice):
    identifiers = session.scalars(
        select(Question.chapter_id)
        .join(PracticeItem)
        .where(PracticeItem.practice_session_id == practice.id)
        .distinct()
    ).all()
    candidate = practice.settings.get("chapter_id")
    chapter_id = UUID(candidate) if candidate else identifiers[0] if len(identifiers) == 1 else None
    chapter = session.get(Chapter, chapter_id) if chapter_id else None
    rows = session.execute(
        select(Question.is_valid, Attempt)
        .select_from(PracticeItem)
        .join(Question)
        .outerjoin(Attempt, Attempt.practice_item_id == PracticeItem.id)
        .where(PracticeItem.practice_session_id == practice.id)
    ).all()
    attempts = [attempt for valid, attempt in rows if valid and attempt and attempt.is_valid]
    total = sum(valid for valid, _ in rows)
    title = chapter.name if chapter else ""
    if not title:
        title = "错题复习" if practice.mode == "review" else "数据结构综合练习"
    return {
        "title": title,
        "chapter_id": chapter.id if chapter else None,
        "chapter_name": chapter.name if chapter else None,
        "id": practice.id,
        "mode": practice.mode,
        "settings": practice.settings,
        "source_conversation_id": practice.source_conversation_id,
        "status": practice.status,
        "actual_count": practice.actual_count,
        "effective_count": total,
        "submitted_count": len(attempts),
        "correct_count": sum(attempt.is_correct for attempt in attempts),
        "notice": practice.notice,
        "error_code": practice.error_code,
        "error_message": practice.error_message,
        "created_at": practice.created_at,
        "completed_at": practice.completed_at,
    }


def wrong_info(session, wrong, include_history=False):
    question = session.get(Question, wrong.question_id)
    chapter = session.get(Chapter, question.chapter_id) if question.chapter_id else None
    attempts = session.scalars(
        select(Attempt)
        .where(Attempt.user_id == wrong.user_id, Attempt.question_id == wrong.question_id)
        .order_by(Attempt.created_at, Attempt.id)
    ).all()
    result = {
        "id": wrong.id,
        "question_id": question.id,
        "chapter_id": question.chapter_id,
        "chapter_name": chapter.name if chapter else None,
        "stem": question.content["stem"],
        "status": wrong.status,
        "correct_days": wrong.correct_days,
        "last_correct_date": wrong.last_correct_date,
        "is_valid": question.is_valid,
        "disabled_reason": question.disabled_reason,
        "attempt_count": len(attempts),
        "error_count": sum(not attempt.is_correct for attempt in attempts),
        "updated_at": wrong.updated_at,
    }
    if include_history:
        result["question"] = snapshot(question)
        result["question"]["source_info"] = current_source_info(session, question.source_info)
        result["attempts"] = [attempt_info(session, attempt) for attempt in attempts]
    return result


def current_source_info(session, source):
    result = deepcopy(source)
    for citation in result.get("citations", []):
        document = session.get(Document, UUID(citation["document_id"]))
        citation["source_deleted"] = document is None or document.status == "deleted"
    return result
