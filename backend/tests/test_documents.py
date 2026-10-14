import io
import os
import subprocess
import sys
import time
from hashlib import sha256
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from capstone.core.errors import ApiError
from capstone.core.model_ports import EmbeddingBatch
from capstone.core.settings import Settings
from capstone.db.models import Document, DocumentChunk, DocumentTask
from capstone.import_course import import_course_data
from capstone.main import create_app
from capstone.seed import seed_course_data
from capstone.services.parsing import parse_file, split_fragments
from capstone.services.storage import BlobStore
from capstone.services.vectors import COLLECTION

ORIGIN = {"Origin": "http://127.0.0.1:5173"}
TEXT = "# 栈\n\n栈是后进先出的线性结构。\n\n## 操作\n\npush 和 pop 操作栈顶。\n".encode()


def test_course_import_command_executes_and_is_repeatable(migrated_database, tmp_path):
    seed_course_data(migrated_database)
    environment = {**os.environ, "CAPSTONE_DATA_DIR": str(tmp_path)}
    for expected in ("新增 3 份，已有 0 份", "新增 0 份，已有 3 份"):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "capstone.import_course"],
            env=environment,
            capture_output=True,
            encoding="utf-8",
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert expected in result.stdout
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 3
        assert session.scalar(select(func.count()).select_from(DocumentTask)) == 3
        assert set(session.scalars(select(Document.status))) == {"processing"}
    assert len(list((tmp_path / "uploads").iterdir())) == 3


class TestEmbedding:
    __test__ = False
    available = True
    fingerprint = sha256(b"test-embedding-v1").hexdigest()

    def embed(self, texts):
        return EmbeddingBatch(
            [[1.0, (len(text) % 17) / 17, 0.2] for text in texts], self.fingerprint
        )


def register(client, username="student"):
    response = client.post(
        "/api/v1/auth/register",
        headers=ORIGIN,
        json={
            "username": username,
            "password": "test-password",
        },
    )
    assert response.status_code == 201
    account = response.json()
    return account["default_knowledge_base"]["id"], {
        **ORIGIN,
        "X-CSRF-Token": account["csrf_token"],
    }


def wait_document(client, document_id, status):
    deadline = time.monotonic() + 6
    while True:
        response = client.get(f"/api/v1/documents/{document_id}")
        assert response.status_code == 200
        document = response.json()
        if document["status"] == status:
            return document
        assert time.monotonic() < deadline, document
        time.sleep(0.03)


def upload(client, library_id, headers, data=TEXT, filename="课程.md"):
    response = client.post(
        f"/api/v1/knowledge-bases/{library_id}/documents",
        headers=headers,
        files={"file": (filename, data, "text/markdown")},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_real_files_chunks_vectors_duplicate_retry_and_delete(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, embedding_service=TestEmbedding())) as client:
        library, headers = register(client)
        result = upload(client, library, headers)
        doc_id = result["document"]["id"]
        ready = wait_document(client, doc_id, "ready")
        assert ready["filename"] == "课程.md"
        assert ready["stage"] == "complete"
        assert client.get(f"/api/v1/documents/{doc_id}/file").content == TEXT
        chunks = client.get(f"/api/v1/documents/{doc_id}/chunks").json()
        assert chunks["total"] > 0
        assert all(
            item["line_start"] >= 1 and item["line_end"] >= item["line_start"]
            for item in chunks["items"]
        )
        assert any("操作" in (item["heading"] or "") for item in chunks["items"])
        vectors = client.app.state.vector_client
        points = vectors.scroll(COLLECTION, limit=100, with_payload=True)[0]
        assert len(points) == chunks["total"]
        assert {point.payload["chunk_id"] for point in points} == {
            item["id"] for item in chunks["items"]
        }
        assert all(point.payload["document_id"] == doc_id for point in points)
        assert upload(client, library, headers)["duplicate"] is True
        assert client.get(f"/api/v1/knowledge-bases/{library}/documents").json()["total"] == 1

        request = {"client_request_id": "refresh-1"}
        response = client.post(f"/api/v1/documents/{doc_id}/process", headers=headers, json=request)
        assert response.status_code == 202
        wait_document(client, doc_id, "ready")
        assert (
            client.post(
                f"/api/v1/documents/{doc_id}/process", headers=headers, json=request
            ).status_code
            == 202
        )
        with Session(migrated_database) as session:
            assert session.scalar(select(func.count()).select_from(DocumentTask)) == 2
        assert vectors.count(COLLECTION, exact=True).count == chunks["total"]

        assert client.delete(f"/api/v1/documents/{doc_id}", headers=headers).status_code == 202
        assert client.get(f"/api/v1/documents/{doc_id}/file").status_code == 410
        assert client.get(f"/api/v1/documents/{doc_id}/chunks").status_code == 410
        deadline = time.monotonic() + 6
        while client.get(f"/api/v1/documents/{doc_id}").json()["stage"] != "complete":
            assert time.monotonic() < deadline
            time.sleep(0.03)
        assert vectors.count(COLLECTION, exact=True).count == 0
        assert list(settings.uploads_dir.iterdir()) == []
        with Session(migrated_database) as session:
            assert session.scalar(select(func.count()).select_from(Document)) == 1
            assert session.scalar(select(func.count()).select_from(DocumentChunk)) > 0
        assert client.get(f"/api/v1/knowledge-bases/{library}/documents").json()["total"] == 0
        newer = upload(client, library, headers)["document"]["id"]
        assert newer != doc_id
        wait_document(client, newer, "ready")


