from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session


def create_database_engine(sqlite_path: Path) -> Engine:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite", database=str(sqlite_path)),
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    return engine


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session
