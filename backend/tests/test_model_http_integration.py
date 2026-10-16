import asyncio
import json
import socket
import time
from threading import Event, Thread

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse
from test_conversations import new_conversation, send, wait_answer
from test_documents import register, upload, wait_document
from test_model_http import frame
from test_practice import create, items, submit, wait_practice
from test_reports import report, wait_report
from test_summaries import generate, wait_summary

from capstone.core.errors import ApiError
from capstone.core.model_config import ModelConnection
from capstone.core.model_http import DeepSeekGeneration
from capstone.core.settings import Settings
from capstone.db.models import KnowledgePoint
from capstone.main import create_app


@pytest.fixture
def local_provider():
    """An explicit local HTTP stub, never an external model or a real-model acceptance result."""
    app = FastAPI()
    release = Event()
    release.set()
    state = {"generation": 0, "embedding": 0, "release": release, "point": None}

    @app.post("/compatible-mode/v1/embeddings")
    async def embeddings(request: Request):
        assert request.headers["authorization"] == "Bearer integration-test-key"
        payload = await request.json()
        state["embedding"] += 1
        assert len(payload["input"]) <= 10 and payload["dimensions"] == 3
        return {
            "data": [
                {"index": index, "embedding": [1.0, (len(text) % 7) / 7, 0.2]}
                for index, text in reversed(list(enumerate(payload["input"])))
            ]
        }

    @app.post("/chat/completions")
    async def completion(request: Request):
        assert request.headers["authorization"] == "Bearer integration-test-key"
        payload = await request.json()
        state["generation"] += 1
        assert payload["thinking"] == {"type": "disabled"} and payload["stream"] is True
        if "出题助手" in payload["messages"][0]["content"]:
            text = json.dumps(
                {
                    "items": [
                        {
                            "type": "true_false",
                            "stem": "栈只在栈顶入栈和出栈。",
                            "options": [
                                {"key": "true", "text": "正确"},
                                {"key": "false", "text": "错误"},
                            ],
                            "answer": "true",
                            "explanation": "后进先出。",
                            "hint": "考虑操作端。",
                            "knowledge_point_id": state["point"],
                            "difficulty": "basic",
                            "citation_numbers": [1],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        else:
            text = "协议测试的正文，保留原文引用 [资料1]。"

        async def stream():
            yield frame(text[:4])
            while not release.is_set():
                await asyncio.sleep(0.01)
            payload = frame(text[4:]) + frame(reason="stop") + b"data: [DONE]\n\n"
            # Split UTF-8 code points and SSE frames across real HTTP body chunks.
            for start in range(0, len(payload), 7):
                yield payload[start : start + 7]

        return StreamingResponse(stream(), media_type="text/event-stream")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        origin = "http://127.0.0.1:" + str(listener.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 8
        try:
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(0.02)
            yield origin, state
        finally:
            release.set()
            server.should_exit = True
            thread.join(8)
            assert not thread.is_alive()


def test_production_http_adapters_drive_documents_chat_ai_summary_report(
    bank_database, tmp_path, local_provider
):
    origin, state = local_provider
    with Session(bank_database) as session:
        point = str(
            session.scalar(
                select(KnowledgePoint.id).where(KnowledgePoint.code == "stack-queue.stack")
            )
        )
    state["point"] = point
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        environment="test",
        generation_base_url=origin,
        generation_model="http-stub-text",
        generation_api_key="integration-test-key",
        embedding_base_url=origin + "/compatible-mode/v1",
        embedding_model="http-stub-vector",
        embedding_api_key="integration-test-key",
        embedding_dimension=3,
    )
    # No model-port injection: exercise the same configured HTTP classes used in production.
    with TestClient(create_app(settings)) as client:
        library, headers = register(client)
        document = upload(client, library, headers)["document"]["id"]
        wait_document(client, document, "ready")
        conversation = new_conversation(client, headers, scope="personal", knowledge_point_id=point)
        assert send(client, headers, conversation).status_code == 202
        answer = wait_answer(client, conversation)
        assert answer["citations"][0]["document_id"] == document
        assert "协议测试的正文" in answer["content"] and "[资料1]" in answer["content"]
        practice = create(
            client,
            headers,
            question_source="ai",
            count=1,
            knowledge_point_ids=[point],
            source_conversation_id=conversation,
        )
        wait_practice(client, practice["id"])
        question = items(client, practice["id"])[0]
        result = submit(client, headers, question, "false")
        assert result.status_code == 201 and result.json()["wrong_question_id"]
        assert client.get("/api/v1/wrong-questions").json()["total"] == 1
        assert generate(client, headers, conversation).status_code == 202
        assert wait_summary(client, conversation)["content"]
        saved = report(client, headers).json()
        finished = wait_report(client, saved["id"])
        assert finished["snapshot"]["attempts"]["count"] == 1 and finished["content"]
        assert state["generation"] == 5 and state["embedding"] >= 3


def test_cancellation_interrupts_a_stalled_http_stream(local_provider):
    origin, state = local_provider
    state["release"].clear()
    connection = ModelConnection(
        base_url=origin, model="http-stub-text", api_key="integration-test-key", timeout_seconds=5
    )
    cancelled, first, done = Event(), Event(), Event()
    received = []

    def consume():
        try:
            for delta in DeepSeekGeneration(connection).stream(
                [{"role": "user", "content": "问题"}], cancelled
            ):
                received.append(delta)
                first.set()
        finally:
            done.set()

    consumer = Thread(target=consume, daemon=True)
    consumer.start()
    try:
        assert first.wait(3)
        cancelled.set()
        interrupted = done.wait(1.5)
    finally:
        state["release"].set()
        consumer.join(5)
    assert interrupted, (
        "cancellation must interrupt a blocked read rather than wait for more tokens"
    )
    assert len(received) == 1


def test_timeout_rejects_a_stalled_stream_instead_of_completing_partial_text(local_provider):
    origin, state = local_provider
    state["release"].clear()
    connection = ModelConnection(
        base_url=origin, model="http-stub-text", api_key="integration-test-key", timeout_seconds=0.3
    )
    try:
        with pytest.raises(ApiError) as error:
            list(
                DeepSeekGeneration(connection).stream(
                    [{"role": "user", "content": "问题"}], Event()
                )
            )
        assert error.value.detail["code"] == "GENERATION_TIMEOUT"
    finally:
        state["release"].set()
