from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import func, select
from starlette.datastructures import UploadFile
from starlette.responses import FileResponse, PlainTextResponse, Response

from capstone.api.knowledge import PageNumber, PageSize
from capstone.api.schemas import Page
from capstone.core.auth import (
    AuthenticatedSession,
    DatabaseSession,
    no_store,
    require_csrf,
    require_origin,
)
from capstone.core.errors import ApiError
from capstone.core.knowledge import get_readable_base
from capstone.db.models import Document, DocumentChunk
from capstone.services.documents import create_document, get_document, queue_delete, queue_process
from capstone.services.parsing import decode_text

router = APIRouter(tags=["documents"], dependencies=[Depends(no_store)])
write_dependencies = [Depends(require_origin)]


class DocumentInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    knowledge_base_id: UUID
    knowledge_point_id: UUID | None
    filename: str
    file_type: Literal["pdf", "txt", "md"]
    size_bytes: int
    status: Literal["processing", "ready", "failed", "deleted"]
    stage: str
    error_code: str | None
    error_message: str | None
    source_info: dict | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def retryable(self) -> bool:
        if self.status == "deleted":
            return self.stage == "cleanup_failed"
        return self.status == "failed" and self.error_code not in {
            "NO_TEXT",
            "PDF_INVALID",
            "PDF_ENCRYPTED",
            "PDF_TOO_LONG",
            "TEXT_INVALID",
            "DOCUMENT_TOO_LONG",
            "TOO_MANY_CHUNKS",
            "INDEX_REBUILD_REQUIRED",
            "FILE_MISSING",
            "FILE_UNAVAILABLE",
        }


class UploadResponse(BaseModel):
    document: DocumentInfo
    duplicate: bool


class ProcessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class ChunkInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    text: str
    page_number: int | None
    heading: str | None
    line_start: int | None
    line_end: int | None
    knowledge_point_id: UUID | None


def info(document: Document) -> DocumentInfo:
    return DocumentInfo.model_validate(document)


@router.get("/documents/upload-config")
def upload_config(request: Request, current: AuthenticatedSession) -> dict:
    return {
        "max_mib": request.app.state.settings.upload_max_mib,
        "extensions": ["pdf", "txt", "md", "markdown"],
        "embedding_available": request.app.state.embedding_service.available,
    }


@router.get("/knowledge-bases/{library_id}/documents", response_model=Page[DocumentInfo])
def list_documents(
    library_id: UUID,
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[DocumentInfo]:
    get_readable_base(session, library_id, current.user_id)
    predicate = (Document.knowledge_base_id == library_id) & (Document.status != "deleted")
    total = session.scalar(select(func.count()).select_from(Document).where(predicate))
    documents = session.scalars(
        select(Document)
        .where(predicate)
        .order_by(Document.created_at.desc(), Document.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[info(document) for document in documents],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/knowledge-bases/{library_id}/documents",
    status_code=202,
    response_model=UploadResponse,
    dependencies=write_dependencies,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "knowledge_point_id": {"type": "string", "format": "uuid"},
                        },
                    },
                }
            },
        }
    },
)
async def upload_document(
    library_id: UUID,
    request: Request,
    current: AuthenticatedSession,
    session: DatabaseSession,
) -> UploadResponse:
    require_csrf(request, current)
    library = get_readable_base(session, library_id, current.user_id)
    if library.kind != "personal" or library.owner_id != current.user_id:
        raise ApiError(403, "COURSE_READONLY", "只能向自己的个人知识库上传资料。")
    session.rollback()
    async with request.form(max_files=1, max_fields=1) as form:
        if set(form.keys()) - {"file", "knowledge_point_id"}:
            raise ApiError(422, "UPLOAD_FIELDS_INVALID", "上传包含不支持的字段。")
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise ApiError(422, "FILE_REQUIRED", "请选择要上传的资料。")
        point = form.get("knowledge_point_id")
        try:
            point_id = UUID(point) if isinstance(point, str) and point else None
        except ValueError:
            raise ApiError(422, "KNOWLEDGE_POINT_INVALID", "所选知识点无效。") from None
        maximum = request.app.state.settings.upload_max_mib * 1024 * 1024
        data = await file.read(maximum + 1)
        document, created = create_document(
            session,
            request.app.state.blob_store,
            library_id,
            file.filename,
            data,
            maximum,
            point_id,
        )
        result = UploadResponse(document=info(document), duplicate=not created)
    if created:
        request.app.state.document_worker.notify()
    return result


@router.get("/documents/{document_id}", response_model=DocumentInfo)
def document_detail(
    document_id: UUID,
    current: AuthenticatedSession,
    session: DatabaseSession,
) -> DocumentInfo:
    return info(get_document(session, document_id, current.user_id))


@router.get("/documents/{document_id}/file")
def document_file(
    document_id: UUID,
    request: Request,
    current: AuthenticatedSession,
    session: DatabaseSession,
    download: bool = False,
) -> Response:
    document = get_document(session, document_id, current.user_id)
    if document.status == "deleted":
        raise ApiError(410, "DOCUMENT_DELETED", "资料已删除，原文件不再提供。")
    path = request.app.state.blob_store.path(document.storage_key)
    if not path.is_file():
        raise ApiError(404, "FILE_MISSING", "原文件暂不可用，请重新上传或联系维护者。")
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if not download and document.file_type != "pdf":
        return PlainTextResponse(decode_text(path.read_bytes()), headers=headers)
    return FileResponse(
        path,
        media_type="application/octet-stream" if download else "application/pdf",
        filename=document.filename,
        content_disposition_type="attachment" if download else "inline",
        headers=headers,
    )


@router.get("/documents/{document_id}/chunks", response_model=Page[ChunkInfo])
def document_chunks(
    document_id: UUID,
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[ChunkInfo]:
    document = get_document(session, document_id, current.user_id)
    if document.status == "deleted":
        raise ApiError(410, "DOCUMENT_DELETED", "资料已删除，原片段不再提供。")
    if document.status != "ready":
        raise ApiError(409, "DOCUMENT_NOT_READY", "资料尚未处理完成，暂不能用于学习。")
    predicate = (DocumentChunk.document_id == document_id) & (
        DocumentChunk.index_revision == document.index_revision
    )
    total = session.scalar(select(func.count()).select_from(DocumentChunk).where(predicate))
    chunks = session.scalars(
        select(DocumentChunk)
        .where(predicate)
        .order_by(DocumentChunk.position)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[ChunkInfo.model_validate(chunk) for chunk in chunks],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/documents/{document_id}/process",
    status_code=202,
    response_model=DocumentInfo,
    dependencies=write_dependencies,
)
def process_document(
    document_id: UUID,
    data: ProcessInput,
    request: Request,
    current: AuthenticatedSession,
    session: DatabaseSession,
) -> DocumentInfo:
    require_csrf(request, current)
    result = info(
        queue_process(
            session,
            document_id,
            current.user_id,
            data.client_request_id,
            embedding_available=request.app.state.embedding_service.available,
        )
    )
    request.app.state.document_worker.notify()
    return result


@router.delete(
    "/documents/{document_id}",
    status_code=202,
    response_model=DocumentInfo,
    dependencies=write_dependencies,
)
def delete_document(
    document_id: UUID,
    request: Request,
    current: AuthenticatedSession,
    session: DatabaseSession,
) -> DocumentInfo:
    require_csrf(request, current)
    result = info(queue_delete(session, document_id, current.user_id))
    request.app.state.document_worker.notify()
    return result
