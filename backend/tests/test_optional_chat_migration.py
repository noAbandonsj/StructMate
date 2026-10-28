from uuid import UUID

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from test_conversations import new_conversation
from test_documents import register

from capstone.core.settings import Settings
from capstone.db.models import Message
from capstone.main import create_app
from capstone.services.summaries import completed_pairs


def test_remove_outcome_deletes_obsolete_pairs_and_reports_without_compatibility(
    migrated_database, migration_config, tmp_path, monkeypatch
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        identifier = new_conversation(client, headers)
        with Session(migrated_database) as session, session.begin():
            for sequence, status in ((1, "completed"), (3, "failed")):
                question = Message(
                    conversation_id=UUID(identifier),
                    sequence=sequence,
                    role="user",
                    content=f"问题{sequence}",
                )
                session.add(question)
                session.flush()
                session.add(
                    Message(
                        conversation_id=UUID(identifier),
                        sequence=sequence + 1,
                        role="assistant",
                        reply_to_message_id=question.id,
                        content="正常讲解" if sequence == 1 else "保留的历史固定回复",
                        status=status,
                        citations=[],
                    )
                )
        report = client.post(
            "/api/v1/reports", headers=headers, json={"client_request_id": "report"}
        ).json()
        import capstone.services.reports as reports

        legacy_stats = {**report["snapshot"], "schema_version": 4}
        legacy_stats["learning"] = {**legacy_stats["learning"], "insufficient_materials": 1}
        with monkeypatch.context() as patch:
            patch.setattr(reports, "learning_stats", lambda *args: legacy_stats)
            obsolete = client.post(
                "/api/v1/reports", headers=headers, json={"client_request_id": "legacy"}
            ).json()
    command.downgrade(migration_config, "0014")
    with migrated_database.begin() as connection:
        connection.execute(
            text(
                "UPDATE messages SET status='completed', answer_outcome='insufficient_materials' "
                "WHERE sequence=4"
            )
        )
        before = [
            dict(row._mapping)
            for row in connection.execute(text("SELECT * FROM messages ORDER BY sequence"))
        ]
    command.upgrade(migration_config, "head")
    command.check(migration_config)
    with migrated_database.connect() as connection:
        assert "answer_outcome" not in {
            column["name"] for column in inspect(connection).get_columns("messages")
        }
        after = [
            dict(row._mapping)
            for row in connection.execute(text("SELECT * FROM messages ORDER BY sequence"))
        ]
        before = [row for row in before if row["sequence"] < 3]
        for row in before:
            row.pop("answer_outcome")
        assert after == before
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    with Session(migrated_database) as session:
        assert len(completed_pairs(session, UUID(identifier))) == 2
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://127.0.0.1:5173"},
            json={"username": "student", "password": "test-password"},
        )
        current = client.get("/api/v1/reports/" + report["id"]).json()
        assert current["snapshot"]["learning"]["completed_answers"] == 1
        assert "insufficient_materials" not in current["snapshot"]["learning"]
        assert current["created_at"] == report["created_at"]
        assert current["snapshot"] == report["snapshot"]
        assert client.get("/api/v1/reports/" + obsolete["id"]).status_code == 404
        assert client.get("/api/v1/learning/stats").json()["learning"]["completed_answers"] == 1
        assert client.get("/api/v1/reports/" + report["id"] + "/export").status_code == 200
