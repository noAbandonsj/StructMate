import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_documents import ORIGIN, TestEmbedding, register, upload, wait_document

from capstone.core.settings import Settings
from capstone.db.models import (
    Attempt,
    KnowledgePoint,
    Message,
    PracticeItem,
    Question,
    WrongQuestion,
)
from capstone.main import create_app
from capstone.manage_questions import invalidate
from capstone.services import practice as practice_service


def create(client, headers, key="practice-1", **settings):
    response = client.post(
        "/api/v1/practice-sessions", headers=headers, json={"client_request_id": key, **settings}
    )
    assert response.status_code == 202, response.text
    return response.json()


def items(client, identifier):
    response = client.get(f"/api/v1/practice-sessions/{identifier}/items")
    assert response.status_code == 200
    return response.json()["items"]


def answer_for(engine, item, correct=True):
    with Session(engine) as session:
        snapshot = session.get(PracticeItem, UUID(item["id"])).snapshot
        return (
            snapshot["answer"]
            if correct
            else next(
                option["key"]
                for option in snapshot["options"]
                if option["key"] != snapshot["answer"]
            )
        )


def submit(client, headers, item, answer, key="answer-1"):
    return client.post(
        f"/api/v1/practice-items/{item['id']}/attempts",
        headers=headers,
        json={"client_request_id": key, "answer": answer},
    )


def wait_practice(client, identifier, expected="ready"):
    deadline = time.monotonic() + 5
    while True:
        result = client.get(f"/api/v1/practice-sessions/{identifier}").json()
        if result["status"] == expected:
            return result
        assert time.monotonic() < deadline, result
        time.sleep(0.03)


