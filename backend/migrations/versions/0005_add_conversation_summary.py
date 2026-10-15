"""Add the latest conversation summary; no summary history table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("summary_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Native DROP COLUMN preserves the table and its inbound foreign keys.
    op.drop_column("conversations", "summary_data")
