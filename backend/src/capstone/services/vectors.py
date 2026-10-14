import json
from pathlib import Path
from threading import RLock
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from capstone.core.errors import ApiError
from capstone.core.model_ports import EmbeddingBatch
from capstone.db.models import DocumentChunk

COLLECTION = "capstone_chunks"


class VectorIndex:
    def __init__(self, client: QdrantClient, data_directory: Path):
        self.client = client
        self.metadata_path = data_directory / "index-config.json"
        self.lock = RLock()

    def _ensure(self, batch: EmbeddingBatch, dimension: int) -> None:
        expected = {"dimension": dimension, "fingerprint": batch.fingerprint}
        if self.client.collection_exists(COLLECTION):
            try:
                stored = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                stored = None
            actual = self.client.get_collection(COLLECTION).config.params.vectors
            if (
                stored != expected
                or not isinstance(actual, VectorParams)
                or actual.size != dimension
            ):
                raise ApiError(
                    503,
                    "INDEX_REBUILD_REQUIRED",
                    "向量配置与现有索引不一致，请先由维护者停机重建索引。",
                )
            return
        temporary = self.metadata_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(expected), encoding="utf-8")
        temporary.replace(self.metadata_path)
        self.client.create_collection(
            COLLECTION, vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
        )

    def replace_document(
        self,
        document_id: UUID,
        library_id: UUID,
        owner_id: UUID | None,
        chunks: list[DocumentChunk],
        batch: EmbeddingBatch,
    ) -> int:
        dimension = batch.validate(len(chunks))
        with self.lock:
            self._ensure(batch, dimension)
            self.remove_document(document_id)
            points = [
                PointStruct(
                    id=str(chunk.id),
                    vector=vector,
                    payload={
                        "document_id": str(document_id),
                        "knowledge_base_id": str(library_id),
                        "owner_id": str(owner_id) if owner_id is not None else None,
                        "index_revision": chunk.index_revision,
                        "chunk_id": str(chunk.id),
                        "embedding_fingerprint": batch.fingerprint,
                    },
                )
                for chunk, vector in zip(chunks, batch.vectors, strict=True)
            ]
            self.client.upsert(COLLECTION, points=points, wait=True)
        return dimension

    def remove_document(self, document_id: UUID) -> None:
        with self.lock:
            if self.client.collection_exists(COLLECTION):
                self.client.delete(
                    COLLECTION,
                    points_selector=FilterSelector(
                        filter=Filter(
                            must=[
                                FieldCondition(
                                    key="document_id", match=MatchValue(value=str(document_id))
                                )
                            ]
                        )
                    ),
                    wait=True,
                )
