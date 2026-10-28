import time
from threading import Event
from uuid import UUID, uuid4

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_documents import ORIGIN, TestEmbedding, register, upload, wait_document

from capstone.core.settings import REPOSITORY_ROOT, Settings
from capstone.db.models import Conversation, Message
from capstone.db.session import write_transaction
from capstone.import_course import import_course_data
from capstone.main import create_app
from capstone.seed import seed_course_data


class TestGeneration:
    __test__ = False
    available = True

    def __init__(self):
        self.prompts = []

    def stream(self, messages, cancelled):
        self.prompts.append(messages)
        yield "按资料，栈后进先出 [资料1]。"
        yield "不存在的编号 [资料999] 应被移除，数组 a[0] 保留。"


COURSE_PACKET = REPOSITORY_ROOT / "backend/tests/fixtures/course"


def new_conversation(client, headers, **values):
    response = client.post("/api/v1/conversations", headers=headers, json=values)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(client, headers, identifier, request_id="question-1", content="栈有什么特点？", **values):
    return client.post(
        f"/api/v1/conversations/{identifier}/messages",
        headers=headers,
        json={"content": content, "client_request_id": request_id, **values},
    )


def wait_answer(client, conversation_id, status="completed"):
    deadline = time.monotonic() + 6
    while True:
        result = client.get(f"/api/v1/conversations/{conversation_id}/messages").json()["items"]
        if result and result[-1]["status"] == status:
            return result[-1]
        assert time.monotonic() < deadline, result
        time.sleep(0.03)


def test_conversation_permissions_archive_and_unconfigured_models(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as first:
        second = TestClient(first.app)
        try:
            _, headers = register(first)
            _, other_headers = register(second, "other")
            identifier = new_conversation(first, headers)
            assert first.get("/api/v1/conversations").json()["total"] == 1
            assert second.get("/api/v1/conversations").json()["total"] == 0
            path = f"/api/v1/conversations/{identifier}"
            for response in (
                second.get(path),
                second.get(path + "/messages"),
                second.patch(path, headers=other_headers, json={"title": "他人"}),
                send(second, other_headers, identifier),
            ):
                assert response.status_code == 404
            assert send(first, headers, identifier).status_code == 503
            assert first.get(path + "/messages").json()["total"] == 0
            initial = first.get(path).json()
            assert initial["scope"] == "combined"
            for retired in ({"scope": "personal"}, {"document_ids": []}, {"chapter_id": None}):
                assert first.patch(path, headers=headers, json=retired).status_code == 422
            assert first.get(path).json() == initial
            for field in ("title", "archived"):
                assert first.patch(path, headers=headers, json={field: None}).status_code == 422
            assert first.patch(path, headers=headers, json={"title": " "}).status_code == 422
            renamed = first.patch(path, headers=headers, json={"title": "  新名称  "})
            assert renamed.status_code == 200 and renamed.json()["title"] == "新名称"
            assert first.patch(path, headers=headers, json={"archived": True}).status_code == 200
            assert first.get("/api/v1/conversations").json()["total"] == 0
            assert first.get("/api/v1/conversations?archived=true").json()["total"] == 1
            assert send(first, headers, identifier).status_code == 409
            assert first.patch(path, headers=headers, json={"archived": False}).status_code == 200
            assert first.get("/api/v1/conversations").json()["total"] == 1
            assert first.post("/api/v1/conversations", headers=ORIGIN, json={}).status_code == 403
        finally:
            second.close()


def test_real_retrieval_stream_history_and_deleted_citation(migrated_database, tmp_path):
    seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    import_course_data(migrated_database, settings, COURSE_PACKET)
    generation = TestGeneration()
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as first:
        second = TestClient(first.app)
        try:
            library, headers = register(first)
            other_library, other_headers = register(second, "other")
            own = upload(first, library, headers)["document"]["id"]
            hidden = upload(
                second, other_library, other_headers, data="秘密：不应进入他人上下文。".encode()
            )["document"]["id"]
            wait_document(first, own, "ready")
            wait_document(second, hidden, "ready")
            identifier = new_conversation(first, headers, scope="personal")
            response = send(first, headers, identifier)
            assert response.status_code == 202
            answer = wait_answer(first, identifier)
            assert answer["citations"]
            assert {item["document_id"] for item in answer["citations"]} == {own}
            assert "[资料999]" not in answer["content"]
            assert "[资料1]" in answer["content"] and "a[0]" in answer["content"]
            assert "秘密" not in str(generation.prompts)
            assert "栈是后进先出" in generation.prompts[0][0]["content"]
            stream_url = response.json()["stream_url"]
            stream = first.get(stream_url)
            assert stream.status_code == 200 and "event: snapshot" in stream.text
            assert "event: completed" in stream.text
            assert second.get(stream_url).status_code == 404
            assert (
                second.post(
                    f"/api/v1/messages/{answer['id']}/cancel", headers=other_headers
                ).status_code
                == 404
            )
            assert send(first, headers, identifier).json() == response.json()
            assert send(first, headers, identifier, content="不同内容").status_code == 409
            response = send(first, headers, identifier, "question-2", "请用小例子解释。")
            assert response.status_code == 202
            wait_answer(first, identifier)
            assert any(item["role"] == "assistant" for item in generation.prompts[-1])
            assert generation.prompts[-1][-1]["content"] == "请用小例子解释。"
            assert first.delete(f"/api/v1/documents/{own}", headers=headers).status_code == 202
            history = first.get(f"/api/v1/conversations/{identifier}/messages").json()
            assert history["total"] == 4
            assert all(item["source_deleted"] for item in history["items"][1]["citations"])
            assert send(first, headers, identifier, "after-delete").status_code == 202
            continued = wait_answer(first, identifier)
            assert continued["citations"] == []
            assert "[资料" not in continued["content"]
            assert first.get(f"/api/v1/conversations/{identifier}/messages").json()["total"] == 6
            assert len(generation.prompts) == 3
        finally:
            second.close()


def test_scope_filters_course_explicit_docs_and_stale_revision(migrated_database, tmp_path):
    seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    import_course_data(migrated_database, settings, COURSE_PACKET)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=TestGeneration())
    ) as client:
        library, headers = register(client)
        document_id = upload(client, library, headers)["document"]["id"]
        wait_document(client, document_id, "ready")
        identifier = new_conversation(client, headers, scope="course")
        assert send(client, headers, identifier).status_code == 202
        assert all(
            item["document_id"] != document_id
            for item in wait_answer(client, identifier)["citations"]
        )
        assert (
            client.post(
                "/api/v1/conversations",
                headers=headers,
                json={"scope": "course", "document_ids": [document_id]},
            ).status_code
            == 404
        )
        selected = new_conversation(client, headers, document_ids=[document_id])
        assert send(client, headers, selected).status_code == 202
        assert {item["document_id"] for item in wait_answer(client, selected)["citations"]} == {
            document_id
        }
        # Orphaned old vectors remain physically present but must not satisfy current revision.
        from capstone.db.models import Document

        with Session(migrated_database) as session, write_transaction(session):
            document = session.get(Document, UUID(document_id))
            document.index_revision += 1
        assert send(client, headers, selected, "stale").status_code == 202
        assert wait_answer(client, selected)["citations"] == []


