"""Remove the retired reading recommendation resource store.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("resources")


def downgrade():
    # Recreate the former schema only; deleted recommendations are not restored.
    op.create_table(
        "resources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(16), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("source_info", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "difficulty IN ('basic', 'intermediate', 'advanced')", name="ck_resources_difficulty"
        ),
        sa.CheckConstraint("url LIKE 'https://%' OR url LIKE 'http://%'", name="ck_resources_url"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_resources_chapter_id", "resources", ["chapter_id"])
