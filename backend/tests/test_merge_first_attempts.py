from uuid import UUID

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_documents import register
from test_practice import create, items, submit_group
from test_reports import wait_report

from capstone.core.settings import Settings
from capstone.db.models import LearningReport
from capstone.main import create_app


def test_merge_migration_preserves_answers_hints_reports_and_database_constraints(
    practice_db, migration_config, tmp_path
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        practice = create(client, headers, count=3)
        questions = items(client, practice["id"])
        client.post(f"/api/v1/practice-items/{questions[1]['id']}/hint", headers=headers)
        assert (
            submit_group(client, headers, practice_db, practice, lambda index: True).status_code
            == 201
        )
        repeated = create(client, headers, "repeat", count=3)
        assert (
            submit_group(client, headers, practice_db, repeated, lambda index: True).status_code
            == 201
        )
        client.post("/api/v1/reports", headers=headers, json={"client_request_id": "saved"})
    command.downgrade(migration_config, "0016")
    with practice_db.connect() as connection:
        before = [
            dict(row._mapping)
            for row in connection.execute(text("SELECT * FROM attempts ORDER BY id"))
        ]
        reports = connection.exec_driver_sql("SELECT * FROM learning_reports").all()
        assert {row["category"] for row in before} == {
            "first_independent",
            "first_hinted",
            "repeat",
        }
    command.upgrade(migration_config, "head")
    command.check(migration_config)
    with practice_db.connect() as connection:
        after = [
            dict(row._mapping)
            for row in connection.execute(text("SELECT * FROM attempts ORDER BY id"))
        ]
        assert after == [
            {
                **row,
                "category": "first" if row["category"].startswith("first_") else row["category"],
            }
            for row in before
        ]
        assert connection.exec_driver_sql("SELECT * FROM learning_reports").all() == reports
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    with pytest.raises(IntegrityError), practice_db.begin() as connection:
        connection.execute(text("UPDATE attempts SET category='first_hinted'"))


def test_legacy_report_cleanup_preserves_other_data_and_current_reports(
    practice_db, migration_config, tmp_path
):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        practice = create(client, headers, count=2)
        questions = items(client, practice["id"])
        client.post(f"/api/v1/practice-items/{questions[1]['id']}/hint", headers=headers)
        assert (
            submit_group(
                client, headers, practice_db, practice, lambda index: index == 1
            ).status_code
            == 201
        )
        current = client.post(
            "/api/v1/reports", headers=headers, json={"client_request_id": "current"}
        ).json()
        current = wait_report(client, current["id"], "failed")
    command.downgrade(migration_config, "0017")
    obsolete = []
    with Session(practice_db) as session, session.begin():
        source = session.get(LearningReport, UUID(current["id"]))
        for index, (snapshot, status) in enumerate(
            (
                ({"schema_version": 5}, "completed"),
                ({"schema_version": 4}, "failed"),
                ({}, "generating"),
            )
        ):
            old = LearningReport(
                user_id=source.user_id,
                from_date=source.from_date,
                to_date=source.to_date,
                cutoff_at=source.cutoff_at,
                snapshot=snapshot,
                status=status,
                content="旧报告" if status == "completed" else "",
                request_id=f"legacy-{index}",
                request_hash="legacy",
            )
            session.add(old)
            session.flush()
            obsolete.append(str(old.id))
    with practice_db.connect() as connection:
        tables = (
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT IN ('alembic_version', 'learning_reports') "
                "AND name NOT LIKE 'sqlite_%'"
            )
            .scalars()
            .all()
        )
        before = {
            table: connection.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY rowid').all()
            for table in tables
        }
        reports = connection.exec_driver_sql(
            "SELECT * FROM learning_reports WHERE request_id='current'"
        ).all()
    command.upgrade(migration_config, "head")
    command.check(migration_config)
    with practice_db.connect() as connection:
        assert connection.exec_driver_sql("SELECT * FROM learning_reports").all() == reports
        for table, rows in before.items():
            assert (
                connection.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY rowid').all() == rows
            )
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
        assert set(
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'report_%'"
            ).scalars()
        ) == {"report_snapshot_immutable", "report_completed_immutable"}
    command.downgrade(migration_config, "0017")
    command.upgrade(migration_config, "head")
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://127.0.0.1:5173"},
            json={"username": "student", "password": "test-password"},
        )
        assert client.get("/api/v1/reports").json()["total"] == 1
        assert client.get("/api/v1/reports/" + current["id"]).json() == current
        for identifier in obsolete:
            path = "/api/v1/reports/" + identifier
            assert client.get(path).status_code == 404
            assert client.get(path + "/export").status_code == 404
        exported = client.get("/api/v1/reports/" + current["id"] + "/export")
        assert exported.status_code == 200
        assert "首次作答：2 道，正确率 50.0%" in exported.text
        assert "未记录" not in exported.text
        assert client.get("/api/v1/learning/stats").json()["categories"]["first"]["count"] == 2