def test_cancel_concurrent_send_and_retry_are_idempotent(migrated_database, tmp_path):
    class SlowGeneration(TestGeneration):
        def __init__(self):
            super().__init__()
            self.started = Event()

        def stream(self, messages, cancelled):
            self.prompts.append(messages)
            self.started.set()
            while not cancelled.wait(0.03):
                yield "讲解中。"
                time.sleep(0.15)

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    generation = SlowGeneration()
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as client:
        library, headers = register(client)
        doc_id = upload(client, library, headers)["document"]["id"]
        wait_document(client, doc_id, "ready")
        identifier = new_conversation(client, headers)
        original = send(client, headers, identifier)
        assert original.status_code == 202 and generation.started.wait(3)
        assert send(client, headers, identifier).json() == original.json()
        assert send(client, headers, identifier, "another").status_code == 409
        answer_id = original.json()["assistant_message_id"]
        cancel_url = f"/api/v1/messages/{answer_id}/cancel"
        assert client.post(cancel_url, headers=headers).json()["status"] == "cancelled"
        assert client.post(cancel_url, headers=headers).json()["status"] == "cancelled"
        retry_url = f"/api/v1/messages/{answer_id}/retry"
        retry = client.post(retry_url, headers=headers, json={"client_request_id": "retry"})
        assert retry.status_code == 202
        assert (
            client.post(retry_url, headers=headers, json={"client_request_id": "retry"}).json()
            == retry.json()
        )
        assert retry.json()["user_message_id"] == original.json()["user_message_id"]
        assert (
            client.post(
                f"/api/v1/messages/{retry.json()['assistant_message_id']}/cancel", headers=headers
            ).status_code
            == 200
        )
        assert send(client, headers, identifier, "later").status_code == 202
        latest = client.get(f"/api/v1/conversations/{identifier}/messages").json()["items"][-1]
        assert (
            client.post(f"/api/v1/messages/{latest['id']}/cancel", headers=headers).status_code
            == 200
        )
        assert (
            client.post(
                retry_url, headers=headers, json={"client_request_id": "too-late"}
            ).status_code
            == 409
        )
        with Session(migrated_database) as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(Message).where(Message.role == "user")
                )
                == 2
            )


