"""Replace the retired knowledge-point tree with the flat chapter model.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

REFERENCES = ("documents", "document_chunks", "conversations", "questions", "resources")


def clear_learning_history():
    # Explicitly authorized reset: accounts, libraries, uploaded documents,
    # document tasks and administrator-maintained resources remain intact.
    for table in (
        "attempts",
        "wrong_questions",
        "practice_items",
        "practice_sessions",
        "learning_reports",
        "messages",
        "conversations",
        "questions",
    ):
        op.execute(sa.text(f"DELETE FROM {table}"))


def question_trigger(legacy=False):
    columns = (
        "content, source_info, owner_id, knowledge_point_id, source_type, "
        "bank_code, bank_key, content_fingerprint, difficulty"
        if legacy
        else "content, source_info, owner_id, chapter_id, content_fingerprint, difficulty"
    )
    op.execute(f"""CREATE TRIGGER immutable_distributed_question
        BEFORE UPDATE OF {columns} ON questions
        WHEN EXISTS (SELECT 1 FROM practice_items WHERE question_id = OLD.id)
        BEGIN SELECT RAISE(ABORT, 'distributed question is immutable'); END""")


def snapshot_trigger():
    op.execute("""CREATE TRIGGER immutable_practice_snapshot
        BEFORE UPDATE OF snapshot, question_id, practice_session_id, position ON practice_items
        BEGIN SELECT RAISE(ABORT, 'distributed snapshot is immutable'); END""")


def constraints(batch, old, new):
    batch.drop_constraint(f"uq_{old}_code", type_="unique")
    for field in ("code", "name", "sort_order"):
        batch.drop_constraint(f"ck_{old}_{field}", type_="check")
    batch.create_unique_constraint(f"uq_{new}_code", ["code"])
    batch.create_check_constraint(f"ck_{new}_code", "length(code) BETWEEN 1 AND 64")
    batch.create_check_constraint(f"ck_{new}_name", "length(name) BETWEEN 1 AND 100")
    batch.create_check_constraint(f"ck_{new}_sort_order", "sort_order >= 0")


def rename_references(old, new):
    for table in REFERENCES:
        op.alter_column(table, old, new_column_name=new, existing_type=sa.Uuid())
    for table in ("questions", "resources"):
        op.drop_index(f"ix_{table}_{old}", table_name=table)
        op.create_index(f"ix_{table}_{new}", table, [new])


def upgrade():
    clear_learning_history()
    op.execute("DROP TRIGGER immutable_distributed_question")
    op.execute("DROP TRIGGER immutable_practice_snapshot")
    op.rename_table("knowledge_points", "chapters")
    with op.batch_alter_table("chapters") as batch:
        constraints(batch, "knowledge_points", "chapters")
        batch.drop_constraint("fk_knowledge_points_parent_id_knowledge_points", type_="foreignkey")
        batch.drop_constraint("ck_knowledge_points_parent", type_="check")
        batch.drop_index("ix_knowledge_points_parent_id")
        batch.drop_column("parent_id")
    rename_references("knowledge_point_id", "chapter_id")
    with op.batch_alter_table("questions") as batch:
        batch.drop_constraint("ck_questions_source_owner", type_="check")
        batch.drop_constraint("uq_questions_bank_key", type_="unique")
        for column in ("source_type", "bank_code", "bank_key", "available"):
            batch.drop_column(column)
        for column in ("owner_id", "chapter_id", "content_fingerprint"):
            batch.alter_column(column, nullable=False)
    with op.batch_alter_table("practice_sessions") as batch:
        batch.drop_constraint("ck_practice_sessions_source", type_="check")
        batch.drop_constraint("ck_practice_sessions_mode", type_="check")
        batch.drop_column("question_source")
        batch.create_check_constraint("ck_practice_sessions_mode", "mode IN ('chapter', 'review')")
    with op.batch_alter_table("practice_items") as batch:
        batch.drop_column("feedback")
    question_trigger()
    snapshot_trigger()


def downgrade():
    clear_learning_history()
    op.execute("DROP TRIGGER immutable_distributed_question")
    op.execute("DROP TRIGGER immutable_practice_snapshot")
    with op.batch_alter_table("questions") as batch:
        batch.add_column(sa.Column("source_type", sa.String(8), nullable=False))
        batch.add_column(sa.Column("bank_code", sa.String(64)))
        batch.add_column(sa.Column("bank_key", sa.String(160)))
        batch.add_column(sa.Column("available", sa.Boolean(), nullable=False))
        batch.create_unique_constraint("uq_questions_bank_key", ["bank_key"])
        batch.create_check_constraint(
            "ck_questions_source_owner",
            "(source_type = 'bank' AND owner_id IS NULL AND bank_key IS NOT NULL) OR "
            "(source_type = 'ai' AND owner_id IS NOT NULL AND bank_key IS NULL)",
        )
        for column in ("owner_id", "chapter_id", "content_fingerprint"):
            batch.alter_column(column, nullable=True)
    with op.batch_alter_table("practice_sessions") as batch:
        batch.drop_constraint("ck_practice_sessions_mode", type_="check")
        batch.add_column(sa.Column("question_source", sa.String(8)))
        batch.create_check_constraint(
            "ck_practice_sessions_mode", "mode IN ('chapter', 'adaptive', 'review')"
        )
        batch.create_check_constraint(
            "ck_practice_sessions_source",
            "(mode = 'review' AND question_source IS NULL) OR "
            "(mode != 'review' AND question_source IN ('bank', 'ai') "
            "AND question_source IS NOT NULL)",
        )
    with op.batch_alter_table("practice_items") as batch:
        batch.add_column(sa.Column("feedback", sa.JSON()))
    rename_references("chapter_id", "knowledge_point_id")
    with op.batch_alter_table("chapters") as batch:
        constraints(batch, "chapters", "knowledge_points")
        batch.add_column(sa.Column("parent_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_knowledge_points_parent_id_knowledge_points",
            "chapters",
            ["parent_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_knowledge_points_parent", "parent_id IS NULL OR parent_id != id"
        )
        batch.create_index("ix_knowledge_points_parent_id", ["parent_id"])
    op.rename_table("chapters", "knowledge_points")
    question_trigger(legacy=True)
    snapshot_trigger()
