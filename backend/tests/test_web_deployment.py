from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from capstone import web
from capstone.core.settings import Settings
from capstone.main import create_app


@pytest.fixture
def built_web(tmp_path, monkeypatch):
    directory = tmp_path / "web"
    assets = directory / "assets"
    assets.mkdir(parents=True)
    (directory / "index.html").write_text(
        '<html><div id="app">desktop-shell</div></html>', encoding="utf-8"
    )
    (assets / "index-test.js").write_text('console.log("desktop-asset")', encoding="utf-8")
    monkeypatch.setattr(web, "FRONTEND_DIST", directory)
    return directory


def test_web_mode_requires_a_real_build_before_starting(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "FRONTEND_DIST", tmp_path / "missing")
    with pytest.raises(RuntimeError, match="pnpm.cmd build"):
        create_app(Settings(_env_file=None, data_dir=tmp_path, serve_frontend=True))
    assert not (tmp_path / "capstone.db").exists()


def test_development_default_does_not_publish_build(migrated_database, tmp_path, built_web):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        assert client.get("/").status_code == 404
        assert client.get("/assets/index-test.js").status_code == 404
        assert client.get("/api/v1/health").status_code == 200


def test_spa_routes_refresh_assets_and_api_404_stay_separate(
    migrated_database, tmp_path, built_web
):
    settings = Settings(_env_file=None, data_dir=tmp_path, serve_frontend=True)
    with TestClient(create_app(settings)) as client:
        for path in (
            "/",
            "/login",
            "/register",
            "/knowledge",
            "/chat/" + str(uuid4()),
            "/practice/" + str(uuid4()),
            "/wrong",
            "/reports/" + str(uuid4()),
            "/unknown-route",
        ):
            response = client.get(path)
            assert response.status_code == 200 and "desktop-shell" in response.text
            assert response.headers["content-type"].startswith("text/html")
        assert client.head("/reports").content == b""
        assert client.get("/").headers["cache-control"] == "no-cache"
        asset = client.get("/assets/index-test.js")
        assert asset.status_code == 200 and "desktop-asset" in asset.text
        assert "javascript" in asset.headers["content-type"]
        for path in ("/api/v1/not-found", "/assets/not-found.js", "/src/main.ts", "/.env"):
            response = client.get(path)
            assert response.status_code == 404 and "desktop-shell" not in response.text
        assert "/{path}" not in str(client.get("/openapi.json").json()["paths"])


def test_same_origin_cookie_login_logout_and_private_api_still_work(
    migrated_database, tmp_path, built_web
):
    origin = "http://127.0.0.1:8000"
    settings = Settings(_env_file=None, data_dir=tmp_path, serve_frontend=True)
    with TestClient(create_app(settings), base_url=origin) as client:
        response = client.post(
            "/api/v1/auth/register",
            headers={"Origin": origin},
            json={"username": "desktop", "password": "test-password"},
        )
        assert response.status_code == 201
        headers = {"Origin": origin, "X-CSRF-Token": response.json()["csrf_token"]}
        assert client.get("/api/v1/learning/stats").status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        assert client.get("/api/v1/learning/stats").status_code == 401
        assert client.get("/login").status_code == 200


def test_static_mount_does_not_expose_files_outside_assets(migrated_database, tmp_path, built_web):
    (tmp_path / ".env").write_text("private-test-secret", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir=tmp_path, serve_frontend=True)
    with TestClient(create_app(settings)) as client:
        for path in ("/assets/%2e%2e/.env", "/assets/%2e%2e/%2e%2e/.env", "/data/capstone.db"):
            response = client.get(path)
            assert response.status_code == 404
            assert "private-test-secret" not in response.text
