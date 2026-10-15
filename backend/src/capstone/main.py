from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import QdrantClient
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from capstone import __version__
from capstone.api.auth import router as auth_router
from capstone.api.conversations import router as conversations_router
from capstone.api.documents import router as documents_router
from capstone.api.health import router as health_router
from capstone.api.knowledge import router as knowledge_router
from capstone.api.practice import router as practice_router
from capstone.api.summaries import router as summaries_router
from capstone.core.errors import install_error_handlers
from capstone.core.model_ports import (
    EmbeddingService,
    GenerationService,
    UnconfiguredEmbedding,
    UnconfiguredGeneration,
)
from capstone.core.settings import Settings
from capstone.core.upload_limits import UploadBodyLimit
from capstone.db.session import create_database_engine
from capstone.services.chat_runner import ChatRunner
from capstone.services.document_worker import DocumentWorker
from capstone.services.practice_runner import PracticeRunner
from capstone.services.storage import BlobStore
from capstone.services.summary_runner import SummaryRunner
from capstone.services.vectors import VectorIndex


def create_app(
    settings: Settings | None = None,
    *,
    embedding_service: EmbeddingService | None = None,
    generation_service: GenerationService | None = None,
) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configuration.uploads_dir.mkdir(parents=True, exist_ok=True)
        engine = create_database_engine(configuration.sqlite_path)
        vector_client = None
        worker = None
        chat_runner = None
        practice_runner = None
        summary_runner = None
        try:
            vector_client = QdrantClient(
                path=str(configuration.qdrant_dir),
                force_disable_check_same_thread=True,
            )
            app.state.engine = engine
            app.state.session_factory = sessionmaker(bind=engine)
            app.state.vector_client = vector_client
            app.state.blob_store = BlobStore(configuration.uploads_dir)
            app.state.vector_index = VectorIndex(vector_client, configuration.data_dir)
            app.state.embedding_service = embedding_service or UnconfiguredEmbedding()
            app.state.generation_service = generation_service or UnconfiguredGeneration()
            if inspect(engine).has_table("messages"):
                chat_runner = ChatRunner(
                    app.state.session_factory,
                    configuration,
                    app.state.generation_service,
                    app.state.embedding_service,
                    app.state.vector_index,
                )
                chat_runner.start()
            app.state.chat_runner = chat_runner
            if inspect(engine).has_table("practice_sessions"):
                practice_runner = PracticeRunner(
                    app.state.session_factory,
                    configuration,
                    app.state.generation_service,
                    app.state.embedding_service,
                    app.state.vector_index,
                )
                practice_runner.start()
            app.state.practice_runner = practice_runner
            if inspect(engine).has_table("conversations") and any(
                column["name"] == "summary_data"
                for column in inspect(engine).get_columns("conversations")
            ):
                summary_runner = SummaryRunner(
                    app.state.session_factory, app.state.generation_service
                )
                summary_runner.start()
            app.state.summary_runner = summary_runner
            if inspect(engine).has_table("document_tasks"):
                worker = DocumentWorker(
                    app.state.session_factory,
                    configuration,
                    app.state.embedding_service,
                    app.state.vector_index,
                    app.state.blob_store,
                )
                worker.start()
            app.state.document_worker = worker
            yield
        finally:
            if summary_runner is not None:
                summary_runner.stop()
            if practice_runner is not None:
                practice_runner.stop()
            if chat_runner is not None:
                chat_runner.stop()
            if worker is not None:
                worker.stop()
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
        UploadBodyLimit,
        maximum=configuration.upload_max_mib * 1024 * 1024 + 65536,
    )
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
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(conversations_router, prefix="/api/v1")
    app.include_router(practice_router, prefix="/api/v1")
    app.include_router(summaries_router, prefix="/api/v1")
    return app
