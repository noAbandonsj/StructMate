from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from capstone.db.models import AuthSession, KnowledgeBase, KnowledgePoint, User
from capstone.seed import seed_course_data


def add_user(session: Session, username: str = "student") -> User:
    user = User(username=username, display_name="同学", password_hash="test-hash")
    session.add(user)
    session.flush()
    return user


def test_migration_matches_models_and_populated_database_can_be_downgraded(
    migrated_database: Engine, migration_config: Config
) -> None:
    assert set(inspect(migrated_database).get_table_names()) == {
        "alembic_version",
        "users",
        "auth_sessions",
        "knowledge_bases",
        "knowledge_points",
    }
    seed_course_data(migrated_database)
    with Session(migrated_database) as session, session.begin():
        user = add_user(session)
        session.add(KnowledgeBase(kind="personal", owner_id=user.id, name="我的资料"))
        session.add(
            AuthSession(
                user_id=user.id,
                token_hash="a" * 64,
                csrf_token="test-csrf",
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
    command.check(migration_config)
    command.downgrade(migration_config, "base")
    assert set(inspect(migrated_database).get_table_names()) == {"alembic_version"}
    command.upgrade(migration_config, "head")
    command.check(migration_config)


def test_duplicate_username_rolls_back_user_and_personal_library(migrated_database: Engine) -> None:
    with Session(migrated_database) as session, session.begin():
        existing_user = add_user(session)
        original_user_id = existing_user.id
    with pytest.raises(IntegrityError), Session(migrated_database) as session, session.begin():
        new_user = add_user(session, "another_student")
        session.add(KnowledgeBase(kind="personal", owner_id=new_user.id, name="我的资料"))
        session.flush()
        add_user(session, "student")
    with Session(migrated_database) as session:
        assert session.scalars(select(User.id)).all() == [original_user_id]
        assert session.scalars(select(KnowledgeBase)).all() == []


@pytest.mark.parametrize("username", ["Student", "ab", "has space", "中文", "a" * 33])
def test_unprepared_usernames_cannot_bypass_storage_rules(
    migrated_database: Engine, username: str
) -> None:
    with pytest.raises(IntegrityError), Session(migrated_database) as session, session.begin():
        add_user(session, username)


def test_one_personal_library_per_user(migrated_database: Engine) -> None:
    with Session(migrated_database) as session, session.begin():
        user = add_user(session)
        user_id = user.id
        session.add(KnowledgeBase(kind="personal", owner_id=user_id, name="我的资料"))
    with pytest.raises(IntegrityError), Session(migrated_database) as session, session.begin():
        session.add(KnowledgeBase(kind="personal", owner_id=user_id, name="第二个个人库"))


@pytest.mark.parametrize(
    ("kind", "with_owner", "course_code"),
    [
        ("personal", False, None),
        ("personal", True, "data-structures"),
        ("course", True, "data-structures"),
        ("course", False, None),
        ("course", False, ""),
        ("unknown", False, "data-structures"),
    ],
)
def test_library_type_and_owner_combinations_are_enforced(
    migrated_database: Engine, kind: str, with_owner: bool, course_code: str | None
) -> None:
    with pytest.raises(IntegrityError), Session(migrated_database) as session, session.begin():
        user = add_user(session)
        session.add(
            KnowledgeBase(
                kind=kind,
                owner_id=user.id if with_owner else None,
                course_code=course_code,
                name="资料",
            )
        )


def test_course_code_is_unique_without_limiting_distinct_courses(migrated_database: Engine) -> None:
    with Session(migrated_database) as session, session.begin():
        session.add_all(
            [
                KnowledgeBase(kind="course", course_code="data-structures", name="数据结构"),
                KnowledgeBase(kind="course", course_code="another-course", name="其他课程"),
            ]
        )
    with pytest.raises(IntegrityError), Session(migrated_database) as session, session.begin():
        session.add(KnowledgeBase(kind="course", course_code="data-structures", name="重复课程"))


@pytest.mark.parametrize("entity", ["session", "library", "knowledge-point"])
def test_foreign_keys_reject_missing_parents(migrated_database: Engine, entity: str) -> None:
    with pytest.raises(IntegrityError), Session(migrated_database) as session, session.begin():
        missing_id = uuid4()
        if entity == "session":
            record = AuthSession(
                user_id=missing_id,
                token_hash="a" * 64,
                csrf_token="test-csrf",
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        elif entity == "library":
            record = KnowledgeBase(kind="personal", owner_id=missing_id, name="我的资料")
        else:
            record = KnowledgePoint(code="child", name="子知识点", parent_id=missing_id)
        session.add(record)


def test_user_deletion_cannot_remove_personal_library_implicitly(migrated_database: Engine) -> None:
    with Session(migrated_database) as session, session.begin():
        user = add_user(session)
        user_id = user.id
        session.add(KnowledgeBase(kind="personal", owner_id=user_id, name="我的资料"))
    with pytest.raises(IntegrityError), Session(migrated_database) as session, session.begin():
        session.delete(session.get(User, user_id))


@pytest.mark.parametrize(
    ("token_hash", "csrf_token", "expiry_offset"),
    [("plain-token", "csrf", 1), ("g" * 64, "csrf", 1), ("a" * 64, "", 1), ("a" * 64, "csrf", 0)],
)
def test_session_fields_cannot_store_invalid_credentials_or_expiry(
    migrated_database: Engine, token_hash: str, csrf_token: str, expiry_offset: int
) -> None:
    now = datetime.now(UTC)
    with pytest.raises(IntegrityError), Session(migrated_database) as session, session.begin():
        user = add_user(session)
        session.add(
            AuthSession(
                user_id=user.id,
                token_hash=token_hash,
                csrf_token=csrf_token,
                created_at=now,
                expires_at=now + timedelta(seconds=expiry_offset),
            )
        )


def test_session_token_hash_cannot_be_reused(migrated_database: Engine) -> None:
    with Session(migrated_database) as session, session.begin():
        user = add_user(session)
        user_id = user.id
        session.add(
            AuthSession(
                user_id=user_id,
                token_hash="a" * 64,
                csrf_token="first-csrf",
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
    with pytest.raises(IntegrityError), Session(migrated_database) as session, session.begin():
        session.add(
            AuthSession(
                user_id=user_id,
                token_hash="a" * 64,
                csrf_token="second-csrf",
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )


def test_database_roundtrip_restores_utc_for_session_expiry_comparisons(
    migrated_database: Engine,
) -> None:
    local_time = datetime(2026, 10, 11, 18, 30, tzinfo=timezone(timedelta(hours=8)))
    with Session(migrated_database) as session, session.begin():
        user = add_user(session)
        session.add(
            AuthSession(
                user_id=user.id,
                token_hash="a" * 64,
                csrf_token="test-csrf",
                created_at=local_time,
                expires_at=local_time + timedelta(days=7),
            )
        )
    with Session(migrated_database) as session:
        restored = session.scalars(select(AuthSession)).one()
        assert restored.created_at == datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
        assert restored.created_at.tzinfo is UTC
        assert restored.expires_at > restored.created_at
        assert restored.expires_at > datetime(2026, 10, 12, tzinfo=UTC)
    with pytest.raises(StatementError), Session(migrated_database) as session, session.begin():
        session.add(
            User(
                username="another_student",
                display_name="同学",
                password_hash="test-hash",
                created_at=datetime(2026, 10, 11),
            )
        )


def test_ddl_is_rolled_back_on_transaction_failure(migrated_database: Engine) -> None:
    with pytest.raises(RuntimeError), migrated_database.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE rollback_probe (id INTEGER PRIMARY KEY)")
        raise RuntimeError("Simulated failure")
    assert not inspect(migrated_database).has_table("rollback_probe")