def test_unconfigured_embedding_never_marks_document_ready(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        library, headers = register(client)
        doc_id = upload(client, library, headers)["document"]["id"]
        failed = wait_document(client, doc_id, "failed")
        assert failed["error_code"] == "EMBEDDING_NOT_CONFIGURED"
        assert client.get(f"/api/v1/documents/{doc_id}/file").content == TEXT
        assert client.get(f"/api/v1/documents/{doc_id}/chunks").status_code == 409
        assert not client.app.state.vector_client.collection_exists(COLLECTION)


def test_cross_account_and_readonly_course_access(migrated_database, tmp_path):
    course = seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, embedding_service=TestEmbedding())) as first:
        second = TestClient(first.app)
        try:
            a, headers_a = register(first, "first")
            b, headers_b = register(second, "second")
            doc_a = upload(first, a, headers_a)["document"]["id"]
            doc_b = upload(second, b, headers_b)["document"]["id"]
            wait_document(first, doc_a, "ready")
            wait_document(second, doc_b, "ready")
            for suffix in ("", "/file", "/chunks"):
                assert second.get(f"/api/v1/documents/{doc_a}{suffix}").status_code == 404
            assert second.delete(f"/api/v1/documents/{doc_a}", headers=headers_b).status_code == 404
            assert (
                second.post(
                    f"/api/v1/documents/{doc_a}/process",
                    headers=headers_b,
                    json={"client_request_id": "retry"},
                ).status_code
                == 404
            )
            assert second.get(f"/api/v1/knowledge-bases/{a}/documents").status_code == 404
            assert (
                first.post(
                    f"/api/v1/knowledge-bases/{course.course_id}/documents",
                    headers=headers_a,
                    files={"file": ("notes.md", TEXT)},
                ).status_code
                == 403
            )
            first.delete(f"/api/v1/documents/{doc_a}", headers=headers_a)
            assert second.get(f"/api/v1/documents/{doc_b}/file").content == TEXT
            query = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=doc_b))])
            assert (
                first.app.state.vector_client.count(
                    COLLECTION, count_filter=query, exact=True
                ).count
                > 0
            )
        finally:
            second.close()


@pytest.mark.parametrize(
    "filename,data,status",
    [
        ("bad.exe", b"binary", 415),
        ("empty.txt", b"", 422),
        ("bad.pdf", b"not-pdf", 422),
        ("binary.txt", b"a\x00b", 422),
        ("huge.txt", b"x" * (1024 * 1024 + 1), 413),
    ],
    ids=["unsupported", "empty", "invalid-pdf", "binary-text", "too-large"],
)
def test_rejected_uploads_leave_no_document_or_file(
    migrated_database, tmp_path, filename, data, status
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path, upload_max_mib=1)
    with TestClient(create_app(settings)) as client:
        library, headers = register(client)
        response = client.post(
            f"/api/v1/knowledge-bases/{library}/documents",
            headers=headers,
            files={"file": (filename, data)},
        )
        assert response.status_code == status
        with Session(migrated_database) as session:
            assert session.scalar(select(func.count()).select_from(Document)) == 0
        assert list(settings.uploads_dir.iterdir()) == []


