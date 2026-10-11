"""create_account_foundation

Revision ID: 0001
Revises:
Create Date: 2026-10-11 21:50:36.729623
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(code) BETWEEN 1 AND 64", name="ck_knowledge_points_code"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 100", name="ck_knowledge_points_name"),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id != id", name="ck_knowledge_points_parent"
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_knowledge_points_sort_order"),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["knowledge_points.id"],
            name="fk_knowledge_points_parent_id_knowledge_points",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_knowledge_points_code"),
    )
    with op.batch_alter_table("knowledge_points", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_points_parent_id"), ["parent_id"], unique=False
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(username) BETWEEN 3 AND 32 AND username NOT GLOB '*[^a-z0-9_]*'",
            name="ck_users_username_format",
        ),
        sa.CheckConstraint("length(display_name) BETWEEN 1 AND 32", name="ck_users_display_name"),
        sa.CheckConstraint("length(password_hash) > 0", name="ck_users_password_hash"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(token_hash) = 64 AND token_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_auth_sessions_token_hash",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry"),
        sa.CheckConstraint("length(csrf_token) > 0", name="ck_auth_sessions_csrf_token"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_auth_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    with op.batch_alter_table("auth_sessions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_auth_sessions_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_auth_sessions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("course_code", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(kind = 'personal' AND owner_id IS NOT NULL AND course_code IS NULL) OR "
            "(kind = 'course' AND owner_id IS NULL AND course_code IS NOT NULL)",
            name="ck_knowledge_bases_kind_owner",
        ),
        sa.CheckConstraint(
            "course_code IS NULL OR length(course_code) BETWEEN 1 AND 64",
            name="ck_knowledge_bases_course_code",
        ),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 100", name="ck_knowledge_bases_name"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_knowledge_bases_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_code", name="uq_knowledge_bases_course_code"),
        sa.UniqueConstraint("owner_id", name="uq_knowledge_bases_owner_id"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_bases")
    with op.batch_alter_table("auth_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_auth_sessions_user_id"))
        batch_op.drop_index(batch_op.f("ix_auth_sessions_expires_at"))

    op.drop_table("auth_sessions")
    op.drop_table("users")
    with op.batch_alter_table("knowledge_points", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_points_parent_id"))

    # SQLite checks self-references during DROP TABLE; release the catalog hierarchy first.
    op.execute("UPDATE knowledge_points SET parent_id = NULL")
    op.drop_table("knowledge_points")