def test_bank_snapshot_hidden_answers_scoring_and_idempotency(bank_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        practice = create(client, headers)
        assert practice["status"] == "ready" and practice["actual_count"] == 5
        assert create(client, headers)["id"] == practice["id"]
        assert (
            client.post(
                "/api/v1/practice-sessions",
                headers=headers,
                json={"client_request_id": "practice-1", "count": 2},
            ).status_code
            == 409
        )
        questions = items(client, practice["id"])
        for item in questions:
            assert item["attempt"] is None
            assert "answer" not in item and "explanation" not in item and "source_info" not in item
            assert "snapshot" not in item and item["hint"] is None
        item = questions[0]
        answer = answer_for(bank_database, item, False)
        result = submit(client, headers, item, answer)
        assert result.status_code == 201 and result.json()["is_correct"] is False
        assert result.json()["wrong_question_id"]
        assert result.json()["source_info"]["verification"]["checked_on"]
        assert submit(client, headers, item, answer).json()["id"] == result.json()["id"]
        assert (
            submit(client, headers, item, answer, "another-key").json()["id"] == result.json()["id"]
        )
        assert submit(client, headers, item, answer_for(bank_database, item)).status_code == 409
        for item in questions[1:]:
            assert (
                submit(
                    client, headers, item, answer_for(bank_database, item), item["id"]
                ).status_code
                == 201
            )
        completed = client.get(f"/api/v1/practice-sessions/{practice['id']}").json()
        assert completed["status"] == "completed" and completed["correct_count"] == 4
        assert completed["submitted_count"] == 5
        assert all(item["attempt"] is not None for item in items(client, practice["id"]))
        with Session(bank_database) as session:
            assert session.scalar(select(func.count()).select_from(Attempt)) == 5
            assert session.scalar(select(func.count()).select_from(WrongQuestion)) == 1


def test_personal_practice_wrong_questions_and_origin_are_isolated(bank_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as first:
        second = TestClient(first.app)
        try:
            _, headers = register(first, "first")
            _, other = register(second, "second")
            practice = create(first, headers, count=1)
            item = items(first, practice["id"])[0]
            wrong = submit(first, headers, item, answer_for(bank_database, item, False)).json()[
                "wrong_question_id"
            ]
            for response in (
                second.get(f"/api/v1/practice-sessions/{practice['id']}"),
                second.get(f"/api/v1/practice-sessions/{practice['id']}/items"),
                submit(second, other, item, item["options"][0]["key"]),
                second.post(f"/api/v1/practice-items/{item['id']}/hint", headers=other),
                second.post(
                    f"/api/v1/practice-items/{item['id']}/feedback",
                    headers=other,
                    json={"reason": "这道题似乎有错误"},
                ),
                second.get(f"/api/v1/wrong-questions/{wrong}"),
                second.post(
                    "/api/v1/wrong-questions/review-sessions",
                    headers=other,
                    json={"client_request_id": "review", "wrong_question_ids": [wrong]},
                ),
            ):
                assert response.status_code == 404
            assert second.get("/api/v1/practice-sessions").json()["total"] == 0
            assert second.get("/api/v1/wrong-questions").json()["total"] == 0
            assert (
                first.post(
                    "/api/v1/practice-sessions",
                    headers=ORIGIN,
                    json={"client_request_id": "missing-csrf"},
                ).status_code
                == 403
            )
        finally:
            second.close()


def test_hint_repeat_and_review_categories_do_not_inflate_independent_sample(
    bank_database, tmp_path
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with Session(bank_database) as session:
        point = str(
            session.scalar(
                select(KnowledgePoint.id).where(KnowledgePoint.code == "linear-list.definition")
            )
        )
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        practice = create(client, headers, count=5, knowledge_point_ids=[point])
        assert practice["actual_count"] == 1 and "实际 1 道" in practice["notice"]
        item = items(client, practice["id"])[0]
        hint_url = f"/api/v1/practice-items/{item['id']}/hint"
        assert client.post(hint_url, headers=headers).json()["hinted"]
        assert client.post(hint_url, headers=headers).status_code == 200
        result = submit(client, headers, item, answer_for(bank_database, item, False)).json()
        assert result["category"] == "first_hinted" and result["hinted"]
        practice = create(client, headers, "repeat", count=1, knowledge_point_ids=[point])
        item = items(client, practice["id"])[0]
        assert (
            submit(client, headers, item, answer_for(bank_database, item)).json()["category"]
            == "repeat"
        )
        analysis = client.get("/api/v1/learning/performance").json()
        assert all(
            value["sample_count"] == 0
            and value["accuracy"] is None
            and value["status"] == "insufficient"
            for value in analysis["items"]
        )


def test_wrong_review_distinct_shanghai_dates_and_reset(bank_database, tmp_path, monkeypatch):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    clock = [datetime(2026, 10, 14, 15, 58, tzinfo=UTC)]
    monkeypatch.setattr(practice_service, "utc_now", lambda: clock[0])
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        original = create(client, headers, count=1)
        item = items(client, original["id"])[0]
        first = submit(client, headers, item, answer_for(bank_database, item, False)).json()
        wrong_id = first["wrong_question_id"]
        dates = [
            datetime(2026, 10, 14, 15, 59, tzinfo=UTC),
            datetime(2026, 10, 14, 15, 59, 30, tzinfo=UTC),
            datetime(2026, 10, 14, 16, 1, tzinfo=UTC),
            datetime(2026, 10, 14, 16, 2, tzinfo=UTC),
        ]
        for index, now in enumerate(dates):
            clock[0] = now
            review = client.post(
                "/api/v1/wrong-questions/review-sessions",
                headers=headers,
                json={
                    "client_request_id": "review-" + str(index),
                    "wrong_question_ids": [wrong_id],
                },
            )
            assert review.status_code == 202
            practice = review.json()
            assert practice["mode"] == "review" and practice["question_source"] is None
            reviewed = items(client, practice["id"])[0]
            result = submit(
                client, headers, reviewed, answer_for(bank_database, reviewed, index < 3)
            ).json()
            assert result["category"] == "review"
            wrong = client.get("/api/v1/wrong-questions/" + wrong_id).json()
            assert wrong["correct_days"] == [1, 1, 2, 0][index]
            assert wrong["status"] == ("consolidated" if index == 2 else "pending")
        history = client.get("/api/v1/wrong-questions/" + wrong_id).json()
        assert history["attempt_count"] == 5 and history["attempts"][0]["id"] == first["id"]
        assert history["error_count"] == 2


def test_feedback_invalidation_and_distributed_snapshots_are_immutable(bank_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        practice = create(client, headers, count=1)
        item = items(client, practice["id"])[0]
        feedback_url = f"/api/v1/practice-items/{item['id']}/feedback"
        assert (
            client.post(
                feedback_url, headers=headers, json={"reason": "这个选项与解析矛盾"}
            ).status_code
            == 409
        )
        result = submit(client, headers, item, answer_for(bank_database, item, False)).json()
        assert (
            client.post(
                feedback_url, headers=headers, json={"reason": "这个选项与解析矛盾"}
            ).status_code
            == 200
        )
        for model, values in ((PracticeItem, {"snapshot": {}}), (Question, {"content": {}})):
            with pytest.raises(IntegrityError), Session(bank_database) as session, session.begin():
                session.execute(update(model).values(**values))
        invalidate(bank_database, UUID(item["question_id"]), "维护者确认题目条件不完整")
        assert client.get("/api/v1/wrong-questions").json()["total"] == 0
        assert (
            client.get("/api/v1/wrong-questions/" + result["wrong_question_id"]).json()["is_valid"]
            is False
        )
        restored = items(client, practice["id"])[0]
        assert restored["attempt"]["is_valid"] is False and restored["stem"] == item["stem"]
        assert (
            client.get("/api/v1/practice-sessions/" + practice["id"]).json()["effective_count"] == 0
        )
        assert all(
            row["sample_count"] == 0
            for row in client.get("/api/v1/learning/performance").json()["items"]
        )


def test_simultaneous_submissions_only_create_one_attempt(bank_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        practice = create(client, headers, count=1)
        item = items(client, practice["id"])[0]
        correct = answer_for(bank_database, item)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda key: submit(client, headers, item, correct, key), ["one", "two"])
            )
        assert all(result.status_code == 201 for result in results)
        assert results[0].json()["id"] == results[1].json()["id"]
        with Session(bank_database) as session:
            assert session.scalar(select(func.count()).select_from(Attempt)) == 1


def test_ai_unconfigured_preserves_mode_and_bank_does_not_require_models(bank_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        failed = create(
            client, headers, question_source="ai", generation_requirements="侧重概念辨析"
        )
        assert failed["status"] == "failed" and failed["question_source"] == "ai"
        assert failed["settings"]["generation_requirements"] == "侧重概念辨析"
        assert items(client, failed["id"]) == []
        assert create(client, headers, "bank", question_source="bank")["status"] == "ready"


def test_ai_concept_questions_accept_structure_without_template_verification(
    bank_database, tmp_path
):
    with Session(bank_database) as session:
        point = str(
            session.scalar(
                select(KnowledgePoint.id).where(KnowledgePoint.code == "linear-list.definition")
            )
        )

    class ConceptGeneration:
        available = True

        def stream(self, messages, cancelled):
            yield json.dumps(
                {
                    "items": [
                        {
                            "type": "true_false",
                            "stem": "逻辑结构等同于物理存储布局。",
                            "options": [
                                {"key": "true", "text": "正确"},
                                {"key": "false", "text": "错误"},
                            ],
                            "answer": "false",
                            "explanation": "同一逻辑结构可以采用不同存储布局。",
                            "hint": "区分逻辑关系与物理位置。",
                            "knowledge_point_id": point,
                            "difficulty": "basic",
                            "citation_numbers": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=ConceptGeneration())) as client:
        _, headers = register(client)
        practice = create(
            client, headers, question_source="ai", count=1, knowledge_point_ids=[point]
        )
        wait_practice(client, practice["id"])
        item = items(client, practice["id"])[0]
        assert item["source_type"] == "ai" and item["attempt"] is None
        result = submit(client, headers, item, "false").json()
        assert result["is_correct"] and result["source_info"]["verification"] is None
        repeated = create(
            client,
            headers,
            "same-generated-question",
            question_source="ai",
            count=1,
            knowledge_point_ids=[point],
        )
        wait_practice(client, repeated["id"])
        repeated_item = items(client, repeated["id"])[0]
        assert repeated_item["question_id"] == item["question_id"]
        assert submit(client, headers, repeated_item, "false").json()["category"] == "repeat"


def test_populated_practice_migration_down_and_up(bank_database, migration_config, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        practice = create(client, headers, count=1)
        item = items(client, practice["id"])[0]
        assert (
            submit(client, headers, item, answer_for(bank_database, item, False)).status_code == 201
        )
    command.downgrade(migration_config, "0003")
    command.upgrade(migration_config, "head")
    command.check(migration_config)


@pytest.mark.parametrize("review_fails", [False, True])
def test_ai_drafts_are_not_published_until_review_succeeds(bank_database, tmp_path, review_fails):
    with Session(bank_database) as session:
        point = str(
            session.scalar(
                select(KnowledgePoint.id).where(KnowledgePoint.code == "stack-queue.stack")
            )
        )

    class ReviewedGeneration:
        available = True
        calls = 0

        def stream(self, messages, cancelled):
            self.calls += 1
            with Session(bank_database) as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(Question)
                        .where(Question.source_type == "ai")
                    )
                    == 0
                )
            if self.calls == 2:
                assert "独立复核草稿" in messages[0]["content"]
                assert "待复核草稿" in messages[1]["content"]
                if review_fails:
                    yield '{"items":[]}'
                    return
            yield json.dumps(
                {
                    "items": [
                        {
                            "type": "single_choice",
                            "stem": "空栈依次 push(1)、push(2)、pop()，弹出什么？",
                            "options": [{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
                            "answer": "A" if self.calls == 1 else "B",
                            "explanation": "后进先出，2 最后入栈，因此弹出 2。",
                            "knowledge_point_id": point,
                            "difficulty": "basic",
                            "citation_numbers": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )

    generation = ReviewedGeneration()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=generation)) as client:
        _, headers = register(client)
        practice = create(
            client, headers, question_source="ai", count=1, knowledge_point_ids=[point]
        )
        wait_practice(client, practice["id"], "failed" if review_fails else "ready")
        assert generation.calls == 2
        if review_fails:
            assert items(client, practice["id"]) == []
            with Session(bank_database) as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(Question)
                        .where(Question.source_type == "ai")
                    )
                    == 0
                )
        else:
            item = items(client, practice["id"])[0]
            assert submit(client, headers, item, "B").json()["is_correct"]


def test_ai_history_marks_deleted_document_sources(bank_database, tmp_path):
    with Session(bank_database) as session:
        point = str(
            session.scalar(
                select(KnowledgePoint.id).where(KnowledgePoint.code == "stack-queue.stack")
            )
        )

    class CitedGeneration:
        available = True

        def stream(self, messages, cancelled):
            yield json.dumps(
                {
                    "items": [
                        {
                            "type": "true_false",
                            "stem": "栈采用后进先出规则。",
                            "options": [
                                {"key": "true", "text": "正确"},
                                {"key": "false", "text": "错误"},
                            ],
                            "answer": "true",
                            "explanation": "栈顶执行入栈和出栈。",
                            "hint": "从栈顶操作考虑。",
                            "knowledge_point_id": point,
                            "difficulty": "basic",
                            "citation_numbers": [1],
                        }
                    ]
                },
                ensure_ascii=False,
            )

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(
        create_app(
            settings, embedding_service=TestEmbedding(), generation_service=CitedGeneration()
        )
    ) as client:
        library, headers = register(client)
        document = upload(client, library, headers)["document"]["id"]
        wait_document(client, document, "ready")
        practice = create(
            client, headers, question_source="ai", count=1, knowledge_point_ids=[point]
        )
        wait_practice(client, practice["id"])
        item = items(client, practice["id"])[0]
        result = submit(client, headers, item, "false").json()
        assert result["source_info"]["citations"][0]["document_id"] == document
        assert client.delete("/api/v1/documents/" + document, headers=headers).status_code == 202
        restored = items(client, practice["id"])[0]
        assert restored["attempt"]["source_info"]["citations"][0]["source_deleted"]
        wrong = client.get("/api/v1/wrong-questions/" + result["wrong_question_id"]).json()
        assert wrong["question"]["source_info"]["citations"][0]["source_deleted"]


def test_conversation_context_is_carried_to_ai_practice_and_checked_for_owner(
    bank_database, tmp_path
):
    with Session(bank_database) as session:
        point = str(
            session.scalar(
                select(KnowledgePoint.id).where(KnowledgePoint.code == "linear-list.definition")
            )
        )
    contexts = []

    class ContextGeneration:
        available = True

        def stream(self, messages, cancelled):
            contexts.append(messages[-1]["content"])
            yield json.dumps(
                {
                    "items": [
                        {
                            "type": "true_false",
                            "stem": "逻辑结构可以由不同存储方式实现。",
                            "options": [
                                {"key": "true", "text": "正确"},
                                {"key": "false", "text": "错误"},
                            ],
                            "answer": "true",
                            "explanation": "逻辑关系与存储布局分开。",
                            "knowledge_point_id": point,
                            "difficulty": "basic",
                            "citation_numbers": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=ContextGeneration())) as client:
        _, headers = register(client)
        conversation = client.post(
            "/api/v1/conversations", headers=headers, json={"knowledge_point_id": point}
        ).json()["id"]
        with Session(bank_database) as session, session.begin():
            session.add(
                Message(
                    conversation_id=UUID(conversation),
                    sequence=1,
                    role="user",
                    content="我正在理解逻辑关系与存储布局，请出概念辨析题。",
                    status="completed",
                )
            )
        practice = create(
            client,
            headers,
            question_source="ai",
            count=1,
            source_conversation_id=conversation,
            knowledge_point_ids=[point],
        )
        wait_practice(client, practice["id"])
        assert practice["source_conversation_id"] == conversation
        assert len(contexts) == 2 and all("逻辑关系与存储布局" in value for value in contexts)
        other = TestClient(client.app)
        try:
            _, other_headers = register(other, "outsider")
            assert (
                other.post(
                    "/api/v1/practice-sessions",
                    headers=other_headers,
                    json={
                        "client_request_id": "foreign-conversation",
                        "source_conversation_id": conversation,
                    },
                ).status_code
                == 404
            )
            assert other.get("/api/v1/practice-sessions").json()["total"] == 0
        finally:
            other.close()


@pytest.mark.parametrize("correct_count,expected", [(2, "priority"), (3, "steady")])
def test_performance_threshold_and_repeat_exclusion(
    bank_database, tmp_path, correct_count, expected
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with Session(bank_database) as session:
        root = str(
            session.scalar(select(KnowledgePoint.id).where(KnowledgePoint.code == "linear-list"))
        )
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        practice = create(client, headers, count=5, knowledge_point_ids=[root])
        for index, item in enumerate(items(client, practice["id"])):
            assert (
                submit(
                    client,
                    headers,
                    item,
                    answer_for(bank_database, item, index < correct_count),
                    item["id"],
                ).status_code
                == 201
            )
        analysis = client.get("/api/v1/learning/performance").json()
        row = next(value for value in analysis["items"] if value["knowledge_point_id"] == root)
        assert row["sample_count"] == 5 and row["accuracy"] == correct_count / 5
        assert row["status"] == expected
        repeated = create(client, headers, "again", count=5, knowledge_point_ids=[root])
        for item in items(client, repeated["id"]):
            assert (
                submit(client, headers, item, answer_for(bank_database, item), item["id"]).json()[
                    "category"
                ]
                == "repeat"
            )
        row = next(
            value
            for value in client.get("/api/v1/learning/performance").json()["items"]
            if value["knowledge_point_id"] == root
        )
        assert row["sample_count"] == 5 and row["correct_count"] == correct_count
        with Session(bank_database) as session, session.begin():
            first = session.scalar(select(Attempt).where(Attempt.category == "first_independent"))
            first.created_at -= timedelta(days=31)
        row = next(
            value
            for value in client.get("/api/v1/learning/performance").json()["items"]
            if value["knowledge_point_id"] == root
        )
        assert row["sample_count"] == 4 and row["status"] == "insufficient"


@pytest.mark.parametrize(
    "output", ["not-json", '{"items":[]}', '{"items":[{"answer":"secret-test-value"}]}']
)
def test_invalid_ai_output_does_not_publish_questions_or_fallback(bank_database, tmp_path, output):
    class BrokenGeneration:
        available = True

        def stream(self, messages, cancelled):
            yield output

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=BrokenGeneration())) as client:
        _, headers = register(client)
        practice = create(client, headers, question_source="ai", count=1)
        failed = wait_practice(client, practice["id"], "failed")
        assert failed["question_source"] == "ai" and failed["error_code"] == "AI_QUESTIONS_INVALID"
        assert "secret-test-value" not in failed["error_message"]
        assert items(client, practice["id"]) == []
        with Session(bank_database) as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(Question).where(Question.source_type == "ai")
                )
                == 0
            )
