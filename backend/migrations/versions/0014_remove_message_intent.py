"""Remove retired answer modes from stored messages and request fingerprints.

Revision ID: 0014
Revises: 0013
"""

import json
from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def upgrade():
    connection = op.get_bind()
    # Convert original-send keys once. Retry fingerprints depend on the original
    # answer ID and must remain untouched. Runtime code needs no legacy adapter.
    rows = connection.execute(
        sa.text(
            "SELECT a.id, a.request_hash, a.intent, q.content FROM messages a "
            "JOIN messages q ON q.id=a.reply_to_message_id "
            "WHERE a.role='assistant' AND a.request_hash IS NOT NULL"
        )
    ).all()
    for row in rows:
        if row.request_hash == digest({"content": row.content, "intent": row.intent}):
            connection.execute(
                sa.text("UPDATE messages SET request_hash=:hash WHERE id=:id"),
                {"id": row.id, "hash": digest({"content": row.content})},
            )
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint("ck_messages_intent", type_="check")
        batch.drop_column("intent")


def downgrade():
    # Removed modes cannot be reconstructed; old code resumes with its default.
    with op.batch_alter_table("messages") as batch:
        batch.add_column(
            sa.Column("intent", sa.String(16), nullable=False, server_default="explain")
        )
        batch.create_check_constraint(
            "ck_messages_intent", "intent IN ('explain', 'hint', 'example')"
        )
    with op.batch_alter_table("messages") as batch:
        batch.alter_column("intent", server_default=None)
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT a.id, a.request_hash, q.content FROM messages a "
            "JOIN messages q ON q.id=a.reply_to_message_id "
            "WHERE a.role='assistant' AND a.request_hash IS NOT NULL"
        )
    ).all()
    for row in rows:
        if row.request_hash == digest({"content": row.content}):
            connection.execute(
                sa.text("UPDATE messages SET request_hash=:hash WHERE id=:id"),
                {"id": row.id, "hash": digest({"content": row.content, "intent": "explain"})},
            )
