from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Text, UniqueConstraint, Uuid
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


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "dedup_key", name="uq_documents_live_content"),
        CheckConstraint(
            "status IN ('processing', 'ready', 'failed', 'deleted')", name="ck_documents_status"
        ),
        CheckConstraint("file_type IN ('pdf', 'txt', 'md')", name="ck_documents_file_type"),
        CheckConstraint("size_bytes > 0", name="ck_documents_size"),
        CheckConstraint("index_revision > 0", name="ck_documents_revision"),
        CheckConstraint("length(content_hash) = 64", name="ck_documents_content_hash"),
        CheckConstraint(
            "(status = 'deleted' AND dedup_key IS NULL) OR "
            "(status != 'deleted' AND dedup_key IS NOT NULL AND dedup_key = content_hash)",
            name="ck_documents_dedup_key",
        ),
        CheckConstraint(
            "status != 'ready' OR (embedding_fingerprint IS NOT NULL "
            "AND length(embedding_fingerprint) = 64 AND embedding_dimension > 0 "
            "AND embedding_dimension IS NOT NULL)",
            name="ck_documents_ready_index",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), index=True
    )
    knowledge_point_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="RESTRICT")
    )
    filename: Mapped[str] = mapped_column(String(240))
    file_type: Mapped[str] = mapped_column(String(8))
    storage_key: Mapped[str] = mapped_column(String(48))
    size_bytes: Mapped[int] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(64))
    dedup_key: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="processing", index=True)
    stage: Mapped[str] = mapped_column(String(24), default="queued")
    index_revision: Mapped[int] = mapped_column(default=1)
    embedding_fingerprint: Mapped[str | None] = mapped_column(String(64))
    embedding_dimension: Mapped[int | None] = mapped_column()
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    source_info: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "index_revision", "position", name="uq_document_chunks_position"
        ),
        CheckConstraint("position >= 0 AND index_revision > 0", name="ck_document_chunks_position"),
        CheckConstraint("length(text) > 0", name="ck_document_chunks_text"),
        CheckConstraint(
            "(page_number IS NULL OR page_number >= 1) AND "
            "((line_start IS NULL AND line_end IS NULL) OR "
            "(line_start IS NOT NULL AND line_end IS NOT NULL "
            "AND line_start >= 1 AND line_end >= line_start))",
            name="ck_document_chunks_source_position",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    index_revision: Mapped[int] = mapped_column()
    position: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column()
    heading: Mapped[str | None] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column()
    line_end: Mapped[int | None] = mapped_column()
    knowledge_point_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="RESTRICT")
    )


class DocumentTask(Base):
    __tablename__ = "document_tasks"
    __table_args__ = (
        UniqueConstraint("document_id", "request_id", name="uq_document_tasks_request"),
        CheckConstraint("action IN ('process', 'delete')", name="ck_document_tasks_action"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_document_tasks_status",
        ),
        CheckConstraint("attempt_count BETWEEN 0 AND 3", name="ck_document_tasks_attempts"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(64))
    index_revision: Mapped[int] = mapped_column()
    action: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
