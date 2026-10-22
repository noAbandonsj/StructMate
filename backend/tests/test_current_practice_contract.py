from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_documents import register
from test_practice import create, items

from capstone.core.settings import Settings
from capstone.db.models import PracticeSession
from capstone.main import create_app


@pytest.mark.parametrize(
    "retired",
    [
        {"mode": "adaptive"},
        {"question_source": "bank"},
        {"knowledge_point_ids": []},
        {"topic": "queue"},
    ],
)
def test_retired_creation_fields_are_rejected_without_writes(practice_db, tmp_path, retired):
    with TestClient(
        create_app(Settings(_env_file=None, environment="test", data_dir=tmp_path))
    ) as client:
        _, headers = register(client)
        chapter = client.get("/api/v1/chapters").json()["items"][0]["id"]
        response = client.post(
            "/api/v1/practice-sessions",
            headers=headers,
            json={"client_request_id": "retired", "chapter_id": chapter, **retired},
        )
        assert response.status_code == 422
        with Session(practice_db) as session:
            assert session.scalar(select(func.count()).select_from(PracticeSession)) == 0


def test_retired_routes_are_absent_and_unknown_chapters_cannot_create_sessions(
    practice_db, tmp_path
):
    with TestClient(
        create_app(Settings(_env_file=None, environment="test", data_dir=tmp_path))
    ) as client:
        _, headers = register(client)
        exercise = create(client, headers, count=1)
        item = items(client, exercise["id"])[0]
        for action in ("attempts", "feedback"):
            assert (
                client.post(
                    f"/api/v1/practice-items/{item['id']}/{action}", headers=headers, json={}
                ).status_code
                == 404
            )
        assert client.get("/api/v1/knowledge-points").status_code == 404
        assert (
            client.post(
                "/api/v1/practice-sessions",
                headers=headers,
                json={"client_request_id": "unknown", "chapter_id": str(uuid4())},
            ).status_code
            == 422
        )
