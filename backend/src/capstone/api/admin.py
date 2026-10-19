"""Course-only administrative entry points; personal write rules remain unchanged."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, or_, select
from starlette.datastructures import UploadFile

from capstone.api.documents import (
    ChunkInfo,
    DocumentInfo,
    ProcessInput,
    UploadResponse,
    document_chunks,
    document_file,
    info,
)
from capstone.api.knowledge import PageNumber, PageSize
from capstone.api.schemas import Page
from capstone.core.auth import (
    Administrator,
    DatabaseSession,
    no_store,
    require_csrf,
    require_origin,
)
from capstone.core.errors import ApiError
from capstone.db.models import CourseMaintenance, Document, KnowledgeBase, User
from capstone.seed import COURSE_CODE
from capstone.services.documents import (
    course_document,
    create_document,
    queue_delete,
    queue_process,
)

router = APIRouter(
    prefix="/admin/course", tags=["course administration"], dependencies=[Depends(no_store)]
)


def course_library(session: DatabaseSession) -> UUID:
    library_id = session.scalar(
        select(KnowledgeBase.id).where(
            KnowledgeBase.kind == "course", KnowledgeBase.course_code == COURSE_CODE
        )
    )
    if library_id is None:
        raise ApiError(409, "COURSE_NOT_INITIALIZED", "请先由本机维护者初始化课程目录。")
    return library_id


@router.get("/documents", response_model=Page[DocumentInfo])
def list_course_documents(
    current: Administrator,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    search: str = Query(default="", max_length=240),
    status: Literal["processing", "ready", "failed", "deleted"] | None = None,
) -> Page[DocumentInfo]:
    predicate = Document.knowledge_base_id == course_library(session)
    predicate &= (
        (Document.status == status)
        if status
        else or_(Document.status != "deleted", Document.stage == "cleanup_failed")
    )
    if search.strip():
        predicate &= Document.filename.contains(search.strip(), autoescape=True)
    total = session.scalar(select(func.count()).select_from(Document).where(predicate))
    documents = session.scalars(
        select(Document)
        .where(predicate)
        .order_by(Document.updated_at.desc(), Document.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page(
        items=[info(document) for document in documents],
        page=page,
        page_size=page_size,
        total=total,
    )


class Attribution(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    author: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=1000)
    license: str = Field(min_length=1, max_length=1000)
    knowledge_point_id: UUID


@router.post(
    "/documents",
    response_model=UploadResponse,
    status_code=202,
    dependencies=[Depends(require_origin)],
)
async def upload_course_document(
    request: Request, current: Administrator, session: DatabaseSession
) -> UploadResponse:
    require_csrf(request, current)
    library_id = course_library(session)
    session.rollback()
    async with request.form(max_files=1, max_fields=4) as form:
        if set(form.keys()) - {"file", "knowledge_point_id", "author", "source", "license"} or any(
            len(form.getlist(key)) != 1 for key in form
        ):
            raise ApiError(422, "UPLOAD_FIELDS_INVALID", "上传包含不支持或重复的字段。")
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise ApiError(422, "FILE_REQUIRED", "请选择要上传的课程资料。")
        try:
            attribution = Attribution.model_validate(
                {key: value for key, value in form.items() if key != "file"}
            )
        except ValidationError:
            raise ApiError(
                422,
                "ATTRIBUTION_REQUIRED",
                "请选择知识点，并填写作者、来源和许可说明。自编资料可注明自编。",
            ) from None
        maximum = request.app.state.settings.upload_max_mib * 1024 * 1024
        data = await file.read(maximum + 1)
        document, created = create_document(
            session,
            request.app.state.blob_store,
            library_id,
            file.filename,
            data,
            maximum,
            attribution.knowledge_point_id,
            source_info={
                "sources": [
                    {
                        "title": attribution.source,
                        "author": attribution.author,
                        "license": attribution.license,
                        "url": attribution.source
                        if attribution.source.startswith(("https://", "http://"))
                        else "",
                    }
                ]
            },
            course_actor_id=current.user_id,
        )
        result = UploadResponse(document=info(document), duplicate=not created)
    if created:
        request.app.state.document_worker.notify()
    return result


@router.get("/documents/{document_id}", response_model=DocumentInfo)
def course_detail(
    document_id: UUID, current: Administrator, session: DatabaseSession
) -> DocumentInfo:
    return info(course_document(session, document_id, current.user_id))


@router.get("/documents/{document_id}/file")
def course_file(
    document_id: UUID,
    request: Request,
    current: Administrator,
    session: DatabaseSession,
    download: bool = False,
):
    course_document(session, document_id, current.user_id)
    return document_file(document_id, request, current, session, download)


@router.get("/documents/{document_id}/chunks", response_model=Page[ChunkInfo])
def course_chunks(
    document_id: UUID,
    current: Administrator,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
):
    course_document(session, document_id, current.user_id)
    return document_chunks(document_id, current, session, page, page_size)


class MaintenanceInfo(BaseModel):
    action: str
    actor: str
    created_at: datetime


@router.get("/documents/{document_id}/history", response_model=list[MaintenanceInfo])
def course_history(document_id: UUID, current: Administrator, session: DatabaseSession):
    course_document(session, document_id, current.user_id)
    rows = session.execute(
        select(CourseMaintenance, User.username)
        .join(User, User.id == CourseMaintenance.actor_id)
        .where(CourseMaintenance.document_id == document_id)
        .order_by(CourseMaintenance.created_at.desc())
    )
    return [
        MaintenanceInfo(action=event.action, actor=actor, created_at=event.created_at)
        for event, actor in rows
    ]


@router.post(
    "/documents/{document_id}/process",
    response_model=DocumentInfo,
    status_code=202,
    dependencies=[Depends(require_origin)],
)
def process_course(
    document_id: UUID,
    data: ProcessInput,
    request: Request,
    current: Administrator,
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
            course_admin=True,
        )
    )
    request.app.state.document_worker.notify()
    return result


@router.delete(
    "/documents/{document_id}",
    response_model=DocumentInfo,
    status_code=202,
    dependencies=[Depends(require_origin)],
)
def delete_course(
    document_id: UUID, request: Request, current: Administrator, session: DatabaseSession
) -> DocumentInfo:
    require_csrf(request, current)
    result = info(queue_delete(session, document_id, current.user_id, course_admin=True))
    request.app.state.document_worker.notify()
    return result
