"""Merge first attempts while retaining recorded hint usage.

Revision ID: 0017
Revises: 0016
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("attempts") as batch:
        batch.drop_constraint("ck_attempts_category", type_="check")
    op.execute(
        "UPDATE attempts SET category='first' "
        "WHERE category IN ('first_independent', 'first_hinted')"
    )
    with op.batch_alter_table("attempts") as batch:
        batch.create_check_constraint(
            "ck_attempts_category", "category IN ('first', 'repeat', 'review')"
        )


def downgrade():
    with op.batch_alter_table("attempts") as batch:
        batch.drop_constraint("ck_attempts_category", type_="check")
    op.execute(
        "UPDATE attempts SET category=CASE WHEN hinted THEN 'first_hinted' "
        "ELSE 'first_independent' END WHERE category='first'"
    )
    with op.batch_alter_table("attempts") as batch:
        batch.create_check_constraint(
            "ck_attempts_category",
            "category IN ('first_independent', 'first_hinted', 'repeat', 'review')",
        )
