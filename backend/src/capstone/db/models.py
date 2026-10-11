from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from capstone.db.base import Base
from capstone.db.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint(
            "length(username) BETWEEN 3 AND 32 AND username NOT GLOB '*[^a-z0-9_]*'",
            name="ck_users_username_format",
        ),
        CheckConstraint("length(display_name) BETWEEN 1 AND 32", name="ck_users_display_name"),
        CheckConstraint("length(password_hash) > 0", name="ck_users_password_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        CheckConstraint(
            "length(token_hash) = 64 AND token_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_auth_sessions_token_hash",
        ),
        CheckConstraint("length(csrf_token) > 0", name="ck_auth_sessions_csrf_token"),
        CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_auth_sessions_user_id_users", ondelete="CASCADE"),
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    csrf_token: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("owner_id", name="uq_knowledge_bases_owner_id"),
        UniqueConstraint("course_code", name="uq_knowledge_bases_course_code"),
        CheckConstraint(
            "(kind = 'personal' AND owner_id IS NOT NULL AND course_code IS NULL) OR "
            "(kind = 'course' AND owner_id IS NULL AND course_code IS NOT NULL)",
            name="ck_knowledge_bases_kind_owner",
        ),
        CheckConstraint("length(name) BETWEEN 1 AND 100", name="ck_knowledge_bases_name"),
        CheckConstraint(
            "course_code IS NULL OR length(course_code) BETWEEN 1 AND 64",
            name="ck_knowledge_bases_course_code",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_knowledge_bases_owner_id_users", ondelete="RESTRICT"),
    )
    course_code: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    __table_args__ = (
        UniqueConstraint("code", name="uq_knowledge_points_code"),
        CheckConstraint("length(code) BETWEEN 1 AND 64", name="ck_knowledge_points_code"),
        CheckConstraint("length(name) BETWEEN 1 AND 100", name="ck_knowledge_points_name"),
        CheckConstraint("sort_order >= 0", name="ck_knowledge_points_sort_order"),
        CheckConstraint("parent_id IS NULL OR parent_id != id", name="ck_knowledge_points_parent"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "knowledge_points.id",
            name="fk_knowledge_points_parent_id_knowledge_points",
            ondelete="RESTRICT",
        ),
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(default=0)
