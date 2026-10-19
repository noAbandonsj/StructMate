import json
import os
import shutil
import subprocess
import sys
import time
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_conversations import TestGeneration, new_conversation, send, wait_answer
from test_documents import ORIGIN, TEXT, TestEmbedding, register, upload, wait_document

from capstone.core.settings import REPOSITORY_ROOT, Settings
from capstone.db.models import CourseMaintenance, Document, DocumentTask, KnowledgePoint, User
from capstone.db.session import write_transaction
from capstone.import_course import import_course_data
from capstone.main import create_app
from capstone.seed import seed_course_data
from capstone.services.documents import queue_delete
from capstone.services.storage import BlobStore

ROOT = "/api/v1/admin/course/documents"


def role(engine, username, value):
    with Session(engine) as session, write_transaction(session):
        session.scalar(select(User).where(User.username == username)).role = value


def course_upload(client, headers, point, **values):
    return client.post(
        ROOT,
        headers=headers,
        files={"file": ("课程维护测试.md", TEXT, "text/markdown")},
        data={
            "knowledge_point_id": str(point),
            "author": "维护者",
            "source": "自编",
            "license": "授权课程学习使用",
            **values,
        },
    )


def point_id(engine):
    with Session(engine) as session:
        return session.scalar(
            select(KnowledgePoint.id).where(KnowledgePoint.code == "stack-queue")
        ) or session.scalar(select(KnowledgePoint.id))


def test_admin_api_rejects_student_and_immediate_revocation(migrated_database, tmp_path):
    seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        assert client.get("/api/v1/auth/me").json()["user"]["role"] == "user"
        for response in (
            client.get(ROOT),
            course_upload(client, headers, point_id(migrated_database)),
            client.get(ROOT + f"/{uuid4()}/file"),
            client.post(
                ROOT + f"/{uuid4()}/process", headers=headers, json={"client_request_id": "x"}
            ),
            client.delete(ROOT + f"/{uuid4()}", headers=headers),
        ):
            assert response.status_code == 403, response.text
        role(migrated_database, "student", "admin")
        assert client.get("/api/v1/auth/me").json()["user"]["role"] == "admin"
        assert client.get(ROOT).status_code == 200
        role(migrated_database, "student", "user")
        assert client.get(ROOT).status_code == 403
        assert course_upload(client, headers, point_id(migrated_database)).status_code == 403
        assert client.get("/api/v1/auth/me").status_code == 200


def test_role_injection_and_invalid_database_role_are_rejected(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/v1/auth/register",
                headers=ORIGIN,
                json={
                    "username": "injected",
                    "password": "test-password",
                    "role": "admin",
                },
            ).status_code
            == 422
        )
        _, headers = register(client)
        assert (
            client.patch(
                "/api/v1/auth/me",
                headers=headers,
                json={
                    "display_name": "维护者",
                    "role": "admin",
                },
            ).status_code
            == 422
        )
        assert client.get("/api/v1/auth/me").json()["user"]["role"] == "user"
    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(text("UPDATE users SET role = 'owner'"))


def test_course_upload_retrieval_processing_history_and_deletion(migrated_database, tmp_path):
    course = seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=TestGeneration())
    ) as admin:
        student = TestClient(admin.app)
        try:
            _, headers = register(admin, "maintainer")
            role(migrated_database, "maintainer", "admin")
            _, student_headers = register(student, "learner")
            point = point_id(migrated_database)
            response = course_upload(admin, headers, point)
            assert response.status_code == 202, response.text
            identifier = response.json()["document"]["id"]
            ready = wait_document(student, identifier, "ready")
            assert ready["knowledge_point_id"] == str(point)
            assert ready["source_info"]["sources"][0]["author"] == "维护者"
            duplicate = course_upload(admin, headers, point, author="不覆盖")
            assert duplicate.json()["duplicate"] is True
            assert duplicate.json()["document"]["source_info"] == ready["source_info"]
            assert admin.get(ROOT + f"/{identifier}/file").content == TEXT
            assert admin.get(ROOT + f"/{identifier}/chunks").json()["total"] > 0
            assert admin.get(ROOT + "?search=不存在&status=ready").json()["total"] == 0
            assert admin.get(ROOT + "?search=维护测试&status=ready").json()["total"] == 1
            assert admin.get(ROOT + "?search=%25").json()["total"] == 0
            assert (
                student.get(f"/api/v1/knowledge-bases/{course.course_id}/documents").json()["total"]
                == 1
            )
            conversation = new_conversation(
                student, student_headers, scope="course", document_ids=[identifier]
            )
            assert send(student, student_headers, conversation).status_code == 202
            answer = wait_answer(student, conversation)
            assert {item["document_id"] for item in answer["citations"]} == {identifier}
            path = ROOT + f"/{identifier}"
            request = {"client_request_id": "reprocess-one"}
            assert admin.post(path + "/process", headers=headers, json=request).status_code == 202
            wait_document(student, identifier, "ready")
            assert admin.post(path + "/process", headers=headers, json=request).status_code == 202
            history = admin.get(path + "/history").json()
            assert {item["actor"] for item in history} == {"maintainer"}
            assert [item["action"] for item in history] == ["process", "upload"]
            assert admin.delete(path, headers=headers).status_code == 202
            deadline = time.monotonic() + 6
            while admin.get(path).json()["stage"] != "complete":
                assert time.monotonic() < deadline
                time.sleep(0.03)
            assert admin.delete(path, headers=headers).status_code == 202
            assert admin.get(path + "/file").status_code == 410
            assert admin.get(path + "/chunks").status_code == 410
            assert admin.get(ROOT).json()["total"] == 0
            assert admin.get(ROOT + "?status=deleted").json()["total"] == 1
            assert len(admin.get(path + "/history").json()) == 3
            after = student.get(f"/api/v1/conversations/{conversation}/messages").json()["items"][
                -1
            ]
            assert after["citations"][0]["text"] == answer["citations"][0]["text"]
            assert after["citations"][0]["source_deleted"] is True
            assert send(student, student_headers, conversation, "after-delete").status_code == 409
            with Session(migrated_database) as session:
                assert session.scalar(select(func.count()).select_from(DocumentTask)) == 3
                assert session.scalar(select(func.count()).select_from(CourseMaintenance)) == 3
        finally:
            student.close()


