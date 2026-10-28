from logging.config import fileConfig

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy.engine import URL

from capstone.core.settings import Settings
from capstone.db.base import Base
from capstone.db.models import AuthSession, Chapter, KnowledgeBase, User  # noqa: F401
from capstone.db.session import create_database_engine
from capstone.db.types import UTCDateTime

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
settings = config.attributes.get("settings") or Settings()


def render_migration_item(kind: str, value: object, _context: AutogenContext) -> str | bool:
    # Migration files must not depend on application types that may change later.
    if kind == "type" and isinstance(value, UTCDateTime):
        return "sa.DateTime()"
    return False


def run_migrations_offline() -> None:
    url = URL.create("sqlite", database=str(settings.sqlite_path))
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        transactional_ddl=True,
        render_item=render_migration_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_database_engine(settings.sqlite_path)
    try:
        with engine.connect() as connection:
            # SQLite cannot rebuild a referenced table with foreign_keys enabled.
            # Disable it only on this migration connection, outside a transaction;
            # check the entire graph before committing and always restore it.
            driver = connection.connection.driver_connection
            driver.autocommit = True
            driver.execute("PRAGMA foreign_keys=OFF")
            driver.autocommit = False
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
                transactional_ddl=True,
                render_item=render_migration_item,
            )
            try:
                with context.begin_transaction():
                    context.run_migrations()
                    if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
                        raise RuntimeError("迁移后的外键关系无效，已回滚")
            finally:
                driver.autocommit = True
                driver.execute("PRAGMA foreign_keys=ON")
                driver.autocommit = False
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
