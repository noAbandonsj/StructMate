import logging
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from capstone import __version__

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    components: dict[str, Literal["ok", "error"]]


@router.get("/health", response_model=HealthResponse)
def health(request: Request, response: Response) -> HealthResponse:
    components: dict[str, Literal["ok", "error"]] = {"sqlite": "ok", "qdrant": "ok"}
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("SQLite health check failed")
        components["sqlite"] = "error"
    try:
        request.app.state.vector_client.get_collections()
    except Exception:
        logger.exception("Qdrant health check failed")
        components["qdrant"] = "error"

    healthy = all(status == "ok" for status in components.values())
    if not healthy:
        response.status_code = 503
    return HealthResponse(
        status="ok" if healthy else "degraded",
        version=__version__,
        components=components,
    )
