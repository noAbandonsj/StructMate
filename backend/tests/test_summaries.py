import time
from copy import deepcopy
from threading import Event
from uuid import UUID

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_documents import ORIGIN, register

from capstone.core.settings import Settings
from capstone.db.models import Conversation, Message
from capstone.db.session import write_transaction
from capstone.main import create_app


class TestSummaryGeneration:
    __test__ = False
    available = True

    def __init__(self):
        self.prompts = []
        self.fail = False

    def stream(self, messages, cancelled):
        self.prompts.append(messages)
        if self.fail:
            raise RuntimeError("private-model-test-key")
        yield "## 本次讨论\n\n讨论了栈的操作规则，仍需用新题独立验证理解。\n"


def create_conversation(client, headers):
    response = client.post("/api/v1/conversations", headers=headers, json={"title": "栈的学习"})
    assert response.status_code == 201
    return response.json()["id"]


def add_pair(
    engine, identifier, question="栈如何工作？", answer="只在栈顶入栈和出栈。", failed=False
):
    with Session(engine) as session, write_transaction(session):
        last = (
            session.scalar(
                select(func.max(Message.sequence)).where(
                    Message.conversation_id == UUID(identifier)
                )
            )
            or 0
        )
        user = Message(
            conversation_id=UUID(identifier), sequence=last + 1, role="user", content=question
        )
        session.add(user)
        session.flush()
        session.add(
            Message(
                conversation_id=UUID(identifier),
                sequence=last + 2,
                role="assistant",
                reply_to_message_id=user.id,
                content=answer,
                status="failed" if failed else "completed",
            )
        )


def generate(client, headers, identifier, key="summary-1"):
    return client.post(
        f"/api/v1/conversations/{identifier}/summary",
        headers=headers,
        json={"client_request_id": key},
    )


def wait_summary(client, identifier, status="completed"):
    deadline = time.monotonic() + 6
    while True:
        result = client.get(f"/api/v1/conversations/{identifier}/summary").json()
        if result["status"] == status:
            return result
        assert time.monotonic() < deadline, result
        time.sleep(0.02)


def test_unconfigured_summary_permissions_and_no_fake_output(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as first:
        other = TestClient(first.app)
        try:
            _, headers = register(first)
            _, other_headers = register(other, "other")
            identifier = create_conversation(first, headers)
            path = f"/api/v1/conversations/{identifier}/summary"
            assert first.get(path).json()["status"] == "empty"
            assert generate(first, headers, identifier).status_code == 503
            assert first.get(path + "/export").status_code == 409
            assert first.get(path).json()["content"] == ""
            assert other.get(path).status_code == 404
            assert other.get(path + "/export").status_code == 404
            assert generate(other, other_headers, identifier).status_code == 404
            assert generate(first, ORIGIN, identifier).status_code == 403
        finally:
            other.close()


def test_summary_fixed_scope_idempotency_and_markdown_export(migrated_database, tmp_path):
    class SlowSummary(TestSummaryGeneration):
        def __init__(self):
            super().__init__()
            self.started, self.release = Event(), Event()

        def stream(self, messages, cancelled):
            self.started.set()
            while not self.release.wait(0.02):
                if cancelled.is_set():
                    return
            yield from super().stream(messages, cancelled)

    model = SlowSummary()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=model)) as client:
        _, headers = register(client)
        identifier = create_conversation(client, headers)
        assert generate(client, headers, identifier).status_code == 409
        add_pair(migrated_database, identifier)
        add_pair(migrated_database, identifier, "未成功的问题", "未完成的回答", failed=True)
        assert generate(client, headers, identifier).status_code == 202
        assert model.started.wait(2)
        try:
            assert generate(client, headers, identifier).status_code == 202
            assert generate(client, headers, identifier, "another").status_code == 409
            add_pair(migrated_database, identifier, "后来新增的追问", "这轮不应进入本次总结")
        finally:
            model.release.set()
        result = wait_summary(client, identifier)
        assert result["message_count"] == 2 and result["cutoff_sequence"] == 2
        assert result["has_newer_messages"] and result["cutoff_at"]
        assert "snapshot" not in result and "used_request_ids" not in result
        assert len(model.prompts) == 1
        assert "未成功的问题" not in model.prompts[0][-1]["content"]
        assert "后来新增的追问" not in model.prompts[0][-1]["content"]
        assert generate(client, headers, identifier).json()["cutoff_sequence"] == 2
        assert len(model.prompts) == 1
        exported = client.get(f"/api/v1/conversations/{identifier}/summary/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("text/markdown")
        assert "attachment" in exported.headers["content-disposition"]
        assert "讨论不代表掌握" in exported.text and "截止消息序号 2" in exported.text


def test_summary_failure_keeps_previous_content_and_restart_does_not_replay(
    migrated_database, tmp_path
):
    model = TestSummaryGeneration()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=model)) as client:
        _, headers = register(client)
        identifier = create_conversation(client, headers)
        add_pair(migrated_database, identifier)
        assert generate(client, headers, identifier).status_code == 202
        first = wait_summary(client, identifier)
        add_pair(migrated_database, identifier, "新增问题", "新增回答")
        model.fail = True
        assert generate(client, headers, identifier, "second").status_code == 202
        failed = wait_summary(client, identifier, "failed")
        assert failed["content"] == first["content"] and failed["cutoff_sequence"] == 2
        assert "private-model-test-key" not in str(failed)
        assert client.get(f"/api/v1/conversations/{identifier}/summary/export").status_code == 200
        assert generate(client, headers, identifier).status_code == 409
        with Session(migrated_database) as session, write_transaction(session):
            conversation = session.get(Conversation, UUID(identifier))
            data = deepcopy(conversation.summary_data)
            data["status"] = "generating"
            conversation.summary_data = data
    fresh = TestSummaryGeneration()
    with TestClient(create_app(settings, generation_service=fresh)) as client:
        assert (
            client.post(
                "/api/v1/auth/login",
                headers=ORIGIN,
                json={"username": "student", "password": "test-password"},
            ).status_code
            == 200
        )
        result = wait_summary(client, identifier, "failed")
        assert result["error_code"] == "SUMMARY_INTERRUPTED"
        assert result["content"] == first["content"] and fresh.prompts == []


def test_long_summary_covers_tail_and_cleanup_resets_history(
    migrated_database, migration_config, tmp_path
):
    model = TestSummaryGeneration()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=model)) as client:
        _, headers = register(client)
        identifier = create_conversation(client, headers)
        add_pair(
            migrated_database, identifier, answer="数据结构知识。" * 5000 + "末尾知识点必须保留。"
        )
        assert generate(client, headers, identifier).status_code == 202
        result = wait_summary(client, identifier)
        assert result["message_count"] == 2
        assert len(model.prompts) > 1
        assert any("末尾知识点必须保留" in prompt[-1]["content"] for prompt in model.prompts)
    command.downgrade(migration_config, "0004")
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0
    command.upgrade(migration_config, "head")
    command.check(migration_config)
