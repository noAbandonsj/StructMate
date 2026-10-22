"""Read-only practice responses and immutable question snapshots.

Write transactions and grading belong in services.practice. Response builders
only read current validity and source status; historical snapshots stay intact.
"""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from capstone.db.models import (
    Attempt,
    Document,
    KnowledgePoint,
    PracticeItem,
    Question,
    WrongQuestion,
)


def snapshot(question):
    return deepcopy(
        {
            **question.content,
            "source_type": question.source_type,
            "knowledge_point_id": str(question.knowledge_point_id)
            if question.knowledge_point_id
            else None,
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
        "source_type": item.snapshot["source_type"],
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
        "source_type": content["source_type"],
        "difficulty": content["difficulty"],
        "knowledge_point_id": content["knowledge_point_id"],
        "hinted": item.hinted_at is not None,
        "hint": content["hint"] if item.hinted_at else None,
        "is_valid": question.is_valid,
        "disabled_reason": question.disabled_reason,
        "attempt": attempt_info(session, attempt, item) if attempt else None,
        "feedback": item.feedback,
    }


def practice_info(session, practice):
    rows = session.execute(
        select(Question.is_valid, Attempt)
        .select_from(PracticeItem)
        .join(Question)
        .outerjoin(Attempt, Attempt.practice_item_id == PracticeItem.id)
        .where(PracticeItem.practice_session_id == practice.id)
    ).all()
    attempts = [attempt for valid, attempt in rows if valid and attempt and attempt.is_valid]
    total = sum(valid for valid, _ in rows)
    title = practice.settings.get("topic", "")
    if not title:
        identifiers = practice.settings.get("knowledge_point_ids", [])
        names = (
            session.scalars(
                select(KnowledgePoint.name).where(
                    KnowledgePoint.id.in_([UUID(value) for value in identifiers])
                )
            ).all()
            if identifiers
            else []
        )
        title = "、".join(names) or (
            "错题复习" if practice.mode == "review" else "数据结构综合练习"
        )
    return {
        "title": title,
        "id": practice.id,
        "mode": practice.mode,
        "question_source": practice.question_source,
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
    attempts = session.scalars(
        select(Attempt)
        .where(Attempt.user_id == wrong.user_id, Attempt.question_id == wrong.question_id)
        .order_by(Attempt.created_at, Attempt.id)
    ).all()
    result = {
        "id": wrong.id,
        "question_id": question.id,
        "knowledge_point_id": question.knowledge_point_id,
        "topic": question.source_info.get("topic", ""),
        "stem": question.content["stem"],
        "source_type": question.source_type,
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
