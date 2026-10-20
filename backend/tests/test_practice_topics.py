import json
from uuid import UUID

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_documents import TestEmbedding, register, upload, wait_document
from test_practice import answer_for, create, items, submit, wait_practice

from capstone.core.settings import Settings
from capstone.db.models import Question, User
from capstone.main import create_app
from capstone.seed import seed_course_data
from capstone.services.documents import create_document, queue_delete
from capstone.services.storage import BlobStore


class TopicGeneration:
    available = True

    def __init__(self, cited=False, before_review=None):
        self.cited, self.before_review = cited, before_review
        self.prompts = []

    def stream(self, messages, cancelled):
        self.prompts.append(messages)
        if len(self.prompts) == 2 and self.before_review:
            self.before_review()
        yield json.dumps(
            {
                "items": [
                    {
                        "type": "true_false",
                        "stem": "队列遵循先进先出的规则。",
                        "options": [
                            {"key": "true", "text": "正确"},
                            {"key": "false", "text": "错误"},
                        ],
                        "answer": "true",
                        "explanation": "先入队的元素先出队。",
                        "difficulty": "basic",
                        "citation_numbers": [1] if self.cited else [],
                    }
                ]
            },
            ensure_ascii=False,
        )


def test_topic_only_needs_no_catalog_and_reaches_wrong_questions_and_reports(
    migrated_database, tmp_path
):
    generation = TopicGeneration()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=generation)) as client:
        _, headers = register(client)
        topic = "队列|FIFO"
        exercise = create(client, headers, question_source="ai", topic=topic, count=1)
        wait_practice(client, exercise["id"])
        assert exercise["title"] == topic
        item = items(client, exercise["id"])[0]
        assert item["knowledge_point_id"] is None
        result = submit(client, headers, item, "false").json()
        assert result["source_info"]["basis"] == "general_knowledge"
        assert result["source_info"]["citations"] == []
        wrong = client.get("/api/v1/wrong-questions?search=FIFO").json()
        assert wrong["total"] == 1 and wrong["items"][0]["topic"] == topic
        assert client.get("/api/v1/wrong-questions?search=栈").json()["total"] == 0
        stats = client.get("/api/v1/learning/stats").json()
        assert stats["attempts"]["count"] == 1
        assert stats["topics"][0]["error_count"] == 1
        assert stats["topics"][0]["materials"] == []
        assert stats["question_types"]["true_false"]["count"] == 1
        assert client.get("/api/v1/learning/performance").status_code == 200
        assert len(generation.prompts) == 2
        report = client.post(
            "/api/v1/reports", headers=headers, json={"client_request_id": "topic-report"}
        ).json()
        exported = client.get(f"/api/v1/reports/{report['id']}/export").text
        assert "队列\\|FIFO" in exported
        assert "\n实际检索片段：[]" in generation.prompts[0][0]["content"]
        payload = json.loads(generation.prompts[0][1]["content"])
        assert payload["topic"] == topic and "mode" not in payload


def test_topic_or_material_is_required_and_invalid_requests_create_no_sessions(
    migrated_database, tmp_path
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        for topic in ("", "   ", "\n\t"):
            response = client.post(
                "/api/v1/practice-sessions",
                headers=headers,
                json={
                    "client_request_id": "empty-topic",
                    "question_source": "ai",
                    "topic": topic,
                },
            )
            assert response.status_code == 422
        assert client.get("/api/v1/practice-sessions").json()["total"] == 0


def test_material_selection_is_private_current_and_supports_material_only_practice(
    migrated_database, tmp_path
):
    course = seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    generation = TopicGeneration(cited=True)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as client:
        library, headers = register(client)
        other = TestClient(client.app)
        try:
            other_library, other_headers = register(other, "outsider")
            mine = upload(client, library, headers)["document"]["id"]
            private = upload(other, other_library, other_headers)["document"]["id"]
            wait_document(client, mine, "ready")
            wait_document(other, private, "ready")
            with Session(migrated_database) as session:
                document, _ = create_document(
                    session,
                    BlobStore(settings.uploads_dir),
                    course.course_id,
                    "公共队列资料.md",
                    "# 队列\n\n队列先进先出。".encode(),
                    10000,
                )
                public = str(document.id)
            wait_document(client, public, "ready")
            candidates = client.get("/api/v1/practice-sessions/materials?page_size=1").json()
            assert candidates["total"] == 2 and len(candidates["items"]) == 1
            candidates = client.get("/api/v1/practice-sessions/materials").json()["items"]
            assert {item["id"] for item in candidates} == {mine, public}
            denied = client.post(
                "/api/v1/practice-sessions",
                headers=headers,
                json={
                    "client_request_id": "private",
                    "question_source": "ai",
                    "document_ids": [private],
                },
            )
            assert denied.status_code == 404
            exercise = create(client, headers, question_source="ai", count=1, document_ids=[public])
            wait_practice(client, exercise["id"])
            assert exercise["title"] == "公共队列资料.md"
            item = items(client, exercise["id"])[0]
            result = submit(client, headers, item, "false").json()
            assert result["source_info"]["basis"] == "selected_materials"
            assert {source["document_id"] for source in result["source_info"]["citations"]} == {
                public
            }
            assert client.get("/api/v1/learning/stats").json()["topics"][0]["materials"] == [
                "公共队列资料.md"
            ]
            assert client.delete("/api/v1/documents/" + mine, headers=headers).status_code == 202
            stale = client.post(
                "/api/v1/practice-sessions",
                headers=headers,
                json={
                    "client_request_id": "deleted",
                    "question_source": "ai",
                    "document_ids": [mine],
                },
            )
            assert stale.status_code == 409
        finally:
            other.close()


def test_material_deleted_during_generation_is_not_published(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    target = {}

    def remove():
        with Session(migrated_database) as session:
            queue_delete(session, UUID(target["document"]), target["user"])

    generation = TopicGeneration(cited=True, before_review=remove)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as client:
        library, headers = register(client)
        target["document"] = upload(client, library, headers)["document"]["id"]
        wait_document(client, target["document"], "ready")
        with Session(migrated_database) as session:
            target["user"] = session.scalar(select(User.id))
        exercise = create(
            client, headers, question_source="ai", count=1, document_ids=[target["document"]]
        )
        failed = wait_practice(client, exercise["id"], "failed")
        assert failed["error_code"] == "PRACTICE_DOCUMENT_NOT_READY"
        assert items(client, exercise["id"]) == []
        with Session(migrated_database) as session:
            assert session.scalar(select(func.count()).select_from(Question)) == 0


def test_nullable_classification_migration_preserves_existing_attempts_and_triggers(
    bank_database, migration_config, tmp_path
):
    command.downgrade(migration_config, "0010")
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        exercise = create(client, headers, count=1)
        item = items(client, exercise["id"])[0]
        submit(client, headers, item, answer_for(bank_database, item, False))
    with bank_database.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
            for table in ("questions", "practice_items", "attempts", "wrong_questions")
        }
    command.upgrade(migration_config, "head")
    with bank_database.connect() as connection:
        for table, expected in before.items():
            assert connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all() == expected
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
    with pytest.raises(IntegrityError), Session(bank_database) as session, session.begin():
        session.execute(
            update(Question)
            .where(Question.id == UUID(item["question_id"]))
            .values(knowledge_point_id=None)
        )
