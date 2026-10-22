from dataclasses import dataclass
from threading import Event, Thread
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from capstone.core.errors import ApiError
from capstone.core.model_ports import EmbeddingBatch, EmbeddingService
from capstone.core.settings import Settings
from capstone.db.models import Document, DocumentChunk, DocumentTask, KnowledgeBase
from capstone.db.session import write_transaction
from capstone.services.parsing import parse_file, split_fragments
from capstone.services.storage import BlobStore
from capstone.services.vectors import VectorIndex


@dataclass(frozen=True)
class Work:
    task_id: UUID
    document_id: UUID
    revision: int
    action: str
    storage_key: str
    file_type: str
    library_id: UUID
    owner_id: UUID | None
    point_id: UUID | None


class Superseded(Exception):
    pass


class DocumentWorker:
    def __init__(
        self,
        factory: sessionmaker,
        settings: Settings,
        embedding: EmbeddingService,
        vectors: VectorIndex,
        store: BlobStore,
    ):
        self.factory, self.settings = factory, settings
        self.embedding, self.vectors, self.store = embedding, vectors, store
        self.wakeup, self.stopping = Event(), Event()
        self.thread = Thread(target=self._run, name="document-processing", daemon=True)

    def start(self) -> None:
        with self.factory() as session, write_transaction(session):
            tasks = session.scalars(
                select(DocumentTask).where(
                    (DocumentTask.status == "running")
                    | ((DocumentTask.status == "failed") & (DocumentTask.action == "delete"))
                )
            ).all()
            for task in tasks:
                document = session.get(Document, task.document_id)
                if task.action == "delete":
                    task.status = "queued"
                    task.attempt_count = 0
                    document.stage = "cleaning"
                    document.error_code = document.error_message = None
                    continue
                task.status = "failed"
                task.error_code, task.error_message = (
                    "PROCESS_INTERRUPTED",
                    "上次处理被中断，可重试。",
                )
                if (
                    document.index_revision == task.index_revision
                    and document.status == "processing"
                ):
                    document.status, document.stage = "failed", "interrupted"
                    document.error_code, document.error_message = (
                        task.error_code,
                        task.error_message,
                    )
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self.wakeup.set()
        self.thread.join()

    def notify(self) -> None:
        self.wakeup.set()

    def _claim(self) -> Work | None:
        with self.factory() as session, write_transaction(session):
            task = session.scalar(
                select(DocumentTask)
                .where(DocumentTask.status == "queued")
                .order_by(DocumentTask.created_at, DocumentTask.id)
                .limit(1)
            )
            if task is None:
                return None
            document = session.get(Document, task.document_id)
            library = session.get(KnowledgeBase, document.knowledge_base_id)
            task.status = "running"
            task.attempt_count += 1
            return Work(
                task.id,
                document.id,
                task.index_revision,
                task.action,
                document.storage_key,
                document.file_type,
                library.id,
                library.owner_id,
                document.chapter_id,
            )

    def _live(self, session, work: Work) -> Document:
        document = session.get(Document, work.document_id)
        if self.stopping.is_set() or (
            work.action == "process"
            and (document.status != "processing" or document.index_revision != work.revision)
        ):
            raise Superseded
        return document

    def _stage(self, work: Work, stage: str) -> None:
        with self.factory() as session, write_transaction(session):
            self._live(session, work).stage = stage

    def _process(self, work: Work) -> None:
        self._stage(work, "extracting")
        path = self.store.path(work.storage_key)
        if not path.is_file():
            raise ApiError(422, "FILE_MISSING", "原文件不存在，请删除此记录后重新上传。")
        fragments = parse_file(path, work.file_type, self.settings)
        self._stage(work, "chunking")
        fragments = split_fragments(fragments, self.settings.chunk_chars)
        if len(fragments) > 2000:
            raise ApiError(422, "TOO_MANY_CHUNKS", "资料片段过多，请拆分文件。")
        chunks = [
            DocumentChunk(
                id=uuid5(NAMESPACE_URL, f"{work.document_id}:{work.revision}:{position}"),
                document_id=work.document_id,
                index_revision=work.revision,
                position=position,
                text=fragment.text,
                page_number=fragment.page_number,
                heading=fragment.heading,
                line_start=fragment.line_start,
                line_end=fragment.line_end,
                chapter_id=work.point_id,
            )
            for position, fragment in enumerate(fragments)
        ]
        with self.factory() as session, write_transaction(session):
            self._live(session, work)
            session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.document_id == work.document_id,
                    DocumentChunk.index_revision == work.revision,
                )
            )
            session.add_all(chunks)
            session.flush()
            session.expunge_all()
        self._stage(work, "embedding")
        vectors, fingerprint, dimension = [], None, None
        for start in range(0, len(chunks), 16):
            self._stage(work, "embedding")
            batch = self.embedding.embed([chunk.text for chunk in chunks[start : start + 16]])
            current_dimension = batch.validate(len(chunks[start : start + 16]))
            if fingerprint is not None and (
                fingerprint != batch.fingerprint or dimension != current_dimension
            ):
                raise ApiError(503, "EMBEDDING_CHANGED", "处理期间向量配置发生变化，请重试。")
            fingerprint, dimension = batch.fingerprint, current_dimension
            vectors.extend(batch.vectors)
        self._stage(work, "indexing")
        self.vectors.replace_document(
            work.document_id,
            work.library_id,
            work.owner_id,
            chunks,
            EmbeddingBatch(vectors, fingerprint),
        )
        with self.factory() as session, write_transaction(session):
            document = self._live(session, work)
            document.status, document.stage = "ready", "complete"
            document.embedding_fingerprint, document.embedding_dimension = fingerprint, dimension
            document.error_code = document.error_message = None
            session.get(DocumentTask, work.task_id).status = "completed"

    def _delete(self, work: Work) -> None:
        self.vectors.remove_document(work.document_id)
        self.store.remove(work.storage_key)
        with self.factory() as session, write_transaction(session):
            document = session.get(Document, work.document_id)
            document.stage = "complete"
            document.error_code = document.error_message = None
            session.get(DocumentTask, work.task_id).status = "completed"

    def _fail(self, work: Work, code: str, message: str) -> None:
        with self.factory() as session, write_transaction(session):
            task = session.get(DocumentTask, work.task_id)
            task.status, task.error_code, task.error_message = "failed", code, message
            document = session.get(Document, work.document_id)
            if work.action == "delete" and task.attempt_count < 3:
                task.status = "queued"
                return
            if document.index_revision == work.revision and (
                document.status == "processing" or work.action == "delete"
            ):
                if work.action == "process":
                    document.status = "failed"
                else:
                    document.stage = "cleanup_failed"
                document.error_code, document.error_message = code, message

    def _record_failure(self, work: Work, code: str, message: str) -> None:
        # Retry only the failure-status write; never replay a model call here.
        for _attempt in range(3):
            try:
                self._fail(work, code, message)
                return
            except Exception:
                if self.stopping.wait(0.2):
                    return

    def _run(self) -> None:
        while not self.stopping.is_set():
            try:
                work = self._claim()
            except Exception:
                self.wakeup.wait(1)
                self.wakeup.clear()
                continue
            if work is None:
                self.wakeup.wait(1)
                self.wakeup.clear()
                continue
            try:
                self._delete(work) if work.action == "delete" else self._process(work)
            except Superseded:
                if not self.stopping.is_set():
                    self._record_failure(
                        work, "PROCESS_SUPERSEDED", "资料状态已变化，本次处理已停止。"
                    )
            except ApiError as error:
                self._record_failure(work, error.detail["code"], error.detail["message"])
            except Exception:
                code, message = (
                    ("CLEANUP_FAILED", "原文件或向量清理未完成，请稍后重试。")
                    if work.action == "delete"
                    else ("PROCESS_FAILED", "资料处理失败，请稍后重试。")
                )
                self._record_failure(work, code, message)
            if work.action == "delete":
                self.stopping.wait(0.3)
