"""Disable incorrect AI questions without changing submitted answers."""

import argparse
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from capstone.core.settings import Settings
from capstone.db.models import (
    Attempt,
    PracticeItem,
    PracticeSession,
    Question,
    utc_now,
)
from capstone.db.session import create_database_engine, write_transaction


def invalidate(engine, identifier, reason):
    with Session(engine) as session, write_transaction(session):
        question = session.get(Question, identifier)
        if question is None:
            raise ValueError("题目不存在")
        question.is_valid = False
        question.disabled_reason = reason
        affected = set(
            session.scalars(
                select(PracticeItem.practice_session_id).where(
                    PracticeItem.question_id == identifier
                )
            )
        )
        for practice_id in affected:
            remaining = session.scalar(
                select(func.count())
                .select_from(PracticeItem)
                .join(Question)
                .outerjoin(Attempt, Attempt.practice_item_id == PracticeItem.id)
                .where(
                    PracticeItem.practice_session_id == practice_id,
                    Question.is_valid.is_(True),
                    Attempt.id.is_(None),
                )
            )
            if remaining == 0:
                practice = session.get(PracticeSession, practice_id)
                practice.status, practice.completed_at = (
                    "completed",
                    practice.completed_at or utc_now(),
                )


def main():
    parser = argparse.ArgumentParser(description="停用确认有误的 AI 题目")
    parser.add_argument("--id", type=UUID, required=True)
    parser.add_argument("--reason", required=True)
    data = parser.parse_args()
    engine = create_database_engine(Settings().sqlite_path)
    try:
        if not data.reason.strip():
            raise ValueError("停用原因不能为空")
        invalidate(engine, data.id, data.reason.strip())
        print("题目已停用并排除统计，已提交作答保留。")
    except Exception:
        print("停用失败，请检查题目编号、数据库迁移及操作参数。")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
