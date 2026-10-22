from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from capstone import seed
from capstone.db.models import AuthSession, Chapter, KnowledgeBase, User
from capstone.db.session import create_database_engine


def test_seed_is_repeatable_preserves_ids_and_personal_data(migrated_database: Engine) -> None:
    first_result = seed.seed_course_data(migrated_database)
    with Session(migrated_database) as session, session.begin():
        original_ids = dict(session.execute(select(Chapter.code, Chapter.id)).all())
        user = User(username="student", display_name="同学", password_hash="test-hash")
        session.add(user)
        session.flush()
        personal_library = KnowledgeBase(kind="personal", owner_id=user.id, name="私人资料")
        session.add(personal_library)
        session.flush()
        personal_id = personal_library.id
        course = session.get(KnowledgeBase, first_result.course_id)
        course_created_at = course.created_at
        course.name = "旧课程标题"
        session.get(Chapter, original_ids["tree"]).name = "旧知识点标题"

    second_result = seed.seed_course_data(migrated_database)
    assert second_result == first_result
    with Session(migrated_database) as session:
        assert dict(session.execute(select(Chapter.code, Chapter.id)).all()) == (original_ids)
        course = session.get(KnowledgeBase, first_result.course_id)
        assert course.name == seed.COURSE_NAME
        assert course.created_at == course_created_at
        assert course.owner_id is None
        assert session.get(KnowledgeBase, personal_id).name == "私人资料"
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0
        assert session.scalar(select(func.count()).select_from(KnowledgeBase)) == 2
        assert session.get(Chapter, original_ids["tree"]).name == "树与二叉树"


def test_seed_builds_only_the_eight_flat_chapters(migrated_database: Engine) -> None:
    result = seed.seed_course_data(migrated_database)
    with Session(migrated_database) as session:
        points = session.scalars(select(Chapter)).all()
        roots = sorted(points, key=lambda point: point.sort_order)
        assert result.chapter_count == len(points) == 8
        assert [point.code for point in roots] == [
            "complexity",
            "linear-list",
            "stack-queue",
            "strings-arrays",
            "tree",
            "graph",
            "search",
            "sort",
        ]
        assert session.scalar(select(func.count()).select_from(User)) == 0
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_seed_failure_rolls_back_all_partial_updates(
    migrated_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = seed.seed_course_data(migrated_database)
    with Session(migrated_database) as session, session.begin():
        session.get(KnowledgeBase, result.course_id).name = "保留的课程标题"
        root = session.scalars(select(Chapter).where(Chapter.code == "linear-list")).one()
        root.name = "保留的知识点标题"
        root_id = root.id
    monkeypatch.setattr(seed, "CHAPTERS", (*seed.CHAPTERS, ("invalid", "错误节点", -1)))
    with pytest.raises(IntegrityError):
        seed.seed_course_data(migrated_database)
    with Session(migrated_database) as session:
        assert session.get(KnowledgeBase, result.course_id).name == "保留的课程标题"
        assert session.get(Chapter, root_id).name == "保留的知识点标题"
        assert session.scalar(select(func.count()).select_from(Chapter)) == 8


def test_seed_cli_requires_migration_without_creating_business_tables(
    migration_config: Config, tmp_path: Path, capsys
) -> None:
    assert seed.main() == 1
    assert "alembic upgrade head" in capsys.readouterr().err
    engine = create_database_engine(tmp_path / "capstone.db")
    try:
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()
    command.upgrade(migration_config, "head")
    assert seed.main() == 0
    assert "8 个内置章节" in capsys.readouterr().out
    assert seed.main() == 0
