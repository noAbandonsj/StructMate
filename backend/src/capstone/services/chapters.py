"""Database access and validation for the fixed chapter catalog."""

from sqlalchemy import select

from capstone.core.chapters import CHAPTER_CODES
from capstone.core.errors import ApiError
from capstone.db.models import Chapter


def chapters(session):
    return session.scalars(
        select(Chapter)
        .where(Chapter.code.in_(CHAPTER_CODES))
        .order_by(Chapter.sort_order, Chapter.code)
    ).all()


def require_chapter(session, identifier):
    chapter = session.get(Chapter, identifier) if identifier else None
    if chapter is None or chapter.code not in CHAPTER_CODES:
        raise ApiError(422, "CHAPTER_INVALID", "请选择有效的内置章节。")
    return chapter
