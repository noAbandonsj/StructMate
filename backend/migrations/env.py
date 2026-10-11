from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import URL

from capstone.core.settings import Settings
from capstone.db.base import Base
from capstone.db.session import create_database_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import business models here as they are introduced, before autogeneration.
target_metadata = Base.metadata
settings = Settings()


def run_migrations_offline() -> None:
    url = URL.create("sqlite", database=str(settings.sqlite_path))
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_database_engine(settings.sqlite_path)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
