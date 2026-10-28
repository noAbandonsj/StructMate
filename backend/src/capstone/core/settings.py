from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from capstone.core.model_config import ModelConnection

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAPSTONE_",
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    serve_frontend: bool = False
    data_dir: Path = REPOSITORY_ROOT / "data"
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    session_days: int = Field(default=7, ge=1, le=30)
    upload_max_mib: int = Field(default=20, ge=1, le=100)
    document_max_chars: int = Field(default=500_000, ge=1000, le=2_000_000)
    pdf_max_pages: int = Field(default=300, ge=1, le=1000)
    chunk_chars: int = Field(default=1200, ge=300, le=4000)
    retrieval_min_score: float = Field(default=0.25, ge=-1, le=1)
    chat_retrieval_timeout_seconds: float = Field(default=3, gt=0, le=30, allow_inf_nan=False)
    generation_base_url: str | None = Field(default=None, repr=False)
    generation_model: str | None = None
    generation_api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    generation_timeout_seconds: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)
    embedding_base_url: str | None = Field(default=None, repr=False)
    embedding_model: str | None = None
    embedding_api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    embedding_timeout_seconds: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)
    embedding_dimension: int | None = Field(default=None, ge=1, le=65536)

    @field_validator(
        "generation_base_url",
        "generation_model",
        "generation_api_key",
        "embedding_base_url",
        "embedding_model",
        "embedding_api_key",
        "embedding_dimension",
        mode="before",
    )
    @classmethod
    def normalize_optional(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    def connection(self, kind: Literal["generation", "embedding"]) -> ModelConnection | None:
        base_url = getattr(self, kind + "_base_url")
        model = getattr(self, kind + "_model")
        api_key = getattr(self, kind + "_api_key")
        if not base_url and not model and api_key is None:
            return None
        if not base_url or not model:
            raise ValueError(f"{kind} 模型地址和模型标识须同时填写；不使用时请清空该组连接参数")
        return ModelConnection(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=getattr(self, kind + "_timeout_seconds"),
            expected_dimension=self.embedding_dimension if kind == "embedding" else None,
        )

    @model_validator(mode="after")
    def validate_model_connections(self) -> Self:
        self.connection("generation")
        self.connection("embedding")
        return self

    @model_validator(mode="after")
    def resolve_data_directory(self) -> Self:
        if not self.data_dir.is_absolute():
            self.data_dir = REPOSITORY_ROOT / self.data_dir
        self.data_dir = self.data_dir.resolve()
        return self

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "capstone.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def qdrant_dir(self) -> Path:
        return self.data_dir / "qdrant"
