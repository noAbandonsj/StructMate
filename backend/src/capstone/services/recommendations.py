from collections import Counter

from sqlalchemy import case, func, select

from capstone.core.errors import ApiError
from capstone.core.knowledge import readable_bases
from capstone.db.models import (
    Document,
    DocumentChunk,
    KnowledgeBase,
    Question,
    Resource,
    WrongQuestion,
)
from capstone.services.chapters import chapters

LEVELS = {"basic": 0, "intermediate": 1, "advanced": 2}


def recommendations(session, user_id, point_id=None, difficulty="basic", limit=6):
    points = chapters(session)
    by_id = {point.id: point for point in points}
    if point_id and point_id not in by_id:
        raise ApiError(422, "CHAPTER_INVALID", "所选章节不存在。")
    roots = {point.code: point for point in points}

    def chapter(identifier):
        return by_id[identifier].code if identifier in by_id else None

    target = chapter(point_id)
    related = [point.id for point in points if not target or chapter(point.id) == target]
    pending = Counter(
        chapter(identifier)
        for identifier in session.scalars(
            select(Question.chapter_id)
            .join(WrongQuestion, WrongQuestion.question_id == Question.id)
            .where(
                WrongQuestion.user_id == user_id,
                WrongQuestion.status == "pending",
                Question.is_valid.is_(True),
            )
        )
    )
    candidates = []

    def describe(identifier, level):
        root = chapter(identifier)
        name = roots[root].name if root in roots else "未分类"
        reasons = [f"同属{name}章节" if target else f"{name}的学习资料"]
        if pending[root]:
            reasons.append(f"该章有 {pending[root]} 道有效待复习题，可结合原错题阅读")
        if level:
            reasons.append(
                "符合所选难度" if level == difficulty else "同章延伸资料，难度与所选不同"
            )
        else:
            reasons.append("上传资料未评定难度，请自行选择阅读深度")
        return reasons

    for resource in session.scalars(
        select(Resource).where(Resource.is_active.is_(True), Resource.chapter_id.in_(related))
    ):
        candidates.append(
            {
                "id": str(resource.id),
                "kind": "external",
                "title": resource.title,
                "description": resource.description,
                "url": resource.url,
                "language": resource.language,
                "difficulty": resource.difficulty,
                "chapter_id": str(resource.chapter_id),
                "source_info": resource.source_info,
                "reasons": describe(resource.chapter_id, resource.difficulty),
            }
        )

    # One current chunk per readable ready document; exclude all historical revisions.
    effective_point = func.coalesce(DocumentChunk.chapter_id, Document.chapter_id)
    eligible = (
        select(
            DocumentChunk.id.label("chunk_id"),
            effective_point.label("point_id"),
            func.row_number()
            .over(partition_by=Document.id, order_by=DocumentChunk.position)
            .label("position"),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(KnowledgeBase)
        .where(
            readable_bases(user_id),
            Document.status == "ready",
            DocumentChunk.index_revision == Document.index_revision,
        )
    )
    if target:
        eligible = eligible.where(effective_point.in_(related))
    ranked = eligible.subquery()
    order = {point.id: pending[chapter(point.id)] for point in points}
    rows = session.execute(
        select(Document, DocumentChunk, ranked.c.point_id)
        .join(DocumentChunk, DocumentChunk.document_id == Document.id)
        .join(ranked, ranked.c.chunk_id == DocumentChunk.id)
        .where(ranked.c.position == 1)
        .order_by(
            case(order, value=ranked.c.point_id, else_=0).desc(),
            Document.updated_at.desc(),
            Document.id,
        )
        .limit(24)
    ).all()
    for document, chunk, identifier in rows:
        candidates.append(
            {
                "id": str(chunk.id),
                "kind": "document",
                "title": document.filename,
                "description": chunk.text[:240],
                "url": f"/api/v1/documents/{document.id}/file",
                "document_id": str(document.id),
                "chunk_id": str(chunk.id),
                "chapter_id": str(identifier) if identifier else None,
                "difficulty": None,
                "language": "原文",
                "source_info": document.source_info,
                "heading": chunk.heading,
                "page_number": chunk.page_number,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "reasons": describe(identifier, None),
            }
        )

    def priority(item):
        identifier = next((key for key in by_id if str(key) == item["chapter_id"]), None)
        return (
            -pending[chapter(identifier)],
            abs(LEVELS.get(item["difficulty"], LEVELS[difficulty]) - LEVELS[difficulty]),
            item["kind"] == "external",
            item["title"],
            item["id"],
        )

    candidates.sort(key=priority)
    selected, urls = [], set()
    for candidate in candidates:
        if candidate["url"] in urls:
            continue
        selected.append(candidate)
        urls.add(candidate["url"])
        if len(selected) == limit:
            break
    return {
        "items": selected,
        "difficulty": difficulty,
        "basis": "按章节匹配、有效待复习题和所选难度排序；难度优先匹配，不据此判断掌握程度。"
        "本地资料只来自本人可访问的就绪片段，外链由维护者登记，未实时联网生成。",
    }
