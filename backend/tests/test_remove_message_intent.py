import json
from hashlib import sha256
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


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def test_remove_modes_preserves_messages_and_request_keys(
    migrated_database, migration_config, tmp_path
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    content = "只给我提示，先不要给出完整答案。"
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        conversation = new_conversation(client, headers)
        cookies = client.cookies
        with Session(migrated_database) as session, session.begin():
            question = Message(
                conversation_id=UUID(conversation),
                sequence=1,
                role="user",
                content=content,
                status="completed",
            )
            session.add(question)
            session.flush()
            answer = Message(
                conversation_id=UUID(conversation),
                sequence=2,
                role="assistant",
                reply_to_message_id=question.id,
                content="保留的部分回答",
                status="failed",
                request_id="original",
                request_hash=digest({"content": content}),
                scope_snapshot={"scope": "combined", "document_ids": []},
            )
            session.add(answer)
            session.flush()
            answer_id = answer.id
            retry_hash = digest({"retry": str(answer_id)})
            session.add(
                Message(
                    conversation_id=UUID(conversation),
                    sequence=3,
                    role="assistant",
                    reply_to_message_id=question.id,
                    status="cancelled",
                    request_id="retry",
                    request_hash=retry_hash,
                    scope_snapshot=answer.scope_snapshot,
                )
            )
    command.downgrade(migration_config, "0013")
    with migrated_database.begin() as connection:
        connection.execute(text("UPDATE messages SET intent='hint'"))
        connection.execute(
            text("UPDATE messages SET request_hash=:hash WHERE request_id='original'"),
            {"hash": digest({"content": content, "intent": "hint"})},
        )
        before = [
            dict(row._mapping)
            for row in connection.execute(text("SELECT * FROM messages ORDER BY sequence"))
        ]
    command.upgrade(migration_config, "head")
    command.check(migration_config)
    with migrated_database.connect() as connection:
        schema = inspect(connection)
        assert "intent" not in {column["name"] for column in schema.get_columns("messages")}
        assert "ck_messages_intent" not in {
            rule["name"] for rule in schema.get_check_constraints("messages")
        }
        after = [
            dict(row._mapping)
            for row in connection.execute(text("SELECT * FROM messages ORDER BY sequence"))
        ]
        for row in before:
            row.pop("intent")
            if row["request_id"] == "original":
                row["request_hash"] = digest({"content": content})
        assert after == before
        assert after[2]["request_hash"] == retry_hash
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    with TestClient(create_app(settings)) as client:
        client.cookies.update(cookies)
        body = {"content": content, "client_request_id": "original"}
        replay = client.post(
            f"/api/v1/conversations/{conversation}/messages", headers=headers, json=body
        )
        assert replay.status_code == 202
        assert replay.json()["assistant_message_id"] == str(answer_id)
        messages = client.get(f"/api/v1/conversations/{conversation}/messages").json()["items"]
        assert len(messages) == 3 and all("intent" not in message for message in messages)
        for mode in ("explain", "hint", "example"):
            retired = client.post(
                f"/api/v1/conversations/{conversation}/messages",
                headers=headers,
                json={**body, "client_request_id": "retired", "intent": mode},
            )
            assert retired.status_code == 422
        assert client.get(f"/api/v1/conversations/{conversation}/messages").json()["total"] == 3
