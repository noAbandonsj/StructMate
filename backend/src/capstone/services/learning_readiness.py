from sqlalchemy import func, select

from capstone.core.knowledge import readable_bases
from capstone.db.models import Document, KnowledgeBase
from capstone.services.retrieval import document_predicate


def ready_document_count(session, user_id, scope="combined", document_ids=None):
    return session.scalar(
        select(func.count())
        .select_from(Document)
        .join(KnowledgeBase)
        .where(*document_predicate(user_id, scope, document_ids or []))
    )


def learning_readiness(
    session, user_id, generation_available, embedding_available, conversation=None
):
    counts = dict(
        session.execute(
            select(KnowledgeBase.kind, func.count())
            .select_from(Document)
            .join(KnowledgeBase)
            .where(readable_bases(user_id), Document.status == "ready")
            .group_by(KnowledgeBase.kind)
        ).all()
    )
    course, personal = counts.get("course", 0), counts.get("personal", 0)
    return {
        "generation_available": generation_available,
        "embedding_available": embedding_available,
        "course_ready_count": course,
        "personal_ready_count": personal,
        "ready_document_count": (
            ready_document_count(session, user_id, conversation.scope, conversation.document_ids)
            if conversation is not None
            else course + personal
        ),
    }
