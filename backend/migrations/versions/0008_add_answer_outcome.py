"""Distinguish completed answers from insufficient-material responses.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("answer_outcome", sa.String(24), nullable=True))
    # Only classify the old deterministic fallback. Preserve content, timestamps,
    # saved report snapshots and genuine model replies (including old citations).
    op.execute(
        sa.text(
            "UPDATE messages SET answer_outcome = CASE WHEN content = :fallback "
            "AND json_array_length(citations) = 0 THEN 'insufficient_materials' "
            "ELSE 'answered' END WHERE role = 'assistant' AND status = 'completed'"
        ).bindparams(
            fallback="当前资料没有找到足够依据。请补充已就绪资料、切换资料范围或把问题描述得更具体。"
        )
    )


def downgrade() -> None:
    op.drop_column("messages", "answer_outcome")
