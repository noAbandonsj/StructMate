import time
from threading import Event

import pytest
from fastapi.testclient import TestClient
from test_conversations import TestGeneration, new_conversation, send, wait_answer
from test_documents import TestEmbedding, register, upload, wait_document
from test_summaries import wait_summary

from capstone.core.errors import ApiError
from capstone.core.settings import Settings
from capstone.main import create_app
from capstone.services.chat_retrieval import ChatRetrieval


def test_chat_without_documents_or_embedding_supports_followup_summary_and_report(
    migrated_database, tmp_path
):
    generation = TestGeneration()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=generation)) as client:
        _, headers = register(client)
        identifier = new_conversation(client, headers)
        assert client.get("/api/v1/conversations/config").json() == {"generation_available": True}
        assert client.get("/api/v1/learning/overview").json()["readiness"] == {
            "generation_available": True
        }
        first = send(client, headers, identifier)
        assert first.status_code == 202
        answer = wait_answer(client, identifier)
        assert answer["content"] and answer["citations"] == []
        assert "[资料" not in answer["content"] and "answer_outcome" not in answer
        assert send(client, headers, identifier).json() == first.json()
        assert send(client, headers, identifier, "followup", "请用例子解释").status_code == 202
        wait_answer(client, identifier)
        assert {"role": "assistant", "content": answer["content"]} in generation.prompts[-1]
        summary_path = f"/api/v1/conversations/{identifier}/summary"
        assert (
            client.post(
                summary_path, headers=headers, json={"client_request_id": "sum"}
            ).status_code
            == 202
        )
        assert wait_summary(client, identifier)["message_count"] == 4
        stats = client.get("/api/v1/learning/stats").json()
        assert stats["schema_version"] == 5
        assert stats["learning"]["completed_answers"] == 2
        assert "insufficient_materials" not in stats["learning"]
        report = client.post(
            "/api/v1/reports", headers=headers, json={"client_request_id": "report"}
        )
        assert report.status_code == 202
        assert report.json()["snapshot"]["learning"]["completed_answers"] == 2
        exported = client.get("/api/v1/reports/" + report.json()["id"] + "/export").text
        assert "有效答疑：2 次" in exported and "资料不足" not in exported


def test_empty_retrieval_still_generates_and_instructs_against_fabricated_file_claims(
    migrated_database, tmp_path, monkeypatch
):
    import capstone.services.chat_retrieval as retrieval

    monkeypatch.setattr(retrieval, "retrieve", lambda *args: [])
    generation = TestGeneration()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as client:
        _, headers = register(client)
        identifier = new_conversation(client, headers)
        assert (
            send(client, headers, identifier, content="总结我上传文件的第三章").status_code == 202
        )
        answer = wait_answer(client, identifier)
        assert answer["content"] and answer["citations"] == []
        instruction = generation.prompts[0][0]["content"]
        assert "无法确认该原文" in instruction and "不能假装读过" in instruction
        assert "通用知识" in instruction and "未经信任的数据" in instruction


@pytest.mark.parametrize(
    "code",
    ["EMBEDDING_TIMEOUT", "EMBEDDING_AUTH_FAILED", "INDEX_MISSING", "INDEX_REBUILD_REQUIRED"],
)
def test_known_retrieval_failures_fall_back_without_exposing_details(
    migrated_database, tmp_path, monkeypatch, caplog, code
):
    import capstone.services.chat_retrieval as retrieval

    def fail(*args):
        raise ApiError(503, code, "private-provider-details")

    monkeypatch.setattr(retrieval, "retrieve", fail)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=TestGeneration())
    ) as client:
        _, headers = register(client)
        identifier = new_conversation(client, headers)
        assert send(client, headers, identifier).status_code == 202
        answer = wait_answer(client, identifier)
        assert answer["citations"] == [] and answer["error_code"] is None
        assert code in caplog.text and "private-provider-details" not in caplog.text
        assert "private-provider-details" not in str(answer)


@pytest.mark.parametrize(
    "error", [RuntimeError("private-bug"), ApiError(403, "ACCESS_DENIED", "private-denial")]
)
def test_unexpected_or_permission_failure_is_not_swallowed(
    migrated_database, tmp_path, monkeypatch, error
):
    import capstone.services.chat_retrieval as retrieval

    def fail(*args):
        raise error

    monkeypatch.setattr(retrieval, "retrieve", fail)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    generation = TestGeneration()
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as client:
        _, headers = register(client)
        identifier = new_conversation(client, headers)
        assert send(client, headers, identifier).status_code == 202
        answer = wait_answer(client, identifier, "failed")
        assert generation.prompts == []
        assert answer["error_code"] in {"GENERATION_FAILED", "ACCESS_DENIED"}


def test_timeout_discards_late_results_and_bounds_outstanding_work(tmp_path, monkeypatch, caplog):
    import capstone.services.chat_retrieval as retrieval

    release = Event()
    calls = []

    def slow(*args):
        calls.append(True)
        release.wait(3)
        return [{"number": 1, "text": "late-result"}]

    monkeypatch.setattr(retrieval, "retrieve", slow)
    settings = Settings(_env_file=None, data_dir=tmp_path, chat_retrieval_timeout_seconds=0.05)
    service = ChatRetrieval(None, TestEmbedding(), None, settings)
    try:
        started = time.monotonic()
        for _ in range(5):
            assert service.search(None, "combined", [], "问题", Event()) == []
        assert time.monotonic() - started < 1
        assert len(calls) == 2
        assert "RETRIEVAL_TIMEOUT" in caplog.text and "RETRIEVAL_BUSY" in caplog.text
    finally:
        release.set()
        service.close()


def test_cancel_during_retrieval_does_not_start_generation(
    migrated_database, tmp_path, monkeypatch
):
    import capstone.services.chat_retrieval as retrieval

    started, release = Event(), Event()

    def slow(*args):
        started.set()
        release.wait(3)
        return []

    monkeypatch.setattr(retrieval, "retrieve", slow)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    generation = TestGeneration()
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as client:
        _, headers = register(client)
        identifier = new_conversation(client, headers)
        queued = send(client, headers, identifier).json()
        try:
            assert started.wait(2)
            assert (
                client.post(
                    f"/api/v1/messages/{queued['assistant_message_id']}/cancel", headers=headers
                ).status_code
                == 200
            )
            wait_answer(client, identifier, "cancelled")
        finally:
            release.set()
        assert generation.prompts == []


def test_other_users_documents_do_not_enter_optional_context(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    generation = TestGeneration()
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as first:
        second = TestClient(first.app)
        try:
            _, headers = register(first)
            library, other_headers = register(second, "other")
            document = upload(
                second, library, other_headers, data="秘密文档不得进入其他账号回答".encode()
            )["document"]["id"]
            wait_document(second, document, "ready")
            identifier = new_conversation(first, headers)
            assert send(first, headers, identifier).status_code == 202
            assert wait_answer(first, identifier)["citations"] == []
            assert "秘密文档" not in str(generation.prompts)
        finally:
            second.close()