def test_generation_failure_is_private_and_restart_does_not_replay(migrated_database, tmp_path):
    class FailedGeneration(TestGeneration):
        def stream(self, messages, cancelled):
            raise RuntimeError("private-test-key")
            yield ""

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(
        create_app(
            settings, embedding_service=TestEmbedding(), generation_service=FailedGeneration()
        )
    ) as client:
        library, headers = register(client)
        document = upload(client, library, headers)["document"]["id"]
        wait_document(client, document, "ready")
        identifier = new_conversation(client, headers)
        assert send(client, headers, identifier).status_code == 202
        answer = wait_answer(client, identifier, "failed")
        assert answer["error_code"] == "GENERATION_FAILED"
        assert "private-test-key" not in str(answer)
        with Session(migrated_database) as session, write_transaction(session):
            record = session.get(Message, UUID(answer["id"]))
            record.status = "generating"
    generation = TestGeneration()
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=generation)
    ) as client:
        # Restore a real user's Cookie via login; startup only marks interrupted state.
        response = client.post(
            "/api/v1/auth/login",
            headers=ORIGIN,
            json={"username": "student", "password": "test-password"},
        )
        assert response.status_code == 200
        assert wait_answer(client, identifier, "failed")["error_code"] == "GENERATION_INTERRUPTED"
        assert generation.prompts == []
        assert client.get(f"/api/v1/conversations/{identifier}").status_code == 200


def test_populated_conversations_can_be_downgraded(migrated_database, migration_config, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=TestGeneration())
    ) as client:
        library, headers = register(client)
        document = upload(client, library, headers)["document"]["id"]
        wait_document(client, document, "ready")
        identifier = new_conversation(client, headers)
        assert send(client, headers, identifier).status_code == 202
        wait_answer(client, identifier)
    command.downgrade(migration_config, "0002")
    command.upgrade(migration_config, "head")
    command.check(migration_config)
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0


def test_live_sse_emits_deltas_and_revokes_logged_out_stream(migrated_database, tmp_path):
    import socket
    from threading import Thread

    import httpx2
    import uvicorn

    class LiveGeneration(TestGeneration):
        def stream(self, messages, cancelled):
            while not cancelled.wait(0.05):
                yield "逐步讲解。"

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    app = create_app(
        settings, embedding_service=TestEmbedding(), generation_service=LiveGeneration()
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(0.02)
            with httpx2.Client(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
                library, headers = register(client)
                document = upload(client, library, headers)["document"]["id"]
                wait_document(client, document, "ready")
                identifier = new_conversation(client, headers)
                queued = send(client, headers, identifier).json()
                with client.stream("GET", queued["stream_url"]) as response:
                    assert response.status_code == 200
                    delta_seen = False
                    deadline = time.monotonic() + 5
                    for line in response.iter_lines():
                        assert time.monotonic() < deadline
                        if line == "event: delta":
                            delta_seen = True
                            assert (
                                client.post(
                                    f"/api/v1/messages/{queued['assistant_message_id']}/cancel",
                                    headers=headers,
                                ).status_code
                                == 200
                            )
                        if line == "event: cancelled":
                            break
                    assert delta_seen
                queued = send(client, headers, identifier, "logout-question").json()
                with client.stream("GET", queued["stream_url"]) as response:
                    deadline = time.monotonic() + 5
                    logged_out, revoked = False, False
                    for line in response.iter_lines():
                        assert time.monotonic() < deadline
                        if line == "event: snapshot" and not logged_out:
                            assert (
                                client.post("/api/v1/auth/logout", headers=headers).status_code
                                == 204
                            )
                            logged_out = True
                        if "LOGIN_REQUIRED" in line:
                            revoked = True
                            break
                    assert logged_out and revoked
        finally:
            server.should_exit = True
            thread.join(8)
            assert not thread.is_alive()


def test_context_keeps_six_completed_pairs_and_excludes_failed_cancelled_questions(
    migrated_database, tmp_path
):
    class RecordedEmbedding(TestEmbedding):
        def __init__(self):
            self.queries = []

        def embed(self, texts):
            self.queries.extend(texts)
            return super().embed(texts)

    embedding, generation = RecordedEmbedding(), TestGeneration()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(
        create_app(settings, embedding_service=embedding, generation_service=generation)
    ) as client:
        library, headers = register(client)
        document = upload(client, library, headers)["document"]["id"]
        wait_document(client, document, "ready")
        identifier = new_conversation(client, headers)
        with Session(migrated_database) as session, write_transaction(session):
            sequence = 0
            for index, status in enumerate(["completed"] * 7 + ["failed", "cancelled"]):
                sequence += 1
                text = f"已完成提问{index}" if status == "completed" else status + "_question"
                question = Message(
                    id=uuid4(),
                    conversation_id=UUID(identifier),
                    sequence=sequence,
                    role="user",
                    content=text,
                )
                session.add(question)
                session.flush()
                sequence += 1
                session.add(
                    Message(
                        conversation_id=UUID(identifier),
                        sequence=sequence,
                        role="assistant",
                        content=f"已完成回答{index}",
                        status=status,
                        reply_to_message_id=question.id,
                    )
                )
        embedding.queries.clear()
        assert send(client, headers, identifier, content="新问题").status_code == 202
        wait_answer(client, identifier)
        history = generation.prompts[-1][1:-1]
        expected = [
            item
            for index in range(1, 7)
            for item in (
                {"role": "user", "content": f"已完成提问{index}"},
                {"role": "assistant", "content": f"已完成回答{index}"},
            )
        ]
        assert history == expected
        assert "failed_question" not in str(generation.prompts)
        assert "cancelled_question" not in str(generation.prompts)
        assert embedding.queries[-1] == "已完成提问6\n新问题"
