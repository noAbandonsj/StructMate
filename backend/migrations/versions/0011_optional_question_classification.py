"""Allow theme-based questions without a fixed knowledge-point classification.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def immutable_question() -> None:
    op.execute("""
        CREATE TRIGGER immutable_distributed_question
        BEFORE UPDATE OF content, source_info, owner_id, knowledge_point_id,
                         source_type, bank_code, bank_key,
                         content_fingerprint, difficulty ON questions
        WHEN EXISTS (SELECT 1 FROM practice_items WHERE question_id = OLD.id)
        BEGIN SELECT RAISE(ABORT, 'distributed question is immutable'); END
    """)


def upgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.alter_column("knowledge_point_id", existing_type=sa.Uuid(), nullable=True)
    immutable_question()


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM questions WHERE knowledge_point_id IS NULL LIMIT 1"))
        .first()
    ):
        raise RuntimeError("存在未分类的主题练习题，无法降级为强制知识点分类")
    with op.batch_alter_table("questions") as batch:
        batch.alter_column("knowledge_point_id", existing_type=sa.Uuid(), nullable=False)
    immutable_question()
