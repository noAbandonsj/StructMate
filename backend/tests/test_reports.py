import json
import time
from datetime import UTC, date, datetime, timedelta
from threading import Event
from uuid import UUID

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_documents import ORIGIN, register
from test_practice import answer_for, create, items, submit, submit_group

from capstone.core.settings import Settings
from capstone.db.models import Attempt, Chapter, LearningReport, Question
from capstone.main import create_app
from capstone.services.learning_stats import date_range


def report(client, headers, key="report-1", **dates):
    return client.post("/api/v1/reports", headers=headers, json={"client_request_id": key, **dates})


def wait_report(client, identifier, status="completed"):
    deadline = time.monotonic() + 6
    while True:
        value = client.get(f"/api/v1/reports/{identifier}").json()
        if value["status"] == status:
            return value
        assert time.monotonic() < deadline, value
        time.sleep(0.02)


def test_empty_stats_unconfigured_report_export_and_permissions(practice_db, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        other = TestClient(client.app)
        try:
            _, headers = register(client)
            register(other, "other")
            stats = client.get("/api/v1/learning/stats").json()
            assert stats["attempts"] == {"count": 0, "correct_count": 0, "accuracy": None}
            assert (
                date.fromisoformat(stats["to_date"]) - date.fromisoformat(stats["from_date"])
            ).days == 6
            assert all(point["evidence"] == "insufficient" for point in stats["chapters"])
            created = report(client, headers)
            assert created.status_code == 202
            value = created.json()
            assert value["status"] == "failed" and value["content"] == ""
            assert value["generated_at"] is None
            assert value["snapshot"]["attempts"]["count"] == 0
            assert report(client, headers).json()["id"] == value["id"]
            assert report(client, headers, from_date="2026-01-01").status_code == 409
            assert report(client, ORIGIN, "csrf").status_code == 403
            path = f"/api/v1/reports/{value['id']}"
            exported = client.get(path + "/export")
            assert exported.status_code == 200
            assert "文字报告尚未生成" in exported.text and "未评估" in exported.text
            assert exported.headers["cache-control"] == "no-store"
            assert other.get(path).status_code == 404
            assert other.get(path + "/export").status_code == 404
            assert other.get("/api/v1/reports").json()["total"] == 0
            assert client.get("/api/v1/reports").json()["total"] == 1
            assert other.get("/api/v1/learning/stats").json()["attempts"]["count"] == 0
            for query in (
                "from_date=2026-10-16&to_date=2026-10-15",
                "to_date=0001-01-01",
                "from_date=0001-01-01",
                "to_date=9999-12-31",
            ):
                assert client.get("/api/v1/learning/stats?" + query).status_code == 422
            client.cookies.clear()
            assert client.get(path + "/export").status_code == 401
        finally:
            other.close()


def test_statistics_shanghai_boundaries_categories_and_validity(practice_db, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        practice = create(client, headers)
        assert (
            submit_group(
                client, headers, practice_db, practice, lambda index: index != 1
            ).status_code
            == 201
        )
        start = datetime(2020, 1, 1, 16, tzinfo=UTC)  # Shanghai Jan 2 midnight
        with Session(practice_db) as session, session.begin():
            rows = session.scalars(select(Attempt).order_by(Attempt.created_at)).all()
            for row, offset, category in zip(
                rows,
                [-1, 0, 10, 86399, 86400],
                ["repeat", "first", "first", "review", "repeat"],
                strict=True,
            ):
                row.created_at = start + timedelta(seconds=offset)
                row.category = category
                row.hinted = offset == 10
            invalid_question_id = rows[1].question_id
        path = "/api/v1/learning/stats?from_date=2020-01-02&to_date=2020-01-02"
        data = client.get(path).json()
        assert data["attempts"]["count"] == 3
        assert data["categories"]["first"] == {"count": 2, "correct_count": 1, "accuracy": 0.5}
        assert data["categories"]["review"]["count"] == 1
        assert data["categories"]["repeat"]["accuracy"] is None
        assert data["hinted_attempt_count"] == 1 and data["learning"]["active_days"] == 1
        assert "duration" not in json.dumps(data)
        with Session(practice_db) as session, session.begin():
            session.execute(
                update(Question).where(Question.id == invalid_question_id).values(is_valid=False)
            )
        data = client.get(path).json()
        assert data["attempts"]["count"] == 2
        assert data["categories"]["first"] == {"count": 1, "correct_count": 1, "accuracy": 1}
        first, last, begin, end = date_range(now=datetime(2026, 10, 15, 16, tzinfo=UTC))
        assert first == date(2026, 10, 10) and last == date(2026, 10, 16)
        assert end - begin == timedelta(days=7)


def test_report_frozen_before_generation_and_history_does_not_change(practice_db, tmp_path):
    class DelayedModel:
        available = True

        def __init__(self):
            self.started, self.release = Event(), Event()
            self.prompts = []

        def stream(self, messages, cancelled):
            self.prompts.append(messages)
            self.started.set()
            assert self.release.wait(5)
            yield "首次作答新题 1 道，证据不足；继续尝试不同新题。"

    model = DelayedModel()
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=model)) as client:
        _, headers = register(client)
        practice = create(client, headers, count=1)
        questions = items(client, practice["id"])
        submit(client, headers, questions[0], answer_for(practice_db, questions[0]))
        first = report(client, headers).json()
        try:
            assert model.started.wait(3)
            assert first["snapshot"]["attempts"]["count"] == 1
            with Session(practice_db) as session:
                other_chapter = session.scalar(
                    select(Chapter.id).where(Chapter.code == "stack-queue")
                )
            second = create(client, headers, "next", count=1, chapter_ids=[str(other_chapter)])
            question = items(client, second["id"])[0]
            submit(client, headers, question, answer_for(practice_db, question), "second")
            assert report(client, headers).json()["id"] == first["id"]
            assert client.get("/api/v1/learning/stats").json()["attempts"]["count"] == 2
        finally:
            model.release.set()
        finished = wait_report(client, first["id"])
        assert len(model.prompts) == 1
        assert json.loads(model.prompts[0][1]["content"])["attempts"]["count"] == 1
        assert finished["snapshot"] == first["snapshot"]
        assert finished["generated_at"] and finished["content"]
        with Session(practice_db) as session, session.begin():
            session.execute(
                update(Question)
                .where(Question.id == UUID(questions[0]["question_id"]))
                .values(is_valid=False)
            )
        assert client.get("/api/v1/learning/stats").json()["attempts"]["count"] == 1
        assert client.get(f"/api/v1/reports/{first['id']}").json() == finished
        for changes in ({"snapshot": {}}, {"content": "rewritten"}):
            with (
                Session(practice_db) as session,
                pytest.raises(IntegrityError),
                session.begin(),
            ):
                session.execute(
                    update(LearningReport)
                    .where(LearningReport.id == UUID(first["id"]))
                    .values(**changes)
                )
        assert (
            client.get("/api/v1/learning/overview").json()["recent_practices"][0]["id"]
            == second["id"]
        )
        second = report(client, headers, "report-new").json()
        assert second["id"] != first["id"]
        wait_report(client, second["id"])
        assert client.get("/api/v1/reports").json()["total"] == 2


def test_failed_and_interrupted_reports_keep_snapshot_and_migration_preserves_data(
    practice_db, migration_config, tmp_path
):
    class FailedModel:
        available = True

        def stream(self, messages, cancelled):
            raise RuntimeError("private-model-secret")
            yield

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, generation_service=FailedModel())) as client:
        _, headers = register(client)
        create(client, headers)
        value = report(client, headers).json()
        failed = wait_report(client, value["id"], "failed")
        assert failed["snapshot"] == value["snapshot"]
        assert "private-model-secret" not in json.dumps(failed)
        assert failed["error_code"] == "REPORT_FAILED"
        with Session(practice_db) as session, session.begin():
            session.execute(update(LearningReport).values(status="generating"))
        runner = client.app.state.report_runner
        runner.start()
        assert wait_report(client, value["id"], "failed")["error_code"] == "REPORT_INTERRUPTED"
        assert report(client, headers).json()["id"] == value["id"]
        command.downgrade(migration_config, "0005")
        with practice_db.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT count(*) FROM practice_sessions").scalar() == 0
            )
        command.upgrade(migration_config, "head")
        assert client.get("/api/v1/reports").json()["total"] == 0
