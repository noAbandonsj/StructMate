from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAPSTONE_",
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    data_dir: Path = REPOSITORY_ROOT / "data"
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    session_days: int = Field(default=7, ge=1, le=30)
    upload_max_mib: int = Field(default=20, ge=1, le=100)
    document_max_chars: int = Field(default=500_000, ge=1000, le=2_000_000)
    pdf_max_pages: int = Field(default=300, ge=1, le=1000)
    chunk_chars: int = Field(default=1200, ge=300, le=4000)
    retrieval_min_score: float = Field(default=0.25, ge=-1, le=1)

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
