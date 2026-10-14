from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from capstone.core.settings import Settings
from capstone.db.models import AuthSession, KnowledgeBase, KnowledgePoint, User
from capstone.main import create_app
from capstone.seed import seed_course_data

ORIGIN = {"Origin": "http://127.0.0.1:5173"}


@pytest.fixture
def clients(migrated_database: Engine, tmp_path: Path) -> Iterator[tuple[TestClient, TestClient]]:
    seed_course_data(migrated_database)
    app = create_app(Settings(_env_file=None, environment="test", data_dir=tmp_path))
    with TestClient(app) as first:
        # Two cookie jars use one running application and one Qdrant client.
        second = TestClient(app)
        try:
            yield first, second
        finally:
            second.close()


def register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "test-password"},
        headers=ORIGIN,
    )
    assert response.status_code == 201
    return response.json()


def test_two_accounts_can_only_read_their_own_library_and_public_course(clients) -> None:
    first, second = clients
    a = register(first, "first")
    b = register(second, "second")
    personal_a = a["default_knowledge_base"]["id"]
    personal_b = b["default_knowledge_base"]["id"]
    libraries_a = first.get("/api/v1/knowledge-bases").json()
    libraries_b = second.get("/api/v1/knowledge-bases").json()
    assert libraries_a["total"] == libraries_b["total"] == 2
    assert {item["kind"] for item in libraries_a["items"]} == {"personal", "course"}
    assert libraries_a["items"][0]["id"] == personal_a
    assert libraries_b["items"][0]["id"] == personal_b
    course_a = next(item for item in libraries_a["items"] if item["kind"] == "course")
    course_b = next(item for item in libraries_b["items"] if item["kind"] == "course")
    assert course_a == course_b and course_a["is_readonly"] is True
    assert first.get(f"/api/v1/knowledge-bases/{personal_a}").json()["is_readonly"] is False
    assert second.get(f"/api/v1/knowledge-bases/{personal_b}").status_code == 200
    assert first.get(f"/api/v1/knowledge-bases/{course_a['id']}").json() == course_a
    for client, other in ((first, personal_b), (second, personal_a)):
        hidden = client.get(f"/api/v1/knowledge-bases/{other}")
        missing = client.get(f"/api/v1/knowledge-bases/{uuid4()}")
        assert hidden.status_code == missing.status_code == 404
        assert hidden.json() == missing.json()
    assert first.get("/api/v1/knowledge-bases").headers["cache-control"] == "no-store"
    assert "owner_id" not in str(libraries_a) and "password" not in str(libraries_a)


def test_catalog_and_library_pagination_are_complete_and_stable(clients) -> None:
    first, _second = clients
    register(first, "student")
    points = first.get("/api/v1/knowledge-points").json()
    assert points["total"] == 31 and len(points["items"]) == 31
    roots = [item for item in points["items"] if item["parent_id"] is None]
    assert len(roots) == 8
    assert [item["code"] for item in roots] == [
        "linear-list",
        "stack-queue",
        "tree",
        "graph",
        "search",
        "sort",
        "hash",
        "complexity",
    ]
    ids = {item["id"] for item in points["items"]}
    assert all(item["parent_id"] is None or item["parent_id"] in ids for item in points["items"])
    paged = []
    for page in range(1, 6):
        response = first.get(f"/api/v1/knowledge-points?page={page}&page_size=7").json()
        assert response["total"] == 31 and response["page"] == page
        paged.extend(response["items"])
    assert paged == points["items"]
    first_library = first.get("/api/v1/knowledge-bases?page=1&page_size=1").json()
    second_library = first.get("/api/v1/knowledge-bases?page=2&page_size=1").json()
    assert first_library["total"] == second_library["total"] == 2
    assert first_library["items"][0]["kind"] == "personal"
    assert second_library["items"][0]["kind"] == "course"
    assert first.get("/api/v1/knowledge-bases?page=3&page_size=1").json()["items"] == []


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101", "page=bad"])
def test_invalid_pagination_is_rejected(clients, query: str) -> None:
    first, _second = clients
    register(first, "student")
    for path in ("knowledge-bases", "knowledge-points"):
        assert first.get(f"/api/v1/{path}?{query}").status_code == 422


def test_all_knowledge_routes_require_login_and_logout_revokes_access(clients) -> None:
    first, _second = clients
    paths = ("/knowledge-bases", f"/knowledge-bases/{uuid4()}", "/knowledge-points")
    for path in paths:
        assert first.get("/api/v1" + path).status_code == 401
    account = register(first, "student")
    assert (
        first.post(
            "/api/v1/auth/logout",
            headers={**ORIGIN, "X-CSRF-Token": account["csrf_token"]},
        ).status_code
        == 204
    )
    for path in paths:
        assert first.get("/api/v1" + path).status_code == 401


def test_read_routes_do_not_create_missing_course_data(migrated_database, tmp_path) -> None:
    app = create_app(Settings(_env_file=None, environment="test", data_dir=tmp_path))
    with TestClient(app) as client:
        register(client, "student")
        with Session(migrated_database) as session:
            counts = {
                model: session.scalar(select(func.count()).select_from(model))
                for model in (User, AuthSession, KnowledgeBase, KnowledgePoint)
            }
        assert client.get("/api/v1/knowledge-bases").json()["total"] == 1
        assert client.get("/api/v1/knowledge-points").json()["items"] == []
        with Session(migrated_database) as session:
            for model, count in counts.items():
                assert session.scalar(select(func.count()).select_from(model)) == count