def test_pdf_and_markdown_positions_and_long_line_splitting(tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    path = tmp_path / "notes.md"
    path.write_text(
        "# 标题\n\n正文。\n\n" + chr(96) * 3 + "\ncode()\n\nmore()\n" + chr(96) * 3,
        encoding="utf-8",
    )
    parts = parse_file(path, "md", settings)
    assert any("code()\n\nmore()" in part.text for part in parts)
    assert all(part.heading == "标题" for part in parts)
    path.write_text("x" * 5000, encoding="utf-8")
    chunks = split_fragments(parse_file(path, "txt", settings), 1200)
    assert "".join(part.text for part in chunks) == "x" * 5000
    assert all(part.line_start == part.line_end == 1 for part in chunks)

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=400)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 200 Td (linked list) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    pdf = tmp_path / "notes.pdf"
    pdf.write_bytes(output.getvalue())
    extracted = parse_file(pdf, "pdf", settings)
    assert extracted[0].page_number == 1 and "linked list" in extracted[0].text
    writer.encrypt("password")
    writer.write(pdf)
    with pytest.raises(ApiError, match="PDF_ENCRYPTED"):
        parse_file(pdf, "pdf", settings)


def test_blob_paths_cannot_escape_upload_directory(tmp_path):
    store = BlobStore(tmp_path / "uploads")
    for key in ("../outside.txt", "C:/secret.txt", "not-a-uuid.md"):
        with pytest.raises(ApiError, match="FILE_UNAVAILABLE"):
            store.path(key)


def test_gb18030_preview_is_utf8_while_download_preserves_original(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    data = "链表节点包含数据和后继引用。".encode("gb18030")
    with TestClient(create_app(settings)) as client:
        library, headers = register(client)
        doc_id = upload(client, library, headers, data, "中文.txt")["document"]["id"]
        wait_document(client, doc_id, "failed")
        preview = client.get(f"/api/v1/documents/{doc_id}/file")
        assert preview.content.decode("utf-8") == "链表节点包含数据和后继引用。"
        assert client.get(f"/api/v1/documents/{doc_id}/file?download=true").content == data
        assert client.get("/api/v1/documents/upload-config").json()["embedding_available"] is False


def test_course_import_is_idempotent_attributed_and_can_retry_after_configuration(
    migrated_database,
    tmp_path,
):
    seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    assert import_course_data(migrated_database, settings) == (3, 0, 0)
    assert import_course_data(migrated_database, settings) == (0, 3, 0)
    with Session(migrated_database) as session:
        document_ids = [str(value) for value in session.scalars(select(Document.id))]
    with TestClient(create_app(settings)) as client:
        _library, _headers = register(client)
        for doc_id in document_ids:
            record = wait_document(client, doc_id, "failed")
            assert record["source_info"]["sources"]
            assert all(source["license"] for source in record["source_info"]["sources"])
            assert "原作" in client.get(f"/api/v1/documents/{doc_id}/file").text
    with TestClient(create_app(settings, embedding_service=TestEmbedding())) as client:
        _library, headers = register(client, "second")
        assert import_course_data(migrated_database, settings, retry_failed=True) == (0, 3, 3)
        for doc_id in document_ids:
            wait_document(client, doc_id, "ready")
            assert client.delete(f"/api/v1/documents/{doc_id}", headers=headers).status_code == 403
            assert (
                client.post(
                    f"/api/v1/documents/{doc_id}/process",
                    headers=headers,
                    json={"client_request_id": "course-retry"},
                ).status_code
                == 403
            )
        with Session(migrated_database) as session:
            assert session.scalar(select(func.count()).select_from(Document)) == 3


def test_interrupted_processing_is_failed_on_restart_without_replaying(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        library, headers = register(client)
        doc_id = upload(client, library, headers)["document"]["id"]
        wait_document(client, doc_id, "failed")
        cookie = client.cookies.get("capstone_session")
    with Session(migrated_database) as session, session.begin():
        document = session.get(Document, UUID(doc_id))
        document.status = "processing"
        task = session.scalar(select(DocumentTask).where(DocumentTask.document_id == document.id))
        task.status, task.attempt_count = "running", 1
    with TestClient(create_app(settings)) as client:
        client.cookies.set("capstone_session", cookie)
        record = wait_document(client, doc_id, "failed")
        assert record["error_code"] == "PROCESS_INTERRUPTED"
        assert client.get(f"/api/v1/documents/{doc_id}/file").content == TEXT
        with Session(migrated_database) as session:
            assert session.scalar(select(func.count()).select_from(DocumentTask)) == 1


def test_cleanup_failure_is_bounded_and_retriable(migrated_database, tmp_path, monkeypatch):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, embedding_service=TestEmbedding())) as client:
        library, headers = register(client)
        doc_id = upload(client, library, headers)["document"]["id"]
        wait_document(client, doc_id, "ready")
        store = client.app.state.blob_store
        original = store.remove

        def blocked(_key):
            raise PermissionError("Simulated file lock")

        monkeypatch.setattr(store, "remove", blocked)
        assert client.delete(f"/api/v1/documents/{doc_id}", headers=headers).status_code == 202
        deadline = time.monotonic() + 6
        while client.get(f"/api/v1/documents/{doc_id}").json()["stage"] != "cleanup_failed":
            assert time.monotonic() < deadline
            time.sleep(0.03)
        assert client.get(f"/api/v1/documents/{doc_id}/file").status_code == 410
        with Session(migrated_database) as session:
            task = session.scalar(select(DocumentTask).where(DocumentTask.action == "delete"))
            assert task.attempt_count == 3
        monkeypatch.setattr(store, "remove", original)
        assert client.delete(f"/api/v1/documents/{doc_id}", headers=headers).status_code == 202
        while client.get(f"/api/v1/documents/{doc_id}").json()["stage"] != "complete":
            assert time.monotonic() < deadline
            time.sleep(0.03)
        assert list(settings.uploads_dir.iterdir()) == []


