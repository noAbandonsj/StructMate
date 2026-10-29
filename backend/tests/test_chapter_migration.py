"""The cleanup migration removes learning history and preserves maintained data."""

from uuid import UUID

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_documents import register
from test_practice import answer_for, create, items, submit

from capstone.core.settings import Settings
from capstone.db.models import Chapter, Question
from capstone.main import create_app
from capstone.services.documents import create_document
from capstone.services.storage import BlobStore

HISTORY = (
    "conversations",
    "messages",
    "questions",
    "practice_sessions",
    "practice_items",
    "attempts",
    "wrong_questions",
    "learning_reports",
)


def test_cleanup_removes_old_history_and_schema_but_preserves_accounts_and_files(
    practice_db, migration_config, tmp_path
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        library, headers = register(client)
        exercise = create(client, headers, count=1)
        question = items(client, exercise["id"])[0]
        assert (
            submit(client, headers, question, answer_for(practice_db, question, False)).status_code
            == 201
        )
        client.post("/api/v1/reports", headers=headers, json={"client_request_id": "report"})
        cookies = client.cookies
        with Session(practice_db) as session:
            chapter = session.scalar(select(Chapter.id))
            document, _ = create_document(
                session,
                BlobStore(settings.uploads_dir),
                UUID(library),
                "retained.md",
                b"retained",
                10000,
                chapter,
            )
            document_id = document.id
    with practice_db.connect() as connection:
        accounts = connection.execute(text("SELECT * FROM users ORDER BY id")).all()
        documents = connection.execute(text("SELECT * FROM documents ORDER BY id")).all()
        old = {
            table: [
                dict(row._mapping) for row in connection.execute(text(f"SELECT * FROM {table}"))
            ]
            for table in HISTORY
        }
    command.downgrade(migration_config, "0012")
    # The frozen legacy schema is used only to exercise the destructive upgrade.
    with practice_db.begin() as connection:
        metadata = MetaData()
        for name, rows in old.items():
            for row in rows:
                if "chapter_id" in row:
                    row["knowledge_point_id"] = row.pop("chapter_id")
                if name == "questions":
                    row.update(source_type="ai", bank_code=None, bank_key=None, available=True)
                if name == "practice_sessions":
                    row["question_source"] = "ai"
                if name == "practice_items":
                    row["feedback"] = None
                if name == "messages":
                    row["intent"] = "explain"
                if name == "attempts" and row["category"] == "first":
                    row["category"] = "first_hinted" if row["hinted"] else "first_independent"
            if rows:
                table = Table(name, metadata, autoload_with=connection)
                # Values read through sqlite text are already serialized.
                keys = list(rows[0])
                connection.execute(
                    text(
                        f"INSERT INTO {name} ({','.join(keys)}) "
                        f"VALUES ({','.join(':' + key for key in keys)})"
                    ),
                    rows,
                )
    command.upgrade(migration_config, "head")
    command.check(migration_config)
    with practice_db.connect() as connection:
        assert connection.execute(text("SELECT * FROM users ORDER BY id")).all() == accounts
        assert connection.execute(text("SELECT * FROM documents ORDER BY id")).all() == documents
        for table in HISTORY:
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        schema = inspect(connection)
        assert "knowledge_points" not in schema.get_table_names()
        assert "parent_id" not in {column["name"] for column in schema.get_columns("chapters")}
        assert not {"source_type", "bank_key", "bank_code", "available"} & {
            column["name"] for column in schema.get_columns("questions")
        }
    with TestClient(create_app(settings)) as client:
        client.cookies.update(cookies)
        assert client.get(f"/api/v1/documents/{document_id}").status_code == 200
        assert client.get("/api/v1/chapters").json()["total"] == 8
        exercise = create(client, headers, "new", count=1)
        question = items(client, exercise["id"])[0]
        assert submit(client, headers, question, "true").status_code == 201
        with pytest.raises(IntegrityError), Session(practice_db) as session, session.begin():
            session.execute(update(Question).values(content={}))
