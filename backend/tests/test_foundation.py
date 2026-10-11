from pathlib import Path

from fastapi.testclient import TestClient
from qdrant_client.models import Distance, VectorParams

from capstone.core.settings import Settings
from capstone.main import create_app


def test_local_storage_survives_restart_and_releases_lock(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["components"] == {"sqlite": "ok", "qdrant": "ok"}
        assert settings.sqlite_path.is_file()
        assert settings.uploads_dir.is_dir()
        with client.app.state.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        client.app.state.vector_client.create_collection(
            "foundation_test", vectors_config=VectorParams(size=3, distance=Distance.COSINE)
        )

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/api/v1/health").status_code == 200
        assert restarted.app.state.vector_client.collection_exists("foundation_test")


def test_storage_failure_is_not_reported_as_healthy(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:

        def fail_collections():
            raise RuntimeError("Simulated storage failure")

        monkeypatch.setattr(client.app.state.vector_client, "get_collections", fail_collections)
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
        assert response.json()["components"]["qdrant"] == "error"
        assert "Simulated storage failure" not in response.text
