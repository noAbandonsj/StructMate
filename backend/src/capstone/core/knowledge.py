from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from capstone.core.errors import ApiError
from capstone.db.models import KnowledgeBase


def readable_bases(user_id: UUID) -> ColumnElement[bool]:
    return or_(KnowledgeBase.owner_id == user_id, KnowledgeBase.kind == "course")


def get_readable_base(session: Session, library_id: UUID, user_id: UUID) -> KnowledgeBase:
    library = session.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == library_id, readable_bases(user_id))
    )
    if library is None:
        raise ApiError(404, "LIBRARY_NOT_FOUND", "知识库不存在或不可访问。")
    return library
