import json
import os
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_documents import TestEmbedding, register, upload, wait_document
from test_practice import answer_for, create, items, submit

from capstone.core.settings import REPOSITORY_ROOT, Settings
from capstone.db.models import Document, DocumentChunk, KnowledgePoint, Question, Resource
from capstone.main import create_app
from capstone.manage_resources import import_resources

RESOURCE_PACKET = REPOSITORY_ROOT / "backend/tests/fixtures/resources.json"


def test_resource_maintainer_command_executes_without_a_model(bank_database, tmp_path):
    for expected in ("新增 6，更新 0，未变 0", "新增 0，更新 0，未变 6"):
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "capstone.manage_resources",
                "--file",
                str(RESOURCE_PACKET),
            ],
            env={**os.environ, "CAPSTONE_DATA_DIR": str(tmp_path)},
            capture_output=True,
            encoding="utf-8",
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert expected in result.stdout


def test_resources_import_is_atomic_idempotent_and_can_deactivate(bank_database, tmp_path):
    assert import_resources(bank_database, RESOURCE_PACKET) == (6, 0, 0)
    assert import_resources(bank_database, RESOURCE_PACKET) == (0, 0, 6)
    packet = json.loads(RESOURCE_PACKET.read_text(encoding="utf-8"))
    packet[0]["title"] = "维护后的标题"
    packet[0]["is_active"] = False
    path = tmp_path / "resources.json"
    path.write_text(json.dumps(packet), encoding="utf-8")
    assert import_resources(bank_database, path) == (0, 1, 5)
    packet[1]["knowledge_point_code"] = "missing"
    packet[0]["title"] = "不应部分写入"
    path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(ValueError):
        import_resources(bank_database, path)
    with Session(bank_database) as session:
        resource = session.scalar(select(Resource).where(Resource.code == packet[0]["code"]))
        assert resource.title == "维护后的标题" and not resource.is_active
    packet[1]["url"] = "javascript:alert(1)"
    path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(ValueError):
        import_resources(bank_database, path)


def test_recommendation_scope_difficulty_and_valid_wrong_reason(bank_database, tmp_path):
    import_resources(bank_database, RESOURCE_PACKET)
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        with Session(bank_database) as session:
            point = session.scalar(
                select(KnowledgePoint).where(KnowledgePoint.code == "stack-queue.stack")
            )
            point_id = str(point.id)
        result = client.get(
            "/api/v1/recommendations",
            params={"knowledge_point_id": point_id, "difficulty": "intermediate"},
        ).json()
        assert len(result["items"]) == 2
        assert result["items"][0]["difficulty"] == "intermediate"
        assert all("同属栈与队列章节" in item["reasons"] for item in result["items"])
        practice = create(client, headers, knowledge_point_ids=[point_id], count=1)
        item = items(client, practice["id"])[0]
        submit(client, headers, item, answer_for(bank_database, item, False))
        result = client.get("/api/v1/recommendations").json()
        assert "1 道有效待复习题" in " ".join(result["items"][0]["reasons"])
        with Session(bank_database) as session, session.begin():
            session.execute(
                update(Question)
                .where(Question.id == UUID(item["question_id"]))
                .values(is_valid=False)
            )
        result = client.get("/api/v1/recommendations").json()
        assert "待复习题" not in json.dumps(result["items"], ensure_ascii=False)
        assert (
            client.get("/api/v1/recommendations?knowledge_point_id=" + str(uuid4())).status_code
            == 422
        )
        assert client.get("/api/v1/recommendations?limit=0").status_code == 422
        assert client.get("/api/v1/recommendations?difficulty=invalid").status_code == 422
        client.cookies.clear()
        assert client.get("/api/v1/recommendations").status_code == 401


def test_recommendations_only_expose_current_readable_ready_documents(bank_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, embedding_service=TestEmbedding())) as client:
        other = TestClient(client.app)
        try:
            library, headers = register(client)
            other_library, other_headers = register(other, "other")
            identifier = upload(client, library, headers)["document"]["id"]
            private = upload(other, other_library, other_headers, filename="别人的.md")["document"][
                "id"
            ]
            wait_document(client, identifier, "ready")
            wait_document(other, private, "ready")
            with Session(bank_database) as session, session.begin():
                point = session.scalar(
                    select(KnowledgePoint).where(KnowledgePoint.code == "stack-queue")
                )
                session.execute(
                    update(Document)
                    .where(Document.id.in_([UUID(identifier), UUID(private)]))
                    .values(knowledge_point_id=point.id)
                )
                old = DocumentChunk(
                    id=uuid4(),
                    document_id=UUID(identifier),
                    index_revision=2,
                    position=0,
                    text="旧版本不应泄露",
                    knowledge_point_id=point.id,
                )
                old_id = old.id
                session.add(old)
            candidates = client.get("/api/v1/recommendations").json()["items"]
            assert len(candidates) == 1 and candidates[0]["document_id"] == identifier
            assert "旧版本" not in json.dumps(candidates, ensure_ascii=False)
            path = f"/api/v1/documents/{identifier}/chunks/{candidates[0]['chunk_id']}"
            assert client.get(path).status_code == 200
            assert other.get(path).status_code == 404
            assert client.get(f"/api/v1/documents/{identifier}/chunks/{old_id}").status_code == 404
            with Session(bank_database) as session, session.begin():
                session.execute(
                    update(Document).where(Document.id == UUID(identifier)).values(status="failed")
                )
            assert client.get("/api/v1/recommendations").json()["items"] == []
            assert client.get(path).status_code == 409
            with Session(bank_database) as session, session.begin():
                session.execute(
                    update(Document).where(Document.id == UUID(identifier)).values(status="ready")
                )
            assert (
                client.delete(f"/api/v1/documents/{identifier}", headers=headers).status_code == 202
            )
            assert client.get("/api/v1/recommendations").json()["items"] == []
            assert client.get(path).status_code == 410
        finally:
            other.close()
