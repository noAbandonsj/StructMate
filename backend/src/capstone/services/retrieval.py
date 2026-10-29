from uuid import UUID

from sqlalchemy import select

from capstone.core.errors import ApiError
from capstone.core.knowledge import readable_bases
from capstone.db.models import Document, DocumentChunk, KnowledgeBase
from capstone.services.citation_grounding import has_evidence


def document_predicate(user_id: UUID, scope: str, document_ids: list[str]):
    predicates = [readable_bases(user_id), Document.status == "ready"]
    if scope != "combined":
        predicates.append(KnowledgeBase.kind == ("course" if scope == "course" else "personal"))
    if document_ids:
        predicates.append(Document.id.in_([UUID(str(identifier)) for identifier in document_ids]))
    return predicates


def document_excerpts(factory, user_id, document_ids):
    """Read bounded current excerpts from each explicitly selected ready document."""
    result = []
    with factory() as session:
        for identifier in sorted(set(document_ids)):
            rows = session.execute(
                select(DocumentChunk, Document)
                .join(Document)
                .join(KnowledgeBase)
                .where(
                    *document_predicate(user_id, "combined", [identifier]),
                    DocumentChunk.index_revision == Document.index_revision,
                )
                .order_by(DocumentChunk.position)
                .limit(3)
            ).all()
            for chunk, document in rows:
                result.append(citation_info(chunk, document, len(result) + 1))
    return result


def citation_info(chunk, document, number):
    return {
        "number": number,
        "document_id": str(document.id),
        "chunk_id": str(chunk.id),
        "filename": document.filename,
        "chapter_id": str(chunk.chapter_id) if chunk.chapter_id else None,
        "page_number": chunk.page_number,
        "heading": chunk.heading,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "text": chunk.text[:3000],
        "source_info": document.source_info,
    }


def retrieve(factory, embedding, vectors, settings, user_id, scope, document_ids, query):
    predicates = document_predicate(user_id, scope, document_ids)
    with factory() as session:
        documents = session.execute(
            select(
                Document.id,
                Document.index_revision,
                Document.embedding_fingerprint,
                Document.embedding_dimension,
            )
            .join(KnowledgeBase)
            .where(*predicates)
        ).all()
    if not documents:
        return []
    batch = embedding.embed([query])
    dimension = batch.validate(1)
    if any(
        row.embedding_fingerprint != batch.fingerprint or row.embedding_dimension != dimension
        for row in documents
    ):
        raise ApiError(
            503, "INDEX_REBUILD_REQUIRED", "模型配置与资料索引不一致，请联系维护者重建。"
        )
    hits = vectors.search(
        batch, [(row.id, row.index_revision) for row in documents], settings.retrieval_min_score
    )
    result, seen = [], set()
    # A deletion/reprocess may race the external query. Check current SQL facts again.
    with factory() as session:
        for hit in hits:
            payload = hit.payload or {}
            try:
                chunk_id = UUID(payload["chunk_id"])
            except (KeyError, ValueError, TypeError):
                continue
            row = session.execute(
                select(DocumentChunk, Document)
                .join(Document)
                .join(KnowledgeBase)
                .where(
                    DocumentChunk.id == chunk_id,
                    DocumentChunk.index_revision == Document.index_revision,
                    Document.embedding_fingerprint == batch.fingerprint,
                    *predicates,
                )
            ).first()
            if row is None:
                continue
            chunk, document = row
            if (
                payload.get("document_id") != str(document.id)
                or payload.get("index_revision") != document.index_revision
                or chunk.id in seen
                or not has_evidence(chunk.text)
            ):
                continue
            seen.add(chunk.id)
            result.append(citation_info(chunk, document, len(result) + 1))
            if len(result) == 6:
                break
    return result
