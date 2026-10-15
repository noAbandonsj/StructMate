from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from capstone.core.errors import ApiError
from capstone.db.models import (
    Attempt,
    Conversation,
    KnowledgePoint,
    Message,
    Question,
    WrongQuestion,
    utc_now,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
CATEGORIES = ("first_independent", "first_hinted", "repeat", "review")


def date_range(from_date=None, to_date=None, now=None):
    now = now or utc_now()
    try:
        to_date = to_date or now.astimezone(SHANGHAI).date()
        from_date = from_date or to_date - timedelta(days=6)
        start = datetime.combine(from_date, time.min, SHANGHAI).astimezone(UTC)
        end = datetime.combine(to_date + timedelta(days=1), time.min, SHANGHAI).astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ApiError(422, "DATE_RANGE_INVALID", "日期超出支持范围。") from error
    if from_date > to_date:
        raise ApiError(422, "DATE_RANGE_INVALID", "开始日期不能晚于结束日期。")
    return from_date, to_date, start, end


def measure(attempts):
    count, correct = len(attempts), sum(attempt.is_correct for attempt in attempts)
    return {
        "count": count,
        "correct_count": correct,
        "accuracy": correct / count if count else None,
    }


def learning_stats(session, user_id, from_date=None, to_date=None, cutoff=None):
    cutoff = cutoff or utc_now()
    from_date, to_date, start, end = date_range(from_date, to_date, cutoff)
    rows = session.execute(
        select(Attempt, Question.knowledge_point_id, Question.source_type)
        .join(Question, Question.id == Attempt.question_id)
        .where(
            Attempt.user_id == user_id,
            Attempt.is_valid.is_(True),
            Question.is_valid.is_(True),
            Attempt.created_at >= start,
            Attempt.created_at < end,
            Attempt.created_at <= cutoff,
        )
    ).all()
    attempts = [row[0] for row in rows]
    questions = session.execute(
        select(Message.conversation_id, Message.created_at)
        .join(Conversation)
        .where(
            Conversation.user_id == user_id,
            Message.role == "user",
            Message.created_at >= start,
            Message.created_at < end,
            Message.created_at <= cutoff,
        )
    ).all()
    answers = session.execute(
        select(Message.conversation_id, Message.updated_at)
        .join(Conversation)
        .where(
            Conversation.user_id == user_id,
            Message.role == "assistant",
            Message.status == "completed",
            Message.updated_at >= start,
            Message.updated_at < end,
            Message.updated_at <= cutoff,
        )
    ).all()
    wrongs = session.scalars(
        select(WrongQuestion)
        .join(Question)
        .where(
            WrongQuestion.user_id == user_id,
            Question.is_valid.is_(True),
            WrongQuestion.created_at <= cutoff,
        )
    ).all()
    points = session.scalars(
        select(KnowledgePoint).order_by(KnowledgePoint.sort_order, KnowledgePoint.code)
    ).all()
    codes = {point.id: point.code for point in points}
    chapters = []
    for point in points:
        if point.parent_id is not None:
            continue
        related = [
            row[0]
            for row in rows
            if codes[row[1]] == point.code or codes[row[1]].startswith(point.code + ".")
        ]
        independent = [attempt for attempt in related if attempt.category == "first_independent"]
        chapters.append(
            {
                "knowledge_point_id": str(point.id),
                "name": point.name,
                "attempts": measure(related),
                "independent": measure(independent),
                "evidence": "insufficient" if len(independent) < 5 else "sufficient",
            }
        )
    active_days = {attempt.created_at.astimezone(SHANGHAI).date() for attempt in attempts}
    active_days.update(row.created_at.astimezone(SHANGHAI).date() for row in questions)
    active_days.update(row.updated_at.astimezone(SHANGHAI).date() for row in answers)
    return {
        "schema_version": 1,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "time_zone": "Asia/Shanghai",
        "as_of": cutoff.isoformat(),
        "attempts": measure(attempts),
        "categories": {
            category: measure([attempt for attempt in attempts if attempt.category == category])
            for category in CATEGORIES
        },
        "sources": {
            source: measure([row[0] for row in rows if row[2] == source])
            for source in ("bank", "ai")
        },
        "hinted_attempt_count": sum(attempt.hinted for attempt in attempts),
        "knowledge_points": chapters,
        "learning": {
            "asked_questions": len(questions),
            "completed_answers": len(answers),
            "active_days": len(active_days),
            "conversation_count": len({row.conversation_id for row in [*questions, *answers]}),
        },
        "wrong_questions": {
            "new_in_range": sum(
                start <= wrong.created_at < end and wrong.created_at <= cutoff for wrong in wrongs
            ),
            "current_pending": sum(wrong.status == "pending" for wrong in wrongs),
        },
        "basis": "仅包含服务端已提交的有效作答；题库与 AI 题共同参与，AI 按保存的参考答案计分。"
        "首次独立、提示、重复和复习分开；不估算学习时长。",
    }
