"""Add administrator roles and attributed course maintenance events.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

from capstone.db.types import UTCDateTime

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Inline column CHECK works with SQLite ADD COLUMN, avoiding a users-table
    # rebuild and preserving all foreign-key-linked learning records.
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(16),
            sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
            nullable=False,
            server_default="user",
        ),
    )
    op.create_table(
        "course_maintenance",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "action IN ('upload', 'process', 'delete')", name="ck_course_maintenance_action"
        ),
    )
    op.create_index("ix_course_maintenance_document_id", "course_maintenance", ["document_id"])


def downgrade() -> None:
    op.drop_table("course_maintenance")
    op.drop_column("users", "role")
