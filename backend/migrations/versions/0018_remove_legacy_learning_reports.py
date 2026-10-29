"""Remove pre-launch reports with retired statistics snapshots.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "DELETE FROM learning_reports "
        "WHERE COALESCE(CAST(json_extract(snapshot, '$.schema_version') AS INTEGER), 0) < 6"
    )


def downgrade():
    # Deleted pre-launch reports can only be recovered from a backup.
    pass
