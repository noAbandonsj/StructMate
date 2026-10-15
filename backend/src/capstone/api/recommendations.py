from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from capstone.core.auth import AuthenticatedSession, DatabaseSession, no_store
from capstone.services.recommendations import recommendations

router = APIRouter(tags=["recommendations"], dependencies=[Depends(no_store)])


@router.get("/recommendations")
def recommend(
    current: AuthenticatedSession,
    session: DatabaseSession,
    knowledge_point_id: UUID | None = None,
    difficulty: Literal["basic", "intermediate", "advanced"] = "basic",
    limit: Annotated[int, Query(ge=1, le=12)] = 6,
):
    return recommendations(session, current.user_id, knowledge_point_id, difficulty, limit)
