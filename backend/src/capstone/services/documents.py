from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from capstone.core.auth import check_admin
from capstone.core.errors import ApiError
from capstone.core.knowledge import readable_bases
from capstone.db.models import (
    CourseMaintenance,
    Document,
    DocumentTask,
    KnowledgeBase,
    KnowledgePoint,
    utc_now,
)
from capstone.db.session import write_transaction
from capstone.services.storage import BlobStore, validate_upload


def get_document(session: Session, document_id: UUID, user_id: UUID) -> Document:
    document = session.scalar(
        select(Document)
        .join(KnowledgeBase)
        .where(Document.id == document_id, readable_bases(user_id))
    )
    if document is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "资料不存在或不可访问。")
    return document


def writable_document(session: Session, document_id: UUID, user_id: UUID) -> Document:
    document = get_document(session, document_id, user_id)
    library = session.get(KnowledgeBase, document.knowledge_base_id)
    if library.kind != "personal" or library.owner_id != user_id:
        raise ApiError(403, "COURSE_READONLY", "课程资料为只读，不能修改。")
    return document


def course_document(session: Session, document_id: UUID, user_id: UUID) -> Document:
    check_admin(session, user_id)
    document = session.scalar(
        select(Document)
        .join(KnowledgeBase)
        .where(Document.id == document_id, KnowledgeBase.kind == "course")
    )
    if document is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "课程资料不存在。")
    return document


def record_maintenance(
    session: Session, document_id: UUID, actor_id: UUID | None, action: str
) -> None:
    if actor_id is not None:
        session.add(CourseMaintenance(document_id=document_id, actor_id=actor_id, action=action))


def create_document(
    session: Session,
    store: BlobStore,
    library_id: UUID,
    filename: str,
    data: bytes,
    maximum: int,
    knowledge_point_id: UUID | None = None,
    source_info: dict | None = None,
    *,
    course_actor_id: UUID | None = None,
    preserve_course_removals: bool = False,
) -> tuple[Document, bool]:
    name, kind = validate_upload(filename, data, maximum)
    digest = sha256(data).hexdigest()
    existing = session.scalar(
        select(Document).where(
            Document.knowledge_base_id == library_id, Document.dedup_key == digest
        )
    )
    if existing is not None:
        return existing, False
    if knowledge_point_id is not None and session.get(KnowledgePoint, knowledge_point_id) is None:
        raise ApiError(422, "KNOWLEDGE_POINT_INVALID", "所选知识点不存在，请重新选择。")
    session.rollback()
    document_id = uuid4()
    key = store.save(document_id, kind, data)
    try:
        with write_transaction(session):
            if preserve_course_removals and source_info and source_info.get("content_code"):
                code = source_info["content_code"]
                matches = session.scalars(
                    select(Document).where(
                        Document.knowledge_base_id == library_id,
                        Document.source_info["content_code"].as_string() == code,
                    )
                ).all()
                if any(row.status == "deleted" for row in matches) and not any(
                    row.status != "deleted" for row in matches
                ):
                    raise ApiError(409, "COURSE_REMOVED", "此预置资料已移除，请显式恢复。")
            if course_actor_id is not None:
                check_admin(session, course_actor_id)
                if (
                    session.scalar(select(KnowledgeBase.kind).where(KnowledgeBase.id == library_id))
                    != "course"
                ):
                    raise ApiError(404, "LIBRARY_NOT_FOUND", "课程知识库不存在。")
            document = Document(
                id=document_id,
                knowledge_base_id=library_id,
                filename=name,
                file_type=kind,
                storage_key=key,
                size_bytes=len(data),
                content_hash=digest,
                dedup_key=digest,
                index_revision=1,
                status="processing",
                stage="queued",
                knowledge_point_id=knowledge_point_id,
                source_info=source_info,
            )
            session.add(document)
            session.flush()
            record_maintenance(session, document_id, course_actor_id, "upload")
            session.add(
                DocumentTask(
                    document_id=document_id,
                    request_id="initial",
                    index_revision=1,
                    action="process",
                )
            )
    except IntegrityError:
        store.remove(key)
        existing = session.scalar(
            select(Document).where(
                Document.knowledge_base_id == library_id, Document.dedup_key == digest
            )
        )
        if existing is not None:
            return existing, False
        raise ApiError(503, "UPLOAD_FAILED", "资料保存失败，请稍后重试。") from None
    except Exception:
        store.remove(key)
        raise
    return document, True