def test_admin_cannot_use_course_routes_for_personal_documents(migrated_database, tmp_path):
    seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, embedding_service=TestEmbedding())) as admin:
        student = TestClient(admin.app)
        try:
            own, headers = register(admin, "maintainer")
            role(migrated_database, "maintainer", "admin")
            library, student_headers = register(student, "learner")
            hidden = upload(student, library, student_headers)["document"]["id"]
            mine = upload(admin, own, headers)["document"]["id"]
            for identifier in (hidden, mine):
                path = ROOT + f"/{identifier}"
                for suffix in ("", "/file", "/chunks", "/history"):
                    assert admin.get(path + suffix).status_code == 404
                assert admin.delete(path, headers=headers).status_code == 404
                assert (
                    admin.post(
                        path + "/process", headers=headers, json={"client_request_id": "x"}
                    ).status_code
                    == 404
                )
            for suffix in ("", "/file", "/chunks"):
                assert admin.get(f"/api/v1/documents/{hidden}{suffix}").status_code == 404
            assert admin.delete(f"/api/v1/documents/{hidden}", headers=headers).status_code == 404
            conversation = new_conversation(student, student_headers)
            assert admin.get(f"/api/v1/conversations/{conversation}").status_code == 404
            assert admin.get(f"/api/v1/knowledge-bases/{library}/documents").status_code == 404
            assert admin.get("/api/v1/wrong-questions").json()["total"] == 0
            assert admin.get("/api/v1/reports").json()["total"] == 0
        finally:
            student.close()


def test_upload_validation_csrf_busy_and_model_failure_retry(migrated_database, tmp_path):
    seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path, upload_max_mib=1)
    with TestClient(create_app(settings)) as admin:
        _, headers = register(admin)
        role(migrated_database, "student", "admin")
        point = point_id(migrated_database)
        assert course_upload(admin, ORIGIN, point).status_code == 403
        assert course_upload(admin, headers, point, author=" ").status_code == 422
        assert course_upload(admin, headers, uuid4()).status_code == 422
        assert (
            admin.post(
                ROOT, headers={**headers, "Content-Length": "2000000"}, content=b"x"
            ).status_code
            == 413
        )
        response = course_upload(admin, headers, point)
        identifier = response.json()["document"]["id"]
        failed = wait_document(admin, identifier, "failed")
        assert failed["error_code"] == "EMBEDDING_NOT_CONFIGURED"
        assert (
            admin.post(
                ROOT + f"/{identifier}/process", headers=headers, json={"client_request_id": "x"}
            ).status_code
            == 503
        )
        admin.app.state.embedding_service = TestEmbedding()
        admin.app.state.document_worker.embedding = TestEmbedding()
        assert (
            admin.post(
                ROOT + f"/{identifier}/process", headers=headers, json={"client_request_id": "x"}
            ).status_code
            == 202
        )
        wait_document(admin, identifier, "ready")
        admin.app.state.document_worker.stop()
        response = admin.post(
            ROOT + f"/{identifier}/process", headers=headers, json={"client_request_id": "busy"}
        )
        assert response.status_code == 202
        assert (
            admin.post(
                ROOT + f"/{identifier}/process", headers=headers, json={"client_request_id": "busy"}
            ).status_code
            == 202
        )
        assert (
            admin.post(
                ROOT + f"/{identifier}/process",
                headers=headers,
                json={"client_request_id": "another"},
            ).status_code
            == 409
        )


