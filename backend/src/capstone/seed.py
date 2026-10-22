"""Explicit, repeatable initialization of the fixed data structures catalog."""

import sys
from dataclasses import dataclass
from uuid import UUID

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from capstone.core.chapters import CHAPTERS
from capstone.core.settings import REPOSITORY_ROOT, Settings
from capstone.db.models import Chapter, KnowledgeBase
from capstone.db.session import create_database_engine

COURSE_CODE = "data-structures"
COURSE_NAME = "数据结构课程资料"


@dataclass(frozen=True)
class SeedResult:
    course_id: UUID
    chapter_count: int


def seed_course_data(engine: Engine) -> SeedResult:
    """Update maintained labels without replacing IDs or touching personal data."""
    with Session(engine) as session, session.begin():
        course_insert = insert(KnowledgeBase).values(
            kind="course", owner_id=None, course_code=COURSE_CODE, name=COURSE_NAME
        )
        session.execute(
            course_insert.on_conflict_do_update(
                index_elements=["course_code"], set_={"name": course_insert.excluded.name}
            )
        )
        course_id = session.scalars(
            select(KnowledgeBase.id).where(KnowledgeBase.course_code == COURSE_CODE)
        ).one()
        for code, name, sort_order in CHAPTERS:
            point_insert = insert(Chapter).values(code=code, name=name, sort_order=sort_order)
            session.execute(
                point_insert.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "name": point_insert.excluded.name,
                        "sort_order": point_insert.excluded.sort_order,
                    },
                )
            )
    return SeedResult(course_id=course_id, chapter_count=len(CHAPTERS))


def main() -> int:
    settings = Settings()
    engine = create_database_engine(settings.sqlite_path)
    try:
        migrations = ScriptDirectory.from_config(
            Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
        )
        with engine.connect() as connection:
            current_heads = MigrationContext.configure(connection).get_current_heads()
        if set(current_heads) != set(migrations.get_heads()):
            print("请先在 backend 目录执行 uv run --locked alembic upgrade head。", file=sys.stderr)
            return 1
        result = seed_course_data(engine)
    except SQLAlchemyError:
        print("课程初始化失败，请检查数据库迁移和写入权限。", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(
        f"课程基础数据已就绪：{COURSE_NAME}，{result.chapter_count} 个内置章节；尚未导入课程文档。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