@pytest.mark.parametrize(
    "mode",
    ["shape", "secret-error", "fingerprint"],
    ids=["bad-shape", "private-error", "changed-index"],
)
def test_model_failure_and_configuration_mismatch_never_publish_ready(
    migrated_database,
    tmp_path,
    mode,
):
    class FailedEmbedding(TestEmbedding):
        def embed(self, texts):
            if mode == "shape":
                return EmbeddingBatch([], self.fingerprint)
            if mode == "secret-error":
                raise RuntimeError("private-test-credential")
            return EmbeddingBatch([[1.0, 0.1, 0.2] for _text in texts], sha256(b"new").hexdigest())

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    if mode == "fingerprint":
        with TestClient(create_app(settings, embedding_service=TestEmbedding())) as client:
            library, headers = register(client)
            doc_id = upload(client, library, headers)["document"]["id"]
            wait_document(client, doc_id, "ready")
    with TestClient(create_app(settings, embedding_service=FailedEmbedding())) as client:
        library, headers = register(client, "new_user")
        doc_id = upload(client, library, headers)["document"]["id"]
        failed = wait_document(client, doc_id, "failed")
        expected = {
            "shape": "EMBEDDING_INVALID",
            "secret-error": "PROCESS_FAILED",
            "fingerprint": "INDEX_REBUILD_REQUIRED",
        }
        assert failed["error_code"] == expected[mode]
        assert "private-test-credential" not in str(failed)
        assert client.get(f"/api/v1/documents/{doc_id}/chunks").status_code == 409


def test_write_requests_reject_missing_csrf_and_hidden_ids_even_without_model(
    migrated_database,
    tmp_path,
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as first:
        second = TestClient(first.app)
        try:
            a, headers_a = register(first, "first")
            _b, headers_b = register(second, "second")
            assert (
                first.post(
                    f"/api/v1/knowledge-bases/{a}/documents",
                    headers=ORIGIN,
                    files={"file": ("notes.md", TEXT)},
                ).status_code
                == 403
            )
            doc_id = upload(first, a, headers_a)["document"]["id"]
            wait_document(first, doc_id, "failed")
            assert (
                second.post(
                    f"/api/v1/documents/{doc_id}/process",
                    headers=headers_b,
                    json={"client_request_id": "retry"},
                ).status_code
                == 404
            )
            assert (
                first.post(
                    f"/api/v1/documents/{doc_id}/process",
                    headers=headers_a,
                    json={"client_request_id": "retry"},
                ).status_code
                == 503
            )
            assert first.delete(f"/api/v1/documents/{doc_id}", headers=ORIGIN).status_code == 403
            with Session(migrated_database) as session:
                assert session.scalar(select(func.count()).select_from(DocumentTask)) == 1
        finally:
            second.close()
