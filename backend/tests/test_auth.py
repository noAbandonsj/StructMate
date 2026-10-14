from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from capstone.api import auth
from capstone.core.auth import SESSION_COOKIE, token_digest, verify_password
from capstone.core.errors import ApiError
from capstone.core.settings import Settings
from capstone.db.models import AuthSession, KnowledgeBase, User, utc_now
from capstone.main import create_app

ORIGIN = {"Origin": "http://127.0.0.1:5173"}
CREDENTIALS = {"username": "student", "password": "simple-password"}


@pytest.fixture
def client(migrated_database: Engine, tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as http:
        yield http


def register(client: TestClient, **changes) -> dict:
    response = client.post("/api/v1/auth/register", json={**CREDENTIALS, **changes}, headers=ORIGIN)
    assert response.status_code == 201
    return response.json()


def csrf_headers(account: dict) -> dict[str, str]:
    return {**ORIGIN, "X-CSRF-Token": account["csrf_token"]}


def test_registration_logs_in_creates_one_library_and_keeps_credentials_private(
    client: TestClient, migrated_database: Engine
) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={**CREDENTIALS, "username": " Student ", "display_name": " 数据结构同学 "},
        headers=ORIGIN,
    )
    assert response.status_code == 201
    account = response.json()
    assert account["user"]["username"] == "student"
    assert account["user"]["display_name"] == "数据结构同学"
    assert account["default_knowledge_base"]["name"] == "我的资料"
    assert account["default_knowledge_base"]["is_readonly"] is False
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Domain=" not in cookie and "Secure" not in cookie
    assert "Max-Age=604800" in cookie
    raw_token = client.cookies.get(SESSION_COOKIE)
    assert raw_token not in response.text
    assert CREDENTIALS["password"] not in response.text
    assert "password_hash" not in response.text and "token_hash" not in response.text
    assert client.get("/api/v1/auth/me").json() == account
    assert client.get("/api/v1/auth/csrf").json()["csrf_token"] == account["csrf_token"]
    assert client.get("/api/v1/auth/csrf").json()["csrf_token"] == account["csrf_token"]
    with Session(migrated_database) as session:
        user = session.scalars(select(User)).one()
        stored = session.scalars(select(AuthSession)).one()
        library = session.scalars(select(KnowledgeBase)).one()
        assert verify_password(CREDENTIALS["password"], user.password_hash)
        assert user.password_hash != CREDENTIALS["password"]
        assert stored.token_hash == token_digest(raw_token) and stored.token_hash != raw_token
        assert library.owner_id == user.id


def test_duplicate_normalized_username_does_not_create_extra_records(
    client: TestClient, migrated_database: Engine
) -> None:
    register(client)
    previous_token = client.cookies.get(SESSION_COOKIE)
    response = client.post(
        "/api/v1/auth/register", json={**CREDENTIALS, "username": " STUDENT "}, headers=ORIGIN
    )
    assert response.status_code == 409
    assert response.json()["code"] == "USERNAME_TAKEN"
    assert "set-cookie" not in response.headers
    assert client.cookies.get(SESSION_COOKIE) == previous_token
    with Session(migrated_database) as session:
        for model in (User, KnowledgeBase, AuthSession):
            assert session.scalar(select(func.count()).select_from(model)) == 1


def test_registration_failure_rolls_back_entire_account(
    client: TestClient, migrated_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_session(session, *_args):
        session.flush()
        raise ApiError(503, "REGISTRATION_FAILED", "模拟创建失败")

    monkeypatch.setattr(auth, "issue_session", fail_session)
    response = client.post("/api/v1/auth/register", json=CREDENTIALS, headers=ORIGIN)
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    with Session(migrated_database) as session:
        for model in (User, KnowledgeBase, AuthSession):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_login_replaces_previous_cookie_session_and_logout_revokes_it(
    client: TestClient, migrated_database: Engine
) -> None:
    first = register(client)
    old_token = client.cookies.get(SESSION_COOKIE)
    response = client.post("/api/v1/auth/login", json=CREDENTIALS, headers=ORIGIN)
    assert response.status_code == 200
    current = response.json()
    new_token = client.cookies.get(SESSION_COOKIE)
    assert new_token != old_token
    assert current["csrf_token"] != first["csrf_token"]
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Cookie": f"{SESSION_COOKIE}={old_token}"}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/auth/me").status_code == 200
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 1
    assert client.post("/api/v1/auth/logout", headers=csrf_headers(current)).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Cookie": f"{SESSION_COOKIE}={new_token}"}
        ).status_code
        == 401
    )
    assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 204
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(KnowledgeBase)) == 1


