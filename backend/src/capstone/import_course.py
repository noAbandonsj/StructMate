"""Register attributed public course files for the running document worker."""

import argparse
import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from capstone.core.errors import ApiError
from capstone.core.settings import Settings
from capstone.db.models import Document, DocumentTask, KnowledgeBase
from capstone.db.session import create_database_engine, write_transaction
from capstone.seed import COURSE_CODE
from capstone.services.chapters import chapters
from capstone.services.documents import create_document
from capstone.services.storage import BlobStore, validate_upload


def import_course_data(
    engine: Engine,
    settings: Settings,
    content_directory: Path,
    *,
    retry_failed: bool = False,
    restore_deleted: bool = False,
) -> tuple[int, int, int]:
    root = content_directory.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    sources = {
        item["id"]: item for item in json.loads((root / "sources.json").read_text(encoding="utf-8"))
    }
    store = BlobStore(settings.uploads_dir)
    added = skipped = retried = 0
    # Validate the complete packet before writing any course records.
    prepared = []
    for item in manifest:
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root) or path.suffix != ".md":
            raise ApiError(422, "COURSE_FILE_INVALID", "课程文件路径无效。")
        data = path.read_text(encoding="utf-8").encode("utf-8")
        validate_upload(item["title"] + ".md", data, settings.upload_max_mib * 1024 * 1024)
        if sha256(data).hexdigest() != item["sha256"]:
            raise ApiError(422, "COURSE_HASH_CHANGED", "课程文件已修改，请先重新核对摘要和来源。")
        references = [sources[source_id] for source_id in item["source_ids"]]
        if not references or any(not source.get("license") for source in references):
            raise ApiError(422, "COURSE_LICENSE_MISSING", "课程资料缺少来源许可说明。")
        prepared.append((item, data, references))
    with Session(engine) as session:
        library_id = session.scalar(
            select(KnowledgeBase.id).where(
                KnowledgeBase.course_code == COURSE_CODE,
                KnowledgeBase.kind == "course",
            )
        )
        if library_id is None:
            raise ApiError(409, "COURSE_NOT_INITIALIZED", "请先运行 capstone.seed 初始化课程目录。")
        point_ids = {chapter.code: chapter.id for chapter in chapters(session)}
        session.rollback()
        if any(item["chapter_code"] not in point_ids for item, _data, _references in prepared):
            raise ApiError(422, "COURSE_POINT_MISSING", "课程资料须关联一个内置章节。")
        for item, data, references in prepared:
            # A tombstone is scoped by stable content code, not by its hash:
            # even an updated preset must not silently undo a maintainer's deletion.
            tombstone = session.scalar(
                select(Document.id).where(
                    Document.knowledge_base_id == library_id,
                    Document.status == "deleted",
                    Document.source_info["content_code"].as_string() == item["code"],
                )
            )
            live = session.scalar(
                select(Document.id).where(
                    Document.knowledge_base_id == library_id,
                    Document.status != "deleted",
                    Document.source_info["content_code"].as_string() == item["code"],
                )
            )
            session.rollback()
            if tombstone is not None and live is None and not restore_deleted:
                skipped += 1
                continue
            chapter_code = item["chapter_code"]
            try:
                document, created = create_document(
                    session,
                    store,
                    library_id,
                    item["title"] + ".md",
                    data,
                    settings.upload_max_mib * 1024 * 1024,
                    point_ids[chapter_code],
                    source_info={
                        "content_code": item["code"],
                        "title": item["title"],
                        "adaptation": item["adaptation"],
                        "sources": references,
                    },
                    preserve_course_removals=not restore_deleted,
                )
            except ApiError as error:
                if error.detail["code"] != "COURSE_REMOVED":
                    raise
                skipped += 1
                continue
            added += int(created)
            skipped += int(not created)
            document_id = document.id
            session.rollback()
            if retry_failed and not created:
                with write_transaction(session):
                    document = session.get(Document, document_id)
                    if document.knowledge_base_id == library_id and document.status == "failed":
                        document.index_revision += 1
                        document.status, document.stage = "processing", "queued"
                        document.error_code = document.error_message = None
                        session.add(
                            DocumentTask(
                                document_id=document.id,
                                index_revision=document.index_revision,
                                request_id="course-" + uuid4().hex,
                                action="process",
                            )
                        )
                        retried += 1
    return added, skipped, retried


def main() -> int:
    parser = argparse.ArgumentParser(description="导入管理员指定的课程内容包（无内置学习资料）")
    parser.add_argument(
        "--directory",
        type=Path,
        required=True,
        help="包含 manifest.json 与 sources.json 的内容包目录",
    )
    parser.add_argument("--retry-failed", action="store_true", help="重新处理既有失败的课程资料")
    parser.add_argument(
        "--restore-deleted",
        action="store_true",
        help="显式恢复内容包中已移除的资料（登记新记录，保留历史）",
    )
    arguments = parser.parse_args()
    settings = Settings()
    engine = create_database_engine(settings.sqlite_path)
    try:
        added, skipped, retried = import_course_data(
            engine,
            settings,
            arguments.directory,
            retry_failed=arguments.retry_failed,
            restore_deleted=arguments.restore_deleted,
        )
    except Exception:
        print("课程导入失败，请检查迁移、课程初始化、内容摘要和来源许可。")
        return 1
    finally:
        engine.dispose()
    print(f"课程资料已登记：新增 {added} 份，已有 {skipped} 份，重试 {retried} 份。")
    print("向量处理由后端执行；未配置向量服务时保留文件并显示失败，可在配置后重试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