def queue_process(
    session: Session,
    document_id: UUID,
    user_id: UUID,
    request_id: str,
    *,
    embedding_available: bool = True,
    course_admin: bool = False,
) -> Document:
    authorize = course_document if course_admin else writable_document
    document = authorize(session, document_id, user_id)
    previous = session.scalar(
        select(DocumentTask).where(
            DocumentTask.document_id == document_id, DocumentTask.request_id == request_id
        )
    )
    if previous is not None:
        if previous.action != "process":
            raise ApiError(409, "REQUEST_CONFLICT", "请求标识已用于另一项操作。")
        return document
    if document.status == "deleted":
        raise ApiError(410, "DOCUMENT_DELETED", "资料已删除，请重新上传。")
    if document.status == "processing":
        raise ApiError(409, "DOCUMENT_BUSY", "资料正在处理，请等待完成。")
    if not embedding_available:
        raise ApiError(503, "EMBEDDING_NOT_CONFIGURED", "向量服务尚未接通，配置后可重试。")
    session.rollback()
    with write_transaction(session):
        document = authorize(session, document_id, user_id)
        previous = session.scalar(
            select(DocumentTask).where(
                DocumentTask.document_id == document_id, DocumentTask.request_id == request_id
            )
        )
        if previous is not None:
            if previous.action != "process":
                raise ApiError(409, "REQUEST_CONFLICT", "请求标识已用于另一项操作。")
            return document
        if document.status == "processing":
            raise ApiError(409, "DOCUMENT_BUSY", "资料正在处理，请等待完成。")
        if document.status == "deleted":
            raise ApiError(410, "DOCUMENT_DELETED", "资料已删除，请重新上传。")
        revision = document.index_revision + 1
        document.index_revision = revision
        document.status, document.stage = "processing", "queued"
        document.error_code = document.error_message = None
        record_maintenance(session, document_id, user_id if course_admin else None, "process")
        session.add(
            DocumentTask(
                document_id=document_id,
                request_id=request_id,
                index_revision=revision,
                action="process",
            )
        )
    return document


def queue_delete(
    session: Session, document_id: UUID, user_id: UUID, *, course_admin: bool = False
) -> Document:
    authorize = course_document if course_admin else writable_document
    document = authorize(session, document_id, user_id)
    if document.status == "deleted":
        document_id = document.id
        session.rollback()
        with write_transaction(session):
            document = authorize(session, document_id, user_id)
            task = session.scalar(
                select(DocumentTask).where(
                    DocumentTask.document_id == document_id, DocumentTask.action == "delete"
                )
            )
            if task is not None and task.status == "failed":
                task.status, task.attempt_count = "queued", 0
                task.error_code = task.error_message = None
                document.stage = "cleaning"
                document.error_code = document.error_message = None
                record_maintenance(
                    session, document_id, user_id if course_admin else None, "delete"
                )
        return document
    session.rollback()
    with write_transaction(session):
        document = authorize(session, document_id, user_id)
        if document.status == "deleted":
            return document
        document.status, document.stage = "deleted", "cleaning"
        document.deleted_at = utc_now()
        document.dedup_key = None
        document.error_code = document.error_message = None
        record_maintenance(session, document_id, user_id if course_admin else None, "delete")
        session.add(
            DocumentTask(
                document_id=document_id,
                request_id="delete",
                index_revision=document.index_revision,
                action="delete",
            )
        )
    return document
