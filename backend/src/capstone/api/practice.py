from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select

from capstone.api.knowledge import PageNumber, PageSize
from capstone.api.schemas import Page
from capstone.core.auth import (
    AuthenticatedSession,
    DatabaseSession,
    no_store,
    require_csrf,
    require_origin,
)
from capstone.core.knowledge import readable_bases
from capstone.core.practice import (
    FeedbackInput,
    PracticeInput,
    ReviewInput,
    SubmitInput,
    SubmitPracticeInput,
)
from capstone.db.models import (
    Document,
    KnowledgeBase,
    PracticeItem,
    PracticeSession,
    Question,
    WrongQuestion,
)
from capstone.services.performance import performance, selected_points
from capstone.services.practice import (
    attempt_info,
    create_practice,
    create_review,
    feedback,
    get_practice,
    get_wrong,
    item_info,
    practice_info,
    submit,
    submit_practice,
    use_hint,
    wrong_info,
)

router = APIRouter(tags=["practice"], dependencies=[Depends(no_store)])
writes = [Depends(require_origin)]


@router.get("/practice-sessions/config")
def config(current: AuthenticatedSession, request: Request):
    return {
        "generation_available": request.app.state.generation_service.available,
        "default_count": 5,
        "max_count": 20,
    }


@router.get("/learning/performance")
def learning_performance(current: AuthenticatedSession, session: DatabaseSession):
    return performance(session, current.user_id)


@router.get("/practice-sessions/materials")
def materials(
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
):
    predicate = (readable_bases(current.user_id), Document.status == "ready")
    rows = session.execute(
        select(Document, KnowledgeBase.kind)
        .join(KnowledgeBase)
        .where(*predicate)
        .order_by(Document.updated_at.desc(), Document.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {"id": str(document.id), "filename": document.filename, "kind": kind}
            for document, kind in rows
        ],
        "total": session.scalar(
            select(func.count()).select_from(Document).join(KnowledgeBase).where(*predicate)
        ),
        "page": page,
        "page_size": page_size,
    }


@router.post("/practice-sessions", status_code=202, dependencies=writes)
def new_practice(
    data: PracticeInput, current: AuthenticatedSession, session: DatabaseSession, request: Request
):
    require_csrf(request, current)
    practice, generate = create_practice(
        session, current.user_id, data, request.app.state.generation_service.available
    )
    result = practice_info(session, practice)
    if generate:
        request.app.state.practice_runner.submit(practice.id)
    return result


@router.get("/practice-sessions", response_model=Page[dict])
def practice_list(
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
):
    predicate = PracticeSession.user_id == current.user_id
    records = session.scalars(
        select(PracticeSession)
        .where(predicate)
        .order_by(PracticeSession.created_at.desc(), PracticeSession.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page(
        items=[practice_info(session, record) for record in records],
        page=page,
        page_size=page_size,
        total=session.scalar(select(func.count()).select_from(PracticeSession).where(predicate)),
    )


@router.get("/practice-sessions/{identifier}")
def practice_detail(identifier: UUID, current: AuthenticatedSession, session: DatabaseSession):
    return practice_info(session, get_practice(session, identifier, current.user_id))


@router.get("/practice-sessions/{identifier}/items", response_model=Page[dict])
def practice_items(
    identifier: UUID,
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
):
    get_practice(session, identifier, current.user_id)
    predicate = PracticeItem.practice_session_id == identifier
    items = session.scalars(
        select(PracticeItem)
        .where(predicate)
        .order_by(PracticeItem.position)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page(
        items=[item_info(session, item) for item in items],
        page=page,
        page_size=page_size,
        total=session.scalar(select(func.count()).select_from(PracticeItem).where(predicate)),
    )


@router.post("/practice-sessions/{identifier}/submit", status_code=201, dependencies=writes)
def submit_all(
    identifier: UUID,
    data: SubmitPracticeInput,
    current: AuthenticatedSession,
    session: DatabaseSession,
    request: Request,
):
    require_csrf(request, current)
    return submit_practice(session, identifier, current.user_id, data)


@router.post("/practice-items/{identifier}/hint", dependencies=writes)
def hint(
    identifier: UUID, current: AuthenticatedSession, session: DatabaseSession, request: Request
):
    require_csrf(request, current)
    return use_hint(session, identifier, current.user_id)


@router.post("/practice-items/{identifier}/attempts", status_code=201, dependencies=writes)
def attempt(
    identifier: UUID,
    data: SubmitInput,
    current: AuthenticatedSession,
    session: DatabaseSession,
    request: Request,
):
    require_csrf(request, current)
    return attempt_info(session, submit(session, identifier, current.user_id, data))


@router.post("/practice-items/{identifier}/feedback", dependencies=writes)
def item_feedback(
    identifier: UUID,
    data: FeedbackInput,
    current: AuthenticatedSession,
    session: DatabaseSession,
    request: Request,
):
    require_csrf(request, current)
    return feedback(session, identifier, current.user_id, data.reason)


@router.get("/wrong-questions", response_model=Page[dict])
def wrong_list(
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    status: Literal["pending", "consolidated"] | None = None,
    knowledge_point_id: UUID | None = None,
    search: str = Query(default="", max_length=500),
):
    predicates = [WrongQuestion.user_id == current.user_id, Question.is_valid.is_(True)]
    if status:
        predicates.append(WrongQuestion.status == status)
    if search.strip():
        predicates.append(
            or_(
                Question.source_info["topic"].as_string().contains(search.strip(), autoescape=True),
                Question.content["stem"].as_string().contains(search.strip(), autoescape=True),
            )
        )
    if knowledge_point_id:
        predicates.append(
            Question.knowledge_point_id.in_(
                [point.id for point in selected_points(session, [knowledge_point_id])]
            )
        )
    query = select(WrongQuestion).join(Question).where(*predicates)
    rows = session.scalars(
        query.order_by(WrongQuestion.updated_at.desc(), WrongQuestion.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page(
        items=[wrong_info(session, row) for row in rows],
        page=page,
        page_size=page_size,
        total=session.scalar(
            select(func.count()).select_from(WrongQuestion).join(Question).where(*predicates)
        ),
    )


@router.get("/wrong-questions/{identifier}")
def wrong_detail(identifier: UUID, current: AuthenticatedSession, session: DatabaseSession):
    return wrong_info(
        session, get_wrong(session, identifier, current.user_id), include_history=True
    )


@router.post("/wrong-questions/review-sessions", status_code=202, dependencies=writes)
def review(
    data: ReviewInput, current: AuthenticatedSession, session: DatabaseSession, request: Request
):
    require_csrf(request, current)
    return practice_info(session, create_review(session, current.user_id, data))
