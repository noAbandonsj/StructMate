"""Retire material-gated answer outcomes; chat retrieval is optional.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Retired fixed replies and their questions are disposable. Remove the whole
    # pair, including failed retries of that question, rather than adapt old data.
    questions = (
        connection.execute(
            sa.text(
                "SELECT DISTINCT reply_to_message_id FROM messages "
                "WHERE answer_outcome='insufficient_materials' "
                "AND reply_to_message_id IS NOT NULL"
            )
        )
        .scalars()
        .all()
    )
    for question_id in questions:
        connection.execute(
            sa.text("DELETE FROM messages WHERE reply_to_message_id=:id"), {"id": question_id}
        )
        connection.execute(sa.text("DELETE FROM messages WHERE id=:id"), {"id": question_id})
    connection.execute(
        sa.text("DELETE FROM messages WHERE answer_outcome='insufficient_materials'")
    )
    connection.execute(
        sa.text(
            "DELETE FROM learning_reports WHERE "
            "COALESCE(json_extract(snapshot, '$.schema_version'), 0) < 5"
        )
    )
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("answer_outcome")


def downgrade():
    # Deleted learning history cannot be reconstructed on downgrade.
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("answer_outcome", sa.String(24), nullable=True))
    op.execute(
        "UPDATE messages SET answer_outcome='answered' "
        "WHERE role='assistant' AND status='completed'"
    )
