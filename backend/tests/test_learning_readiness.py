from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_conversations import TestGeneration, new_conversation, send, wait_answer
from test_documents import TestEmbedding, register, upload, wait_document
from test_summaries import wait_summary

from capstone.core.settings import Settings
from capstone.db.models import Document
from capstone.main import create_app


def test_readiness_is_scoped_and_no_ready_materials_does_not_record_a_question(
    migrated_database, tmp_path
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=TestGeneration())
    ) as first:
        second = TestClient(first.app)
        try:
            own_library, headers = register(first)
            other_library, other_headers = register(second, "other")
            other_doc = upload(second, other_library, other_headers)["document"]["id"]
            wait_document(second, other_doc, "ready")
            identifier = new_conversation(first, headers, scope="personal")
            config = first.get("/api/v1/conversations/config?conversation_id=" + identifier).json()
            assert config["generation_available"] and config["embedding_available"]
            assert config["ready_document_count"] == config["personal_ready_count"] == 0
            blocked = send(first, headers, identifier)
            assert blocked.status_code == 409
            assert blocked.json()["code"] == "NO_READY_MATERIALS"
            assert first.get(f"/api/v1/conversations/{identifier}/messages").json()["total"] == 0
            assert first.get("/api/v1/learning/stats").json()["learning"]["asked_questions"] == 0
            assert (
                second.get("/api/v1/conversations/config?conversation_id=" + identifier).status_code
                == 404
            )
            own_doc = upload(first, own_library, headers)["document"]["id"]
            wait_document(first, own_doc, "ready")
            config = first.get("/api/v1/conversations/config?conversation_id=" + identifier).json()
            assert config["personal_ready_count"] == config["ready_document_count"] == 1
            assert config["course_ready_count"] == 0
            overview = first.get("/api/v1/learning/overview").json()
            assert overview["readiness"]["ready_document_count"] == 1
            # A different scope and an explicitly selected, no longer ready file must
            # not inherit readiness from the user's other documents.
            course = new_conversation(first, headers, scope="course")
            assert (
                first.get("/api/v1/conversations/config?conversation_id=" + course).json()[
                    "ready_document_count"
                ]
                == 0
            )
            selected = new_conversation(first, headers, document_ids=[own_doc])
            with Session(migrated_database) as session, session.begin():
                session.get(Document, UUID(own_doc)).status = "failed"
            assert (
                first.get("/api/v1/conversations/config?conversation_id=" + selected).json()[
                    "ready_document_count"
                ]
                == 0
            )
            assert send(first, headers, selected).status_code == 409
        finally:
            second.close()


def test_no_hit_is_separate_from_answers_summary_and_followup_context(
    migrated_database, tmp_path, monkeypatch
):
    import capstone.services.chat_runner as runner

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    generation = TestGeneration()
    retrieve = runner.retrieve
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as client:
        library, headers = register(client)
        doc_id = upload(client, library, headers)["document"]["id"]
        wait_document(client, doc_id, "ready")
        identifier = new_conversation(client, headers, scope="personal")
        monkeypatch.setattr(runner, "retrieve", lambda *args: [])
        queued = send(client, headers, identifier)
        assert queued.status_code == 202
        insufficient = wait_answer(client, identifier)
        assert insufficient["answer_outcome"] == "insufficient_materials"
        assert "没有找到足够依据" in insufficient["content"]
        stream = client.get(queued.json()["stream_url"])
        assert "event: completed" in stream.text and "insufficient_materials" in stream.text
        stats = client.get("/api/v1/learning/stats").json()
        assert stats["schema_version"] == 2
        assert stats["learning"]["completed_answers"] == 0
        assert stats["learning"]["insufficient_materials"] == 1
        summary_path = f"/api/v1/conversations/{identifier}/summary"
        empty = client.post(summary_path, headers=headers, json={"client_request_id": "empty"})
        assert empty.status_code == 409 and empty.json()["code"] == "SUMMARY_EMPTY"
        snapshot = client.post(
            "/api/v1/reports", headers=headers, json={"client_request_id": "no-hit-report"}
        ).json()
        monkeypatch.setattr(runner, "retrieve", retrieve)
        assert send(client, headers, identifier, "supported").status_code == 202
        answered = wait_answer(client, identifier)
        assert answered["answer_outcome"] == "answered" and answered["citations"]
        assert not any(
            message["content"] == insufficient["content"] for message in generation.prompts[-1]
        )
        stats = client.get("/api/v1/learning/stats").json()
        assert stats["learning"]["completed_answers"] == 1
        assert stats["learning"]["insufficient_materials"] == 1
        assert stats["learning"]["asked_questions"] == 2
        generated = client.post(summary_path, headers=headers, json={"client_request_id": "valid"})
        assert generated.status_code == 202
        assert wait_summary(client, identifier)["message_count"] == 2
        saved = client.get("/api/v1/reports/" + snapshot["id"]).json()["snapshot"]
        assert saved["learning"]["completed_answers"] == 0
        exported = client.get("/api/v1/reports/" + snapshot["id"] + "/export").text
        assert "有效答疑：0 次" in exported and "资料不足 1 次" in exported
