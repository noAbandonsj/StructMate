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

from capstone.core.settings import REPOSITORY_ROOT, Settings
from capstone.db.models import KnowledgeBase, KnowledgePoint
from capstone.db.session import create_database_engine

COURSE_CODE = "data-structures"
COURSE_NAME = "数据结构课程资料"

# Parent nodes precede their children; codes remain stable across later imports.
KNOWLEDGE_POINTS = (
    ("linear-list", "线性表", None, 10),
    ("stack-queue", "栈与队列", None, 20),
    ("tree", "树", None, 30),
    ("graph", "图", None, 40),
    ("search", "查找", None, 50),
    ("sort", "排序", None, 60),
    ("hash", "散列", None, 70),
    ("complexity", "复杂度", None, 80),
    ("linear-list.definition", "线性表基本概念", "linear-list", 10),
    ("linear-list.sequential", "顺序表", "linear-list", 20),
    ("linear-list.linked", "链表", "linear-list", 30),
    ("stack-queue.stack", "栈与栈操作", "stack-queue", 10),
    ("stack-queue.queue", "队列", "stack-queue", 20),
    ("stack-queue.circular-queue", "循环队列", "stack-queue", 30),
    ("tree.binary-tree", "二叉树基本概念", "tree", 10),
    ("tree.traversal", "二叉树遍历", "tree", 20),
    ("tree.bst", "二叉搜索树", "tree", 30),
    ("tree.heap", "堆", "tree", 40),
    ("graph.representation", "图的存储", "graph", 10),
    ("graph.traversal", "图的遍历", "graph", 20),
    ("graph.shortest-path", "最短路径", "graph", 30),
    ("graph.spanning-tree", "最小生成树", "graph", 40),
    ("search.linear", "顺序查找", "search", 10),
    ("search.binary", "二分查找", "search", 20),
    ("sort.basic", "插入、选择与冒泡排序", "sort", 10),
    ("sort.quick", "快速排序", "sort", 20),
    ("sort.merge", "归并排序", "sort", 30),
    ("hash.functions", "散列函数", "hash", 10),
    ("hash.collisions", "散列冲突处理", "hash", 20),
    ("complexity.time", "时间复杂度", "complexity", 10),
    ("complexity.space", "空间复杂度", "complexity", 20),
)


@dataclass(frozen=True)
class SeedResult:
    course_id: UUID
    knowledge_point_count: int


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
        point_ids: dict[str, UUID] = {}
        for code, name, parent_code, sort_order in KNOWLEDGE_POINTS:
            parent_id = point_ids[parent_code] if parent_code is not None else None
            point_insert = insert(KnowledgePoint).values(
                code=code, name=name, parent_id=parent_id, sort_order=sort_order
            )
            session.execute(
                point_insert.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "name": point_insert.excluded.name,
                        "parent_id": point_insert.excluded.parent_id,
                        "sort_order": point_insert.excluded.sort_order,
                    },
                )
            )
            point_ids[code] = session.scalars(
                select(KnowledgePoint.id).where(KnowledgePoint.code == code)
            ).one()
    return SeedResult(course_id=course_id, knowledge_point_count=len(point_ids))


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
        f"课程基础数据已就绪：{COURSE_NAME}，8 个章节、"
        f"{result.knowledge_point_count} 个目录节点；尚未导入课程文档。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
