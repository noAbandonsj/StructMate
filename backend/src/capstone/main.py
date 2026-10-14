from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import QdrantClient
from sqlalchemy.orm import sessionmaker

from capstone import __version__
from capstone.api.auth import router as auth_router
from capstone.api.health import router as health_router
from capstone.api.knowledge import router as knowledge_router
from capstone.core.errors import install_error_handlers
from capstone.core.settings import Settings
from capstone.db.session import create_database_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configuration.uploads_dir.mkdir(parents=True, exist_ok=True)
        engine = create_database_engine(configuration.sqlite_path)
        vector_client = None
        try:
            vector_client = QdrantClient(path=str(configuration.qdrant_dir))
            app.state.engine = engine
            app.state.session_factory = sessionmaker(bind=engine)
            app.state.vector_client = vector_client
            yield
        finally:
            if vector_client is not None:
                vector_client.close()
            engine.dispose()

    app = FastAPI(
        title="知序 · 数据结构学习助手",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = configuration
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configuration.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    return app
