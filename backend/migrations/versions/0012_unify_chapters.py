"""Consolidate the legacy catalog into eight chapters without rewriting snapshots.

Revision ID: 0012
Revises: 0011
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# Frozen migration data; application catalog changes must not change this migration.
CHAPTERS = (
    ("complexity", "绪论与算法分析", 10),
    ("linear-list", "线性表", 20),
    ("stack-queue", "栈与队列", 30),
    ("strings-arrays", "串、数组与广义表", 40),
    ("tree", "树与二叉树", 50),
    ("graph", "图", 60),
    ("search", "查找", 70),
    ("sort", "排序", 80),
)


def upgrade():
    connection = op.get_bind()
    old = connection.execute(sa.text("SELECT id, code FROM knowledge_points")).all()
    if not old:
        return  # Explicit initialization still belongs to capstone.seed.
    ids = dict((code, identifier) for identifier, code in old)
    valid = {code for code, _, _ in CHAPTERS}
    mapping = {}
    for identifier, code in old:
        target = code.split(".")[0]
        if target == "hash" or code == "tree.bst":
            target = "search"
        if target not in valid:
            raise RuntimeError(f"未知课程分类 {code}，请先确认其章节归属")
        mapping[identifier] = target
    for code, name, order in CHAPTERS:
        if code not in ids:
            ids[code] = uuid4().hex
            connection.execute(
                sa.text(
                    "INSERT INTO knowledge_points (id, code, name, sort_order) "
                    "VALUES (:id, :code, :name, :sort_order)"
                ),
                dict(id=ids[code], code=code, name=name, sort_order=order),
            )
        else:
            connection.execute(
                sa.text(
                    "UPDATE knowledge_points SET name=:name, parent_id=NULL, "
                    "sort_order=:sort_order WHERE id=:id"
                ),
                dict(id=ids[code], name=name, sort_order=order),
            )
    # Only classification changes are authorized here. Question contents, distributed
    # snapshots, attempts, report snapshots and stored request hashes remain untouched.
    op.execute("DROP TRIGGER immutable_distributed_question")
    for identifier, target in mapping.items():
        if identifier == ids[target]:
            continue
        for table in ("documents", "document_chunks", "conversations", "questions", "resources"):
            connection.execute(
                sa.text(
                    f"UPDATE {table} SET knowledge_point_id=:target WHERE knowledge_point_id=:old"
                ),
                dict(target=ids[target], old=identifier),
            )
    op.execute("""
        CREATE TRIGGER immutable_distributed_question
        BEFORE UPDATE OF content, source_info, owner_id, knowledge_point_id,
                         source_type, bank_code, bank_key,
                         content_fingerprint, difficulty ON questions
        WHEN EXISTS (SELECT 1 FROM practice_items WHERE question_id = OLD.id)
        BEGIN SELECT RAISE(ABORT, 'distributed question is immutable'); END
    """)
    # Detach removed children first so RESTRICT self-references cannot block deletion.
    removed = [identifier for identifier, target in mapping.items() if identifier != ids[target]]
    for identifier in removed:
        connection.execute(
            sa.text("UPDATE knowledge_points SET parent_id=NULL WHERE id=:id"), dict(id=identifier)
        )
    for identifier in removed:
        connection.execute(
            sa.text("DELETE FROM knowledge_points WHERE id=:id"), dict(id=identifier)
        )


def downgrade():
    # This is a content migration, with no schema to undo. Splitting merged records
    # would invent their former classification; restore a pre-migration backup instead.
    pass
