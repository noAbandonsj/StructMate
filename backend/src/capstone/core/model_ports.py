import re
from collections.abc import Iterator
from dataclasses import dataclass
from math import isfinite
from threading import Event
from typing import Protocol

from capstone.core.errors import ApiError


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    fingerprint: str

    def validate(self, expected_count: int) -> int:
        dimension = len(self.vectors[0]) if self.vectors else 0
        valid = (
            len(self.vectors) == expected_count
            and dimension > 0
            and re.fullmatch(r"[0-9a-f]{64}", self.fingerprint) is not None
            and all(
                len(vector) == dimension
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and isfinite(value)
                    for value in vector
                )
                and any(value != 0 for value in vector)
                for vector in self.vectors
            )
        )
        if not valid:
            raise ApiError(503, "EMBEDDING_INVALID", "向量服务返回的数据格式不正确，请检查配置。")
        return dimension


class EmbeddingService(Protocol):
    available: bool

    def embed(self, texts: list[str]) -> EmbeddingBatch: ...


class UnconfiguredEmbedding:
    available = False

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        raise ApiError(
            503,
            "EMBEDDING_NOT_CONFIGURED",
            "向量模型尚未接通，文件已保留；配置服务后可重试。",
        )


class GenerationService(Protocol):
    available: bool

    def stream(self, messages: list[dict[str, str]], cancelled: Event) -> Iterator[str]: ...


class UnconfiguredGeneration:
    available = False

    def stream(self, messages: list[dict[str, str]], cancelled: Event) -> Iterator[str]:
        raise ApiError(503, "GENERATION_NOT_CONFIGURED", "生成模型尚未接通，请配置后重试。")
