from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from starlette.responses import PlainTextResponse

from capstone.api.conversations import RequestKey
from capstone.api.schemas import Page, PageNumber, PageSize
from capstone.core.auth import (
    AuthenticatedSession,
    DatabaseSession,
    no_store,
    require_csrf,
    require_origin,
)
from capstone.db.models import Conversation, LearningReport, PracticeSession
from capstone.services.learning_stats import learning_stats
from capstone.services.practice_serialization import practice_info
from capstone.services.reports import create_report, get_report, report_info, report_markdown

router = APIRouter(tags=["reports"], dependencies=[Depends(no_store)])


class ReportInput(RequestKey):
    from_date: date | None = None
    to_date: date | None = None


@router.get("/learning/stats")
def stats(
    current: AuthenticatedSession,
    session: DatabaseSession,
    from_date: date | None = None,
    to_date: date | None = None,
):
    return learning_stats(session, current.user_id, from_date, to_date)


@router.get("/learning/overview")
def overview(current: AuthenticatedSession, session: DatabaseSession, request: Request):
    conversations = session.scalars(
        select(Conversation)
        .where(Conversation.user_id == current.user_id, Conversation.archived.is_(False))
        .order_by(Conversation.updated_at.desc())
        .limit(5)
    ).all()
    practices = session.scalars(
        select(PracticeSession)
        .where(PracticeSession.user_id == current.user_id)
        .order_by(PracticeSession.created_at.desc())
        .limit(5)
    ).all()
    return {
        "stats": learning_stats(session, current.user_id),
        "readiness": {"generation_available": request.app.state.generation_service.available},
        "recent_conversations": [
            {"id": item.id, "title": item.title, "updated_at": item.updated_at}
            for item in conversations
        ],
        "recent_practices": [practice_info(session, item) for item in practices],
    }


@router.post("/reports", status_code=202, dependencies=[Depends(require_origin)])
def create(
    data: ReportInput, current: AuthenticatedSession, session: DatabaseSession, request: Request
):
    require_csrf(request, current)
    report, generate = create_report(
        session, current.user_id, data, request.app.state.generation_service.available
    )
    result = report_info(report)
    if generate:
        request.app.state.report_runner.submit(report.id)
    return result


@router.get("/reports", response_model=Page[dict])
def reports(
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
):
    predicate = LearningReport.user_id == current.user_id
    records = session.scalars(
        select(LearningReport)
        .where(predicate)
        .order_by(LearningReport.created_at.desc(), LearningReport.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page(
        items=[report_info(record) for record in records],
        page=page,
        page_size=page_size,
        total=session.scalar(select(func.count()).select_from(LearningReport).where(predicate)),
    )


@router.get("/reports/{identifier}")
def detail(identifier: UUID, current: AuthenticatedSession, session: DatabaseSession):
    return report_info(get_report(session, identifier, current.user_id))


@router.get("/reports/{identifier}/export")
def export(identifier: UUID, current: AuthenticatedSession, session: DatabaseSession):
    report = get_report(session, identifier, current.user_id)
    return PlainTextResponse(
        report_markdown(report),
        media_type="text/markdown",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="report-{identifier}.md"',
        },
    )
