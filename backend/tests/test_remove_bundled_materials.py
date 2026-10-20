import os
import subprocess
import sys
import time
from uuid import UUID

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_documents import TestEmbedding, register

from capstone.core.settings import REPOSITORY_ROOT, Settings
from capstone.db.models import (
    Document,
    DocumentChunk,
    DocumentTask,
    Resource,
    User,
)
from capstone.import_course import import_course_data
from capstone.main import create_app
from capstone.manage_resources import import_resources
from capstone.seed import seed_course_data
from capstone.services.documents import create_document
from capstone.services.storage import BlobStore

FIXTURES = REPOSITORY_ROOT / "backend/tests/fixtures"


@pytest.mark.parametrize(
    ("module", "option"),
    [("capstone.import_course", "--directory"), ("capstone.manage_resources", "--file")],
)
def test_import_commands_have_no_default_materials(migrated_database, tmp_path, module, option):
    seed_course_data(migrated_database)
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", module],
        env={**os.environ, "CAPSTONE_DATA_DIR": str(tmp_path)},
        capture_output=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 2 and option in result.stderr
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
        assert session.scalar(select(func.count()).select_from(Resource)) == 0


def test_upgrade_removes_only_bundled_materials_and_cleans_files(
    migrated_database, migration_config, tmp_path
):
    command.downgrade(migration_config, "0009")
    course = seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    store = BlobStore(settings.uploads_dir)
    assert import_course_data(migrated_database, settings, FIXTURES / "course") == (3, 0, 0)
    assert import_resources(migrated_database, FIXTURES / "resources.json") == (6, 0, 0)
    with TestClient(create_app(settings, embedding_service=TestEmbedding())) as client:
        library, _ = register(client)
        with Session(migrated_database) as session, session.begin():
            actor = session.scalar(select(User).where(User.username == "student"))
            actor.role = "admin"
            actor_id = actor.id
            point = session.scalar(select(Resource.knowledge_point_id).limit(1))
            session.add(
                Resource(
                    code="admin-resource",
                    knowledge_point_id=point,
                    title="管理员维护的外链",
                    description="管理员登记",
                    url="https://example.org/admin",
                    difficulty="basic",
                    language="中文",
                    source_info={"author": "管理员"},
                )
            )
        with Session(migrated_database) as session:
            admin_document, _ = create_document(
                session,
                store,
                course.course_id,
                "管理员资料.md",
                "# 管理员上传\n\n保留此资料。".encode(),
                10000,
                source_info={"content_code": "linear-list"},
                course_actor_id=actor_id,
            )
            admin_id = admin_document.id
            personal_document, _ = create_document(
                session,
                store,
                UUID(library),
                "个人资料.md",
                "# 个人上传\n\n保留个人资料。".encode(),
                10000,
                source_info={"content_code": "linear-list"},
            )
            personal_id = personal_document.id
        # Let the worker finish before exercising an upgrade of an existing DB.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with Session(migrated_database) as session:
                if (
                    session.scalar(
                        select(func.count()).select_from(Document).where(Document.status != "ready")
                    )
                    == 0
                ):
                    break
            time.sleep(0.05)
        else:
            pytest.fail("Documents did not finish processing")

    with Session(migrated_database) as session:
        bundled = session.scalars(
            select(Document).where(Document.id.not_in([admin_id, personal_id]))
        ).all()
        bundled_ids = [document.id for document in bundled]
        storage_keys = [document.storage_key for document in bundled]
        chunk_count = session.scalar(select(func.count()).select_from(DocumentChunk))
        assert len(bundled_ids) == 3 and chunk_count > 0
    command.upgrade(migration_config, "head")
    # Replaying the migration must not restore content or duplicate delete tasks.
    command.downgrade(migration_config, "0009")
    command.upgrade(migration_config, "head")
    with Session(migrated_database) as session:
        assert session.scalars(select(Resource.code)).all() == ["admin-resource"]
        for identifier in bundled_ids:
            document = session.get(Document, identifier)
            assert document.status == "deleted" and document.dedup_key is None
            assert document.deleted_at is not None and document.stage == "cleaning"
        assert session.get(Document, admin_id).status == "ready"
        assert session.get(Document, personal_id).status == "ready"
        assert session.scalar(select(func.count()).select_from(DocumentChunk)) == chunk_count
        assert (
            session.scalar(
                select(func.count())
                .select_from(DocumentTask)
                .where(DocumentTask.action == "delete")
            )
            == 3
        )
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []

    with TestClient(create_app(settings, embedding_service=TestEmbedding())):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with Session(migrated_database) as session:
                if all(
                    session.get(Document, identifier).stage == "complete"
                    for identifier in bundled_ids
                ):
                    break
            time.sleep(0.05)
        else:
            pytest.fail("Bundled material cleanup did not complete")
    assert all(not (settings.uploads_dir / key).exists() for key in storage_keys)
