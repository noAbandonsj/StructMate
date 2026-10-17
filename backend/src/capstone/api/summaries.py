from uuid import UUID

from fastapi import APIRouter, Depends, Request
from starlette.responses import PlainTextResponse

from capstone.api.conversations import RequestKey
from capstone.core.auth import (
    AuthenticatedSession,
    DatabaseSession,
    no_store,
    require_csrf,
    require_origin,
)
from capstone.core.errors import ApiError
from capstone.services.conversations import get_conversation
from capstone.services.summaries import queue_summary, summary_info

router = APIRouter(tags=["summaries"], dependencies=[Depends(no_store)])


@router.post(
    "/conversations/{identifier}/summary", status_code=202, dependencies=[Depends(require_origin)]
)
def generate(
    identifier: UUID,
    data: RequestKey,
    current: AuthenticatedSession,
    session: DatabaseSession,
    request: Request,
):
    require_csrf(request, current)
    conversation, fresh = queue_summary(
        session,
        identifier,
        current.user_id,
        data.client_request_id,
        request.app.state.generation_service.available,
    )
    result = summary_info(session, conversation)
    if fresh:
        request.app.state.summary_runner.submit(identifier)
    return result


@router.get("/conversations/{identifier}/summary")
def summary(identifier: UUID, current: AuthenticatedSession, session: DatabaseSession):
    return summary_info(session, get_conversation(session, identifier, current.user_id))


@router.get("/conversations/{identifier}/summary/export")
def export(identifier: UUID, current: AuthenticatedSession, session: DatabaseSession):
    conversation = get_conversation(session, identifier, current.user_id)
    info = summary_info(session, conversation)
    if not info["content"]:
        raise ApiError(409, "SUMMARY_NOT_READY", "还没有可导出的总结。")
    content = (
        f"# {conversation.title} · 学习总结\n\n"
        f"生成时间：{info['generated_at']}\n\n"
        f"覆盖已完成问答 {info['message_count']} 条消息，截止消息序号 {info['cutoff_sequence']}。"
        f"消息截止时间：{info['cutoff_at']}。"
        "资料不足、失败、取消和未完成问答不参与新总结，讨论不代表掌握。\n\n"
        + info["content"]
        + "\n"
    )
    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="summary-{identifier}.md"',
        },
    )
