from uuid import uuid4

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from test_documents import TestEmbedding, register, upload, wait_document

from capstone.core.settings import Settings
from capstone.main import create_app
from capstone.seed import seed_course_data


def test_retiring_recommendations_only_drops_resources(
    migrated_database, migration_config, tmp_path
):
    seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, embedding_service=TestEmbedding())) as client:
        library, headers = register(client)
        document = upload(client, library, headers)["document"]["id"]
        wait_document(client, document, "ready")
        assert client.get(f"/api/v1/documents/{document}/chunks").json()["total"] > 0
        assert "/api/v1/recommendations" not in client.app.openapi()["paths"]
        assert client.get("/api/v1/recommendations").status_code == 404

    command.downgrade(migration_config, "0015")
    with migrated_database.begin() as connection:
        chapter = connection.exec_driver_sql("SELECT id FROM chapters LIMIT 1").scalar_one()
        connection.exec_driver_sql(
            "INSERT INTO resources "
            "(id, code, chapter_id, title, description, url, difficulty, language, "
            "source_info, is_active, updated_at) VALUES "
            "(?, 'maintained-link', ?, '旧资料推荐', '待删除外链', 'https://example.org', "
            "'basic', '中文', '{}', 1, CURRENT_TIMESTAMP)",
            (uuid4().hex, chapter),
        )
    tables = set(inspect(migrated_database).get_table_names()) - {"alembic_version", "resources"}

    def snapshot():
        with migrated_database.connect() as connection:
            return {
                table: connection.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY rowid').all()
                for table in tables
            }

    before = snapshot()
    command.upgrade(migration_config, "head")
    assert not inspect(migrated_database).has_table("resources")
    assert snapshot() == before
    command.check(migration_config)
    with migrated_database.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"

    # Downgrade restores an empty schema for historical migrations, not old data.
    command.downgrade(migration_config, "0015")
    with migrated_database.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM resources").scalar_one() == 0
    command.upgrade(migration_config, "head")
    assert snapshot() == before
