import json
from threading import Event

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_documents import register

from capstone.core.errors import ApiError
from capstone.core.model_config import ModelConnection
from capstone.core.settings import Settings
from capstone.main import create_app


def test_unconfigured_and_blank_optional_model_connections(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        generation_base_url=" ",
        embedding_api_key="",
        embedding_dimension="",
    )
    assert settings.connection("generation") is None
    assert settings.connection("embedding") is None


def test_backend_env_parses_two_independent_connections_and_hides_keys(tmp_path):
    path = tmp_path / "model.env"
    path.write_text(
        "\n".join(
            [
                "CAPSTONE_GENERATION_BASE_URL=https://generation.example.test/v1/",
                "CAPSTONE_GENERATION_MODEL=model-text",
                "CAPSTONE_GENERATION_API_KEY=private-generation-test-key",
                "CAPSTONE_GENERATION_TIMEOUT_SECONDS=75",
                "CAPSTONE_EMBEDDING_BASE_URL=http://127.0.0.1:8123/embeddings",
                "CAPSTONE_EMBEDDING_MODEL=model-vector",
                "CAPSTONE_EMBEDDING_TIMEOUT_SECONDS=20",
                "CAPSTONE_EMBEDDING_DIMENSION=768",
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings(_env_file=path, data_dir=tmp_path)
    text, vector = settings.connection("generation"), settings.connection("embedding")
    assert text.base_url == "https://generation.example.test/v1/"
    assert text.timeout_seconds == 75 and text.model == "model-text"
    assert text.api_key.get_secret_value() == "private-generation-test-key"
    assert vector.expected_dimension == 768 and vector.timeout_seconds == 20
    assert vector.api_key is None and text.expected_dimension is None
    assert (
        "private-generation-test-key"
        not in repr(settings) + repr(text) + settings.model_dump_json() + text.model_dump_json()
    )
    assert "api_key" not in text.model_dump()


@pytest.mark.parametrize(
    "change",
    [
        {"generation_model": "only-name"},
        {"embedding_api_key": "private-test-key"},
        {"generation_base_url": "file:///model", "generation_model": "name"},
        {
            "embedding_base_url": "https://user:private-test-key@example.test",
            "embedding_model": "name",
        },
        {
            "embedding_base_url": "https://example.test#private-test-key",
            "embedding_model": "name",
        },
        {"generation_base_url": "https://example.test:bad", "generation_model": "name"},
        {"generation_timeout_seconds": 0},
        {"embedding_timeout_seconds": float("inf")},
        {"embedding_dimension": -1},
    ],
    ids=[
        "partial-name",
        "partial-key",
        "scheme",
        "userinfo",
        "fragment",
        "port",
        "zero-timeout",
        "infinite-timeout",
        "dimension",
    ],
)
def test_invalid_connections_fail_before_startup_without_key_in_diagnostics(change, tmp_path):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, data_dir=tmp_path, **change)
    assert "private-test-key" not in str(error.value)


def test_parameters_do_not_claim_adapter_success_or_leak_to_api(migrated_database, tmp_path):
    settings = Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path,
        generation_base_url="https://text.example.test",
        generation_model="private-text-name",
        generation_api_key="private-generation-test-key",
        embedding_base_url="https://vector.example.test",
        embedding_model="private-vector-name",
        embedding_api_key="private-embedding-test-key",
    )
    with TestClient(create_app(settings)) as client:
        register(client)
        assert client.app.state.generation_service.connection.model == "private-text-name"
        assert client.app.state.embedding_service.connection.model == "private-vector-name"
        assert not client.app.state.generation_service.available
        assert not client.app.state.embedding_service.available
        public = [
            client.get(path).json()
            for path in (
                "/api/v1/health",
                "/api/v1/conversations/config",
                "/api/v1/documents/upload-config",
            )
        ]
        assert public[1]["generation_available"] is False
        payload = json.dumps(public)
        assert all(
            value not in payload
            for value in (
                "private-text-name",
                "private-vector-name",
                "text.example.test",
                "vector.example.test",
                "private-generation-test-key",
                "private-embedding-test-key",
            )
        )
        for action in (
            lambda: client.app.state.embedding_service.embed(["真实文本"]),
            lambda: client.app.state.generation_service.stream([], Event()),
        ):
            with pytest.raises(ApiError) as error:
                action()
            assert "协议适配尚未接通" in error.value.detail["message"]
            assert "private-" not in str(error.value.detail)


def test_connection_diagnostics_mask_url_credentials():
    with pytest.raises(ValidationError) as error:
        ModelConnection(base_url="https://user:private-test-key@example.test", model="name")
    assert "private-test-key" not in str(error.value)