def test_deleted_presets_stay_removed_until_explicit_restore(migrated_database, tmp_path):
    seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    assert import_course_data(migrated_database, settings) == (3, 0, 0)
    with TestClient(create_app(settings)) as admin:
        _, headers = register(admin)
        role(migrated_database, "student", "admin")
        identifier = admin.get(ROOT).json()["items"][0]["id"]
        assert admin.delete(ROOT + f"/{identifier}", headers=headers).status_code == 202
        assert import_course_data(migrated_database, settings) == (0, 3, 0)
        _, _, retries = import_course_data(migrated_database, settings, retry_failed=True)
        assert retries <= 2
        with Session(migrated_database) as session:
            assert session.get(Document, UUID(identifier)).status == "deleted"
        assert import_course_data(migrated_database, settings, restore_deleted=True) == (1, 2, 0)
        assert import_course_data(migrated_database, settings, restore_deleted=True) == (0, 3, 0)
        with Session(migrated_database) as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(Document).where(Document.status != "deleted")
                )
                == 3
            )


def test_admin_cli_grant_list_revoke_unknown_account(migrated_database, tmp_path):
    with Session(migrated_database) as session, session.begin():
        session.add(User(username="maintainer", display_name="维护者", password_hash="hash"))
    environment = {**os.environ, "CAPSTONE_DATA_DIR": str(tmp_path)}
    for arguments, status, expected in (
        (["grant", "missing"], 1, "账号不存在"),
        (["grant", "maintainer"], 0, "admin"),
        (["list", "maintainer"], 0, "admin"),
        (["revoke", "maintainer"], 0, "user"),
    ):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "capstone.manage_admin", *arguments],
            env=environment,
            capture_output=True,
            encoding="utf-8",
            timeout=20,
        )
        assert result.returncode == status, result.stderr
        assert expected in result.stdout


def test_updated_preset_import_does_not_race_course_deletion(
    migrated_database, tmp_path, monkeypatch
):
    seed_course_data(migrated_database)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    assert import_course_data(migrated_database, settings) == (3, 0, 0)
    packet = tmp_path / "packet"
    shutil.copytree(REPOSITORY_ROOT / "content", packet)
    manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
    item = manifest[0]
    file = packet / item["path"]
    updated = file.read_text(encoding="utf-8") + "\n新增课程维护内容。\n"
    file.write_text(updated, encoding="utf-8", newline="\n")
    item["sha256"] = sha256(updated.encode()).hexdigest()
    (packet / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with Session(migrated_database) as session, write_transaction(session):
        actor = User(
            username="maintainer", display_name="维护者", password_hash="hash", role="admin"
        )
        session.add(actor)
        session.flush()
        actor_id = actor.id
        identifier = session.scalar(
            select(Document.id).where(
                Document.source_info["content_code"].as_string() == item["code"]
            )
        )
    original_save = BlobStore.save

    def save_then_remove(store, *args):
        key = original_save(store, *args)
        with Session(migrated_database) as session:
            queue_delete(session, identifier, actor_id, course_admin=True)
        return key

    monkeypatch.setattr(BlobStore, "save", save_then_remove)
    assert import_course_data(migrated_database, settings, packet) == (0, 3, 0)
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 3
        assert session.get(Document, identifier).status == "deleted"
    assert len(list(settings.uploads_dir.iterdir())) == 3  # New blob was removed on rejection.


def test_role_migration_preserves_old_users_and_related_sessions(
    migrated_database, migration_config
):
    command.downgrade(migration_config, "0008")
    identifier = uuid4().hex
    stamp = "2026-10-01 10:00:00.000000"
    with migrated_database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, display_name, password_hash, "
                "created_at, updated_at) VALUES (:id, 'legacy', '旧账号', 'hash', :stamp, :stamp)"
            ),
            {"id": identifier, "stamp": stamp},
        )
        connection.execute(
            text(
                "INSERT INTO auth_sessions (id, user_id, token_hash, csrf_token, "
                "created_at, expires_at) "
                "VALUES (:session, :user, :token, 'csrf', :stamp, '2030-01-01 00:00:00.000000')"
            ),
            {"session": uuid4().hex, "user": identifier, "token": "a" * 64, "stamp": stamp},
        )
    command.upgrade(migration_config, "head")
    with migrated_database.connect() as connection:
        assert connection.execute(
            text("SELECT role, updated_at FROM users WHERE id = :id"), {"id": identifier}
        ).one() == ("user", stamp)
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert (
            connection.execute(text("SELECT user_id FROM auth_sessions")).scalar_one() == identifier
        )
