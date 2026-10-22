from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from capstone.core.settings import REPOSITORY_ROOT
from capstone.db.session import create_database_engine


@pytest.fixture
def migration_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("CAPSTONE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPSTONE_ENVIRONMENT", "test")
    return Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))


@pytest.fixture
def migrated_database(migration_config: Config, tmp_path: Path) -> Iterator[Engine]:
    command.upgrade(migration_config, "head")
    engine = create_database_engine(tmp_path / "capstone.db")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def practice_db(migrated_database):
    from capstone.seed import seed_course_data

    seed_course_data(migrated_database)
    return migrated_database
