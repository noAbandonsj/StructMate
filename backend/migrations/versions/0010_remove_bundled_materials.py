"""Remove bundled learning materials; retain historical references and user uploads.

Revision ID: 0010
Revises: 0009
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM resources WHERE code IN "
        "('ods-array', 'ods-linked', 'ods-single', 'ods-array-queue', "
        "'ods-tree', 'ods-tree-algorithms')"
    )
    connection = op.get_bind()
    documents = connection.execute(
        sa.text(
            "SELECT d.id, d.index_revision FROM documents d "
            "JOIN knowledge_bases k ON k.id = d.knowledge_base_id "
            "WHERE k.kind = 'course' AND k.course_code = 'data-structures' "
            "AND d.status != 'deleted' "
            "AND json_extract(d.source_info, '$.content_code') "
            "IN ('linear-list', 'stack-queue', 'binary-tree') "
            "AND NOT EXISTS (SELECT 1 FROM course_maintenance m "
            "WHERE m.document_id = d.id AND m.action = 'upload')"
        )
    ).all()
    for identifier, index_revision in documents:
        # Use the existing deletion worker to clean blobs and vectors. Chunks and
        # message citation snapshots remain available for historical attribution.
        connection.execute(
            sa.text(
                "UPDATE documents SET status = 'deleted', stage = 'cleaning', "
                "dedup_key = NULL, deleted_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP, error_code = NULL, error_message = NULL "
                "WHERE id = :id"
            ),
            {"id": identifier},
        )
        connection.execute(
            sa.text(
                "INSERT INTO document_tasks "
                "(id, document_id, request_id, index_revision, action, status, "
                "attempt_count, created_at, updated_at) "
                "VALUES (:task_id, :id, 'delete', :revision, 'delete', 'queued', "
                "0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"task_id": uuid4().hex, "id": identifier, "revision": index_revision},
        )


def downgrade() -> None:
    # A schema downgrade must not resurrect removed learning materials.
    pass
