from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
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
        CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
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


class CourseMaintenance(Base):
    __tablename__ = "course_maintenance"
    __table_args__ = (
        CheckConstraint(
            "action IN ('upload', 'process', 'delete')", name="ck_course_maintenance_action"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


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


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('combined', 'course', 'personal')", name="ck_conversations_scope"
        ),
        CheckConstraint("length(title) BETWEEN 1 AND 100", name="ck_conversations_title"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(100), default="新的学习")
    scope: Mapped[str] = mapped_column(String(16), default="combined")
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    knowledge_point_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="RESTRICT")
    )
    archived: Mapped[bool] = mapped_column(default=False)
    summary_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_sequence"),
        UniqueConstraint("conversation_id", "request_id", name="uq_messages_request"),
        CheckConstraint("sequence > 0", name="ck_messages_sequence"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        CheckConstraint(
            "status IN ('generating', 'completed', 'failed', 'cancelled')",
            name="ck_messages_status",
        ),
        CheckConstraint("intent IN ('explain', 'hint', 'example')", name="ck_messages_intent"),
        Index(
            "uq_messages_active",
            "conversation_id",
            unique=True,
            sqlite_where=text("role = 'assistant' AND status = 'generating'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), index=True
    )
    sequence: Mapped[int] = mapped_column()
    role: Mapped[str] = mapped_column(String(16))
    reply_to_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str | None] = mapped_column(String(64))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="completed")
    intent: Mapped[str] = mapped_column(String(16), default="explain")
    answer_outcome: Mapped[str | None] = mapped_column(String(24))
    citations: Mapped[list] = mapped_column(JSON, default=list)
    scope_snapshot: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "(source_type = 'bank' AND owner_id IS NULL AND bank_key IS NOT NULL) OR "
            "(source_type = 'ai' AND owner_id IS NOT NULL AND bank_key IS NULL)",
            name="ck_questions_source_owner",
        ),
        CheckConstraint(
            "difficulty IN ('basic', 'intermediate', 'advanced')", name="ck_questions_difficulty"
        ),
        UniqueConstraint("bank_key", name="uq_questions_bank_key"),
        UniqueConstraint("owner_id", "content_fingerprint", name="uq_questions_owner_content"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    knowledge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="RESTRICT"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(8))
    bank_code: Mapped[str | None] = mapped_column(String(64))
    bank_key: Mapped[str | None] = mapped_column(String(160))
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))
    difficulty: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict] = mapped_column(JSON)
    source_info: Mapped[dict] = mapped_column(JSON)
    is_valid: Mapped[bool] = mapped_column(default=True)
    available: Mapped[bool] = mapped_column(default=True)
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_practice_sessions_request"),
        CheckConstraint(
            "mode IN ('chapter', 'adaptive', 'review')", name="ck_practice_sessions_mode"
        ),
        CheckConstraint(
            "(mode = 'review' AND question_source IS NULL) OR "
            "(mode != 'review' AND question_source IN ('bank', 'ai') "
            "AND question_source IS NOT NULL)",
            name="ck_practice_sessions_source",
        ),
        CheckConstraint(
            "status IN ('generating', 'ready', 'completed', 'failed')",
            name="ck_practice_sessions_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    question_source: Mapped[str | None] = mapped_column(String(8))
    settings: Mapped[dict] = mapped_column(JSON)
    source_conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="generating", index=True)
    actual_count: Mapped[int] = mapped_column(default=0)
    notice: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PracticeItem(Base):
    __tablename__ = "practice_items"
    __table_args__ = (
        UniqueConstraint("practice_session_id", "position", name="uq_practice_items_position"),
        UniqueConstraint("practice_session_id", "question_id", name="uq_practice_items_question"),
        CheckConstraint("position >= 1", name="ck_practice_items_position"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    practice_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="RESTRICT"), index=True
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column()
    snapshot: Mapped[dict] = mapped_column(JSON)
    hinted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    feedback: Mapped[dict | None] = mapped_column(JSON)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("practice_item_id", name="uq_attempts_item"),
        CheckConstraint(
            "category IN ('first_independent', 'first_hinted', 'repeat', 'review')",
            name="ck_attempts_category",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    practice_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("practice_items.id", ondelete="RESTRICT")
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(64))
    answer: Mapped[str] = mapped_column(String(16))
    is_correct: Mapped[bool] = mapped_column()
    hinted: Mapped[bool] = mapped_column()
    category: Mapped[str] = mapped_column(String(24))
    is_valid: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)


class WrongQuestion(Base):
    __tablename__ = "wrong_questions"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_wrong_questions_owner"),
        CheckConstraint("status IN ('pending', 'consolidated')", name="ck_wrong_questions_status"),
        CheckConstraint("correct_days BETWEEN 0 AND 2", name="ck_wrong_questions_days"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    correct_days: Mapped[int] = mapped_column(default=0)
    last_correct_date: Mapped[date | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class LearningReport(Base):
    __tablename__ = "learning_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_learning_reports_request"),
        CheckConstraint("from_date <= to_date", name="ck_learning_reports_dates"),
        CheckConstraint(
            "status IN ('generating', 'completed', 'failed')", name="ck_learning_reports_status"
        ),
        CheckConstraint(
            "status != 'completed' OR length(trim(content)) > 0", name="ck_learning_reports_content"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    from_date: Mapped[date] = mapped_column()
    to_date: Mapped[date] = mapped_column()
    cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="generating", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint(
            "difficulty IN ('basic', 'intermediate', 'advanced')", name="ck_resources_difficulty"
        ),
        CheckConstraint("url LIKE 'https://%' OR url LIKE 'http://%'", name="ck_resources_url"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    knowledge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(40))
    source_info: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
