from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from capstone.api.schemas import Page, PageNumber, PageSize
from capstone.core.auth import AuthenticatedSession, DatabaseSession, no_store
from capstone.core.chapters import CHAPTER_CODES
from capstone.core.knowledge import get_readable_base, readable_bases
from capstone.db.models import Chapter, KnowledgeBase

router = APIRouter(tags=["knowledge"], dependencies=[Depends(no_store)])


class LibraryInfo(BaseModel):
    id: UUID
    kind: Literal["personal", "course"]
    name: str
    is_readonly: bool
    created_at: datetime


class ChapterInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
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


@router.get("/chapters", response_model=Page[ChapterInfo])
def list_chapters(
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 100,
) -> Page[ChapterInfo]:
    predicate = (Chapter.code.in_(CHAPTER_CODES),)
    total = session.scalar(select(func.count()).select_from(Chapter).where(*predicate))
    points = session.scalars(
        select(Chapter)
        .where(*predicate)
        .order_by(Chapter.sort_order, Chapter.code, Chapter.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[ChapterInfo.model_validate(point) for point in points],
        page=page,
        page_size=page_size,
        total=total,
    )
