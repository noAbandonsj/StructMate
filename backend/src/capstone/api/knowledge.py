from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from capstone.api.schemas import Page
from capstone.core.auth import AuthenticatedSession, DatabaseSession, no_store
from capstone.core.knowledge import get_readable_base, readable_bases
from capstone.db.models import KnowledgeBase, KnowledgePoint

router = APIRouter(tags=["knowledge"], dependencies=[Depends(no_store)])
PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


class LibraryInfo(BaseModel):
    id: UUID
    kind: Literal["personal", "course"]
    name: str
    is_readonly: bool
    created_at: datetime


class PointInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    parent_id: UUID | None
    sort_order: int


def library_info(library: KnowledgeBase) -> LibraryInfo:
    return LibraryInfo(
        id=library.id,
        kind=library.kind,
        name=library.name,
        is_readonly=library.kind == "course",
        created_at=library.created_at,
    )


@router.get("/knowledge-bases", response_model=Page[LibraryInfo])
def list_bases(
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[LibraryInfo]:
    predicate = readable_bases(current.user_id)
    total = session.scalar(select(func.count()).select_from(KnowledgeBase).where(predicate))
    libraries = session.scalars(
        select(KnowledgeBase)
        .where(predicate)
        .order_by(KnowledgeBase.kind.desc(), KnowledgeBase.name, KnowledgeBase.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[library_info(library) for library in libraries],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/knowledge-bases/{library_id}", response_model=LibraryInfo)
def base_detail(
    library_id: UUID, current: AuthenticatedSession, session: DatabaseSession
) -> LibraryInfo:
    return library_info(get_readable_base(session, library_id, current.user_id))


@router.get("/knowledge-points", response_model=Page[PointInfo])
def list_points(
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 100,
) -> Page[PointInfo]:
    total = session.scalar(select(func.count()).select_from(KnowledgePoint))
    points = session.scalars(
        select(KnowledgePoint)
        .order_by(KnowledgePoint.sort_order, KnowledgePoint.code, KnowledgePoint.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[PointInfo.model_validate(point) for point in points],
        page=page,
        page_size=page_size,
        total=total,
    )
