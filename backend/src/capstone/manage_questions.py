"""Maintainer-only verified bank import, feedback inspection and invalidation."""

import argparse
import json
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from capstone.core.practice import QuestionData
from capstone.core.settings import REPOSITORY_ROOT, Settings
from capstone.db.models import (
    Attempt,
    KnowledgePoint,
    PracticeItem,
    PracticeSession,
    Question,
    utc_now,
)
from capstone.db.session import create_database_engine, write_transaction


def import_bank(engine, content_directory=REPOSITORY_ROOT / "content"):
    bank = json.loads((content_directory / "question-bank.json").read_text(encoding="utf-8"))
    sources = {
        item["id"]: item
        for item in json.loads((content_directory / "sources.json").read_text(encoding="utf-8"))
    }
    # Validate the entire packet before changing any record.
    prepared = []
    for item in bank:
        content = QuestionData.model_validate(
            {key: item[key] for key in ("type", "stem", "options", "answer", "explanation")}
        ).model_dump()
        references = [sources[identifier] for identifier in item["source_ids"]]
        if (
            not references
            or any(not ref.get("license") for ref in references)
            or not item.get("verification", {}).get("checked_on")
        ):
            raise ValueError("题库缺少核验或来源许可")
        digest = sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        prepared.append((item, content, references, item["code"] + ":" + digest))
    added = skipped = 0
    with Session(engine) as session, write_transaction(session):
        points = {point.code: point.id for point in session.scalars(select(KnowledgePoint))}
        if any(item["knowledge_point_code"] not in points for item, *_ in prepared):
            raise ValueError("请先初始化课程知识点")
        for item, content, references, bank_key in prepared:
            if session.scalar(select(Question.id).where(Question.bank_key == bank_key)):
                skipped += 1
                continue
            # Corrections create a fresh immutable question. Old histories stay intact.
            for old in session.scalars(
                select(Question).where(
                    Question.bank_code == item["code"], Question.available.is_(True)
                )
            ):
                old.available = False
            session.add(
                Question(
                    source_type="bank",
                    bank_code=item["code"],
                    bank_key=bank_key,
                    knowledge_point_id=points[item["knowledge_point_code"]],
                    difficulty=item["difficulty"],
                    content=content,
                    source_info={
                        "sources": references,
                        "evidence": item["evidence"],
                        "verification": item["verification"],
                    },
                )
            )
            added += 1
    return added, skipped


def invalidate(engine, identifier, reason):
    with Session(engine) as session, write_transaction(session):
        question = session.get(Question, identifier)
        if question is None:
            raise ValueError("题目不存在")
        question.is_valid = question.available = False
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
    parser = argparse.ArgumentParser(description="核验题库维护")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("import")
    commands.add_parser("feedback")
    invalid = commands.add_parser("invalidate")
    invalid.add_argument("--id", type=UUID, required=True)
    invalid.add_argument("--reason", required=True)
    data = parser.parse_args()
    engine = create_database_engine(Settings().sqlite_path)
    try:
        if data.action == "import":
            added, skipped = import_bank(engine)
            print(f"核验题库：新增 {added} 道，已有 {skipped} 道。")
        elif data.action == "invalidate":
            if not data.reason.strip():
                raise ValueError("原因不能为空")
            invalidate(engine, data.id, data.reason.strip())
            print("题目已停用并排除当前统计；历史作答保留。")
        else:
            with Session(engine) as session:
                rows = session.execute(
                    select(PracticeItem.id, PracticeItem.question_id, PracticeItem.feedback).where(
                        PracticeItem.feedback.is_not(None)
                    )
                ).all()
                print(
                    json.dumps(
                        [
                            {
                                "item_id": str(row.id),
                                "question_id": str(row.question_id),
                                "feedback": row.feedback,
                            }
                            for row in rows
                        ],
                        ensure_ascii=False,
                        indent=2,
                    )
                )
    except Exception:
        print("题库维护失败，请检查迁移、课程初始化、来源与操作参数。")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
