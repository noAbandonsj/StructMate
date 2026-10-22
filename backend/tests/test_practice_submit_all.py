from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_documents import register
from test_practice import answer_for, create, items

from capstone.core.errors import ApiError
from capstone.core.settings import Settings
from capstone.db.models import Attempt, PracticeSession, WrongQuestion
from capstone.main import create_app
from capstone.manage_questions import invalidate
from capstone.services import practice as service


def payload(engine, questions):
    return {
        "client_request_id": "submit-group",
        "answers": [
            {"practice_item_id": item["id"], "answer": answer_for(engine, item)}
            for item in questions
        ],
    }


def app(tmp_path):
    return create_app(Settings(_env_file=None, environment="test", data_dir=tmp_path))


def test_submit_all_publishes_results_together_and_retries_do_not_count_twice(
    practice_db, tmp_path
):
    with TestClient(app(tmp_path)) as client:
        _, headers = register(client)
        exercise = create(client, headers, count=3)
        questions = items(client, exercise["id"])
        body = payload(practice_db, questions)
        body["answers"][0]["answer"] = answer_for(practice_db, questions[0], False)
        assert (
            client.post(
                f"/api/v1/practice-items/{questions[1]['id']}/hint", headers=headers
            ).status_code
            == 200
        )
        assert all(item["attempt"] is None for item in items(client, exercise["id"]))
        url = f"/api/v1/practice-sessions/{exercise['id']}/submit"
        first = client.post(url, headers=headers, json=body)
        assert first.status_code == 201
        result = first.json()
        assert result["practice"]["status"] == "completed"
        assert result["practice"]["submitted_count"] == 3
        assert result["practice"]["correct_count"] == 2
        assert result["items"][1]["attempt"]["category"] == "first_hinted"
        repeated = client.post(url, headers=headers, json=body)
        assert repeated.status_code == 201
        assert [item["attempt"]["id"] for item in repeated.json()["items"]] == [
            item["attempt"]["id"] for item in result["items"]
        ]
        body["answers"][0]["answer"] = answer_for(practice_db, questions[0])
        assert client.post(url, headers=headers, json=body).status_code == 409
        with Session(practice_db) as session:
            assert session.scalar(select(func.count()).select_from(Attempt)) == 3
            assert session.scalar(select(func.count()).select_from(WrongQuestion)) == 1


def test_incomplete_invalid_duplicate_or_foreign_answers_do_not_submit_anything(
    practice_db, tmp_path
):
    with TestClient(app(tmp_path)) as client:
        _, headers = register(client)
        exercise = create(client, headers, count=2)
        questions = items(client, exercise["id"])
        other = create(client, headers, "other", count=1)
        foreign = items(client, other["id"])[0]
        body = payload(practice_db, questions)
        url = f"/api/v1/practice-sessions/{exercise['id']}/submit"
        invalid = [
            body["answers"][:1],
            [body["answers"][0]] * 2,
            [body["answers"][0], {"practice_item_id": questions[1]["id"], "answer": "invalid"}],
            [
                body["answers"][0],
                {
                    "practice_item_id": foreign["id"],
                    "answer": answer_for(practice_db, foreign),
                },
            ],
        ]
        for answers in invalid:
            assert (
                client.post(url, headers=headers, json={**body, "answers": answers}).status_code
                == 422
            )
        assert client.post(url, headers={"Origin": headers["Origin"]}, json=body).status_code == 403
        outsider = TestClient(client.app)
        try:
            _, outsider_headers = register(outsider, "outsider")
            assert outsider.post(url, headers=outsider_headers, json=body).status_code == 404
        finally:
            outsider.close()
        with Session(practice_db) as session:
            assert session.scalar(select(func.count()).select_from(Attempt)) == 0
            assert session.scalar(select(func.count()).select_from(WrongQuestion)) == 0


def test_failure_after_first_answer_rolls_back_the_whole_group(practice_db, tmp_path, monkeypatch):
    original = service._record_answer
    calls = 0

    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ApiError(409, "TEST_FAILURE", "模拟中断")
        return original(*args)

    with TestClient(app(tmp_path)) as client:
        _, headers = register(client)
        exercise = create(client, headers, count=2)
        questions = items(client, exercise["id"])
        body = payload(practice_db, questions)
        body["answers"][0]["answer"] = answer_for(practice_db, questions[0], False)
        monkeypatch.setattr(service, "_record_answer", fail_second)
        url = f"/api/v1/practice-sessions/{exercise['id']}/submit"
        assert client.post(url, headers=headers, json=body).status_code == 409
        with Session(practice_db) as session:
            assert session.scalar(select(func.count()).select_from(Attempt)) == 0
            assert session.scalar(select(func.count()).select_from(WrongQuestion)) == 0
            assert session.get(PracticeSession, UUID(exercise["id"])).status == "ready"
        monkeypatch.setattr(service, "_record_answer", original)
        assert client.post(url, headers=headers, json=body).status_code == 201


def test_legacy_partial_answers_are_preserved_and_disabled_questions_are_excluded(
    practice_db, tmp_path
):
    with TestClient(app(tmp_path)) as client:
        _, headers = register(client)
        exercise = create(client, headers, count=3)
        questions = items(client, exercise["id"])
        # Seed a historical partial submission directly; this write path is retired.
        from capstone.db.models import PracticeItem

        with Session(practice_db) as session, session.begin():
            stored = session.get(PracticeItem, UUID(questions[0]["id"]))
            attempt = Attempt(
                user_id=UUID(client.get("/api/v1/auth/me").json()["user"]["id"]),
                practice_item_id=stored.id,
                question_id=stored.question_id,
                request_id="legacy",
                answer=stored.snapshot["answer"],
                is_correct=True,
                hinted=False,
                category="first_independent",
            )
            session.add(attempt)
            session.flush()
            first = {"id": str(attempt.id)}
        invalidate(practice_db, UUID(questions[2]["question_id"]), "此题已确认条件缺失")
        response = client.post(
            f"/api/v1/practice-sessions/{exercise['id']}/submit",
            headers=headers,
            json=payload(practice_db, questions[:2]),
        )
        assert response.status_code == 201
        result = response.json()
        assert result["practice"]["effective_count"] == 2
        assert result["practice"]["submitted_count"] == 2
        assert result["practice"]["status"] == "completed"
        assert result["items"][0]["attempt"]["id"] == first["id"]
        assert not result["items"][2]["is_valid"] and result["items"][2]["attempt"] is None


def test_concurrent_group_submissions_have_one_set_of_attempts(practice_db, tmp_path):
    with TestClient(app(tmp_path)) as client:
        _, headers = register(client)
        exercise = create(client, headers, count=3)
        body = payload(practice_db, items(client, exercise["id"]))
        url = f"/api/v1/practice-sessions/{exercise['id']}/submit"
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(lambda _: client.post(url, headers=headers, json=body), range(2))
            )
        assert all(response.status_code == 201 for response in responses)
        assert [item["attempt"]["id"] for item in responses[0].json()["items"]] == [
            item["attempt"]["id"] for item in responses[1].json()["items"]
        ]
        with Session(practice_db) as session:
            assert session.scalar(select(func.count()).select_from(Attempt)) == 3
