import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_documents import TestEmbedding, register, upload, wait_document
from test_practice import create, items, submit, wait_practice

from capstone.core.settings import Settings
from capstone.db.models import Chapter, Document, Question, User
from capstone.main import create_app
from capstone.seed import seed_course_data
from capstone.services.documents import create_document, queue_delete
from capstone.services.storage import BlobStore


class ChapterGeneration:
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


def test_chapter_requirements_reach_wrong_questions_and_reports(migrated_database, tmp_path):
    generation = ChapterGeneration()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=generation)) as client:
        _, headers = register(client)
        topic = "队列|FIFO"
        exercise = create(
            client, headers, question_source="ai", generation_requirements=topic, count=1
        )
        wait_practice(client, exercise["id"])
        assert exercise["title"] == "栈与队列"
        item = items(client, exercise["id"])[0]
        assert item["chapter_id"] == exercise["chapter_id"]
        result = submit(client, headers, item, "false").json()
        assert result["source_info"]["basis"] == "general_knowledge"
        assert result["source_info"]["citations"] == []
        wrong = client.get("/api/v1/wrong-questions?search=队列").json()
        assert wrong["total"] == 1 and wrong["items"][0]["chapter_name"] == "栈与队列"
        assert client.get("/api/v1/wrong-questions?search=栈").json()["total"] == 0
        stats = client.get("/api/v1/learning/stats").json()
        assert stats["attempts"]["count"] == 1
        assert "topics" not in stats
        assert "unclassified" not in stats
        assert (
            next(ch for ch in stats["chapters"] if ch["name"] == "栈与队列")["attempts"]["count"]
            == 1
        )
        assert stats["question_types"]["true_false"]["count"] == 1
        assert client.get("/api/v1/learning/performance").status_code == 200
        assert len(generation.prompts) == 2
        report = client.post(
            "/api/v1/reports", headers=headers, json={"client_request_id": "topic-report"}
        ).json()
        exported = client.get(f"/api/v1/reports/{report['id']}/export").text
        assert "| 栈与队列 |" in exported
        assert "\n实际检索片段：[]" in generation.prompts[0][0]["content"]
        payload = json.loads(generation.prompts[0][1]["content"])
        assert payload["requirements"] == topic and payload["chapter"] == "栈与队列"
        assert "topic" not in payload


def test_chapter_is_required_and_invalid_requests_create_no_sessions(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        for topic in ("", "   ", "\n\t", "仅提供旧主题也必须选择章节"):
            response = client.post(
                "/api/v1/practice-sessions",
                headers=headers,
                json={
                    "client_request_id": "empty-topic",
                    "topic": topic,
                },
            )
            assert response.status_code == 422
        assert client.get("/api/v1/practice-sessions").json()["total"] == 0


def test_chapter_material_selection_is_private_and_current(migrated_database, tmp_path):
    course = seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    generation = ChapterGeneration(cited=True)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as client:
        library, headers = register(client)
        chapter_id = next(
            point["id"]
            for point in client.get("/api/v1/chapters").json()["items"]
            if point["code"] == "stack-queue"
        )
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
                    "chapter_id": chapter_id,
                    "document_ids": [private],
                },
            )
            assert denied.status_code == 404
            with Session(migrated_database) as session, session.begin():
                other_chapter = session.scalar(select(Chapter.id).where(Chapter.code == "tree"))
                session.get(Document, UUID(mine)).chapter_id = other_chapter
            mismatch = client.post(
                "/api/v1/practice-sessions",
                headers=headers,
                json={
                    "client_request_id": "mismatched",
                    "chapter_id": chapter_id,
                    "document_ids": [mine],
                },
            )
            assert (
                mismatch.status_code == 422
                and mismatch.json()["code"] == "MATERIAL_CHAPTER_MISMATCH"
            )
            assert (
                client.get(
                    f"/api/v1/knowledge-bases/{library}/documents",
                    params={"chapter_id": str(other_chapter)},
                ).json()["total"]
                == 1
            )
            assert (
                client.get(
                    f"/api/v1/knowledge-bases/{library}/documents",
                    params={"chapter_id": chapter_id},
                ).json()["total"]
                == 0
            )
            exercise = create(client, headers, question_source="ai", count=1, document_ids=[public])
            wait_practice(client, exercise["id"])
            assert exercise["title"] == "栈与队列"
            item = items(client, exercise["id"])[0]
            result = submit(client, headers, item, "false").json()
            assert result["source_info"]["basis"] == "selected_materials"
            assert {source["document_id"] for source in result["source_info"]["citations"]} == {
                public
            }
            assert "topics" not in client.get("/api/v1/learning/stats").json()
            assert client.delete("/api/v1/documents/" + mine, headers=headers).status_code == 202
            stale = client.post(
                "/api/v1/practice-sessions",
                headers=headers,
                json={
                    "client_request_id": "deleted",
                    "chapter_id": chapter_id,
                    "document_ids": [mine],
                },
            )
            assert stale.status_code == 409
        finally:
            other.close()


@pytest.mark.parametrize("reclassify", [False, True])
def test_material_changed_during_generation_is_not_published(
    migrated_database, tmp_path, reclassify
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    target = {}

    def remove():
        with Session(migrated_database) as session:
            if reclassify:
                document = session.get(Document, UUID(target["document"]))
                document.chapter_id = session.scalar(
                    select(Chapter.id).where(Chapter.code == "tree")
                )
                session.commit()
            else:
                queue_delete(session, UUID(target["document"]), target["user"])

    generation = ChapterGeneration(cited=True, before_review=remove)
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
        assert failed["error_code"] == (
            "MATERIAL_CHAPTER_MISMATCH" if reclassify else "PRACTICE_DOCUMENT_NOT_READY"
        )
        assert items(client, exercise["id"]) == []
        with Session(migrated_database) as session:
            assert session.scalar(select(func.count()).select_from(Question)) == 0