def test_bad_password_and_unknown_user_return_same_error(client: TestClient) -> None:
    register(client)
    wrong_password = client.post(
        "/api/v1/auth/login",
        json={**CREDENTIALS, "password": "incorrect-password"},
        headers=ORIGIN,
    )
    missing_user = client.post(
        "/api/v1/auth/login", json={**CREDENTIALS, "username": "unknown"}, headers=ORIGIN
    )
    assert wrong_password.status_code == missing_user.status_code == 401
    assert wrong_password.json() == missing_user.json()
    assert "set-cookie" not in wrong_password.headers
    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize(
    "origin", [None, "null", "http://example.com", "http://127.0.0.1:5173.evil"]
)
def test_registration_and_login_reject_untrusted_origins(client: TestClient, origin: str | None):
    headers = {"Origin": origin} if origin is not None else {}
    for path in ("register", "login"):
        response = client.post(f"/api/v1/auth/{path}", json=CREDENTIALS, headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == "ORIGIN_REJECTED"


def test_api_documentation_origin_can_submit_json(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register", json=CREDENTIALS, headers={"Origin": "http://testserver"}
    )
    assert response.status_code == 201


@pytest.mark.parametrize("token", [None, "", "invalid-token"])
def test_profile_and_logout_require_csrf_for_active_sessions(client: TestClient, token: str | None):
    account = register(client)
    headers = {**ORIGIN}
    if token is not None:
        headers["X-CSRF-Token"] = token
    assert (
        client.patch(
            "/api/v1/auth/me", json={"display_name": "新的名字"}, headers=headers
        ).status_code
        == 403
    )
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403
    assert client.get("/api/v1/auth/me").json()["user"] == account["user"]


def test_profile_change_is_saved_without_changing_username_or_library(client: TestClient) -> None:
    account = register(client)
    response = client.patch(
        "/api/v1/auth/me", json={"display_name": " 新的名字 "}, headers=csrf_headers(account)
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "新的名字"
    restored = client.get("/api/v1/auth/me").json()
    assert restored["user"]["username"] == "student"
    assert restored["default_knowledge_base"] == account["default_knowledge_base"]
    assert restored["csrf_token"] == account["csrf_token"]


def test_session_expiry_is_enforced(client: TestClient, migrated_database: Engine) -> None:
    register(client)
    with Session(migrated_database) as session, session.begin():
        record = session.scalars(select(AuthSession)).one()
        record.created_at = utc_now() - timedelta(days=8)
        record.expires_at = utc_now() - timedelta(days=1)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/csrf").status_code == 401
    assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 204


def test_account_cookie_survives_application_restart(
    migrated_database: Engine, tmp_path: Path
) -> None:
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as first:
        account = register(first)
        token = first.cookies.get(SESSION_COOKIE)
    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set(SESSION_COOKIE, token)
        assert restarted.get("/api/v1/auth/me").json() == account


def test_https_production_cookie_is_secure(migrated_database: Engine, tmp_path: Path) -> None:
    settings = Settings(_env_file=None, environment="production", data_dir=tmp_path)
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        response = client.post("/api/v1/auth/register", json=CREDENTIALS, headers=ORIGIN)
        assert response.status_code == 201
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "bad username"},
        {"password": "short"},
        {"password": "p" * 129},
        {"display_name": " "},
        {"display_name": "名" * 33},
        {"owner_id": "not-allowed"},
    ],
)
def test_invalid_registration_is_rejected_without_echoing_secrets(
    client: TestClient, migrated_database: Engine, changes: dict
) -> None:
    payload = {**CREDENTIALS, **changes}
    response = client.post("/api/v1/auth/register", json=payload, headers=ORIGIN)
    assert response.status_code == 422
    assert payload["password"] not in response.text
    assert response.headers["cache-control"] == "no-store"
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_password_spaces_are_preserved(client: TestClient) -> None:
    password = "  simple password  "
    register(client, password=password)
    assert (
        client.post(
            "/api/v1/auth/login", json={**CREDENTIALS, "password": password.strip()}, headers=ORIGIN
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={**CREDENTIALS, "password": password}, headers=ORIGIN
        ).status_code
        == 200
    )


def test_json_content_type_is_required(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        content='{"username":"student","password":"simple-password"}',
        headers={**ORIGIN, "Content-Type": "application/json-patch+json"},
    )
    assert response.status_code == 415
