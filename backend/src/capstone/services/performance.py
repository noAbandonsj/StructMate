from datetime import timedelta

from sqlalchemy import select

from capstone.db.models import Attempt, Question, utc_now
from capstone.services.chapters import chapters


def performance(session, user_id, now=None):
    now = now or utc_now()
    cutoff = now - timedelta(days=30)
    points = chapters(session)
    rows = session.execute(
        select(Question.chapter_id, Attempt.is_correct)
        .join(Attempt, Attempt.question_id == Question.id)
        .where(
            Attempt.user_id == user_id,
            Attempt.category == "first",
            Attempt.is_valid.is_(True),
            Question.is_valid.is_(True),
            Attempt.created_at >= cutoff,
            Attempt.created_at <= now,
        )
    ).all()
    result = []
    for point in points:
        scores = [correct for identifier, correct in rows if identifier == point.id]
        count, correct = len(scores), sum(scores)
        rate = correct / count if count else None
        status = "insufficient" if count < 5 else "priority" if rate < 0.6 else "steady"
        result.append(
            {
                "chapter_id": str(point.id),
                "code": point.code,
                "name": point.name,
                "sample_count": count,
                "correct_count": correct,
                "accuracy": rate,
                "status": status,
                "reason": "首次作答的新题少于 5 道，证据不足。"
                if count < 5
                else "最近 30 天首次作答正确率低于 60%，建议优先巩固。"
                if status == "priority"
                else "样本足够，可继续拓展或巩固。",
            }
        )
    result.sort(
        key=lambda item: (
            {"priority": 0, "insufficient": 1, "steady": 2}[item["status"]],
            item["accuracy"] if item["status"] == "priority" else item["sample_count"],
            item["code"],
        )
    )
    return {
        "from_time": cutoff.isoformat(),
        "to_time": now.isoformat(),
        "window_days": 30,
        "items": result,
    }
