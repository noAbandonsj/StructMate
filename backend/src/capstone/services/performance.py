from datetime import timedelta

from sqlalchemy import select

from capstone.db.models import Attempt, KnowledgePoint, Question, utc_now


def selected_points(session, identifiers):
    points = session.scalars(
        select(KnowledgePoint).order_by(KnowledgePoint.sort_order, KnowledgePoint.code)
    ).all()
    selected = set(identifiers)
    roots = [point.code for point in points if point.id in selected]
    return [
        point
        for point in points
        if not selected
        or any(point.code == code or point.code.startswith(code + ".") for code in roots)
    ]


def performance(session, user_id, now=None):
    now = now or utc_now()
    cutoff = now - timedelta(days=30)
    points = session.scalars(
        select(KnowledgePoint).order_by(KnowledgePoint.sort_order, KnowledgePoint.code)
    ).all()
    codes = {point.id: point.code for point in points}
    rows = session.execute(
        select(Question.knowledge_point_id, Attempt.is_correct)
        .join(Attempt, Attempt.question_id == Question.id)
        .where(
            Attempt.user_id == user_id,
            Attempt.category == "first_independent",
            Attempt.is_valid.is_(True),
            Question.is_valid.is_(True),
            Attempt.created_at >= cutoff,
            Attempt.created_at <= now,
        )
    ).all()
    result = []
    for point in points:
        if point.parent_id is not None:
            continue
        scores = [
            correct
            for identifier, correct in rows
            if identifier in codes
            and (codes[identifier] == point.code or codes[identifier].startswith(point.code + "."))
        ]
        count, correct = len(scores), sum(scores)
        rate = correct / count if count else None
        status = "insufficient" if count < 5 else "priority" if rate < 0.6 else "steady"
        result.append(
            {
                "knowledge_point_id": str(point.id),
                "code": point.code,
                "name": point.name,
                "sample_count": count,
                "correct_count": correct,
                "accuracy": rate,
                "status": status,
                "reason": "独立新题少于 5 道，证据不足。"
                if count < 5
                else "最近 30 天独立新题正确率低于 60%，建议优先巩固。"
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
