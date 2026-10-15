import asyncio
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from capstone.api.knowledge import PageNumber, PageSize
from capstone.api.schemas import Page
from capstone.core.auth import (
    AuthenticatedSession,
    DatabaseSession,
    load_session,
    no_store,
    require_csrf,
    require_origin,
)
from capstone.core.errors import ApiError
from capstone.db.models import Conversation, Message
from capstone.db.session import write_transaction
from capstone.services.conversations import (
    create_conversation,
    get_conversation,
    get_message,
    message_info,
    queue_answer,
    update_conversation,
)

router = APIRouter(tags=["conversations"], dependencies=[Depends(no_store)])
write_dependencies = [Depends(require_origin)]
Scope = Literal["combined", "course", "personal"]
Intent = Literal["explain", "hint", "example"]


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="新的学习", min_length=1, max_length=100)
    scope: Scope = "combined"
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    knowledge_point_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def trim_title(cls, value):
        if not value.strip():
            raise ValueError("标题不能为空")
        return value.strip()

    def model_dump(self, **kwargs):
        result = super().model_dump(**kwargs)
        result["document_ids"] = [str(identifier) for identifier in self.document_ids]
        return result


class ConversationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default=None, min_length=1, max_length=100)
    scope: Scope = None
    document_ids: list[UUID] = Field(default=None, max_length=100)
    knowledge_point_id: UUID | None = None
    archived: bool = None

    @model_validator(mode="after")
    def reject_null(self):
        for field in self.model_fields_set - {"knowledge_point_id"}:
            if getattr(self, field) is None:
                raise ValueError("设置值不能为空")
        if "title" in self.model_fields_set and not self.title.strip():
            raise ValueError("标题不能为空")
        return self

    def model_dump(self, **kwargs):
        result = super().model_dump(**kwargs)
        if "document_ids" in result:
            result["document_ids"] = [str(identifier) for identifier in self.document_ids]
        if "title" in result:
            result["title"] = result["title"].strip()
        return result


class ConversationInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    scope: Scope
    document_ids: list[str]
    knowledge_point_id: UUID | None
    archived: bool
    created_at: datetime
    updated_at: datetime


class RequestKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class SendInput(RequestKey):
    content: str = Field(min_length=1, max_length=4000)
    intent: Intent = "explain"

    @field_validator("content")
    @classmethod
    def trim_content(cls, value):
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


@router.get("/conversations/config")
def chat_config(request: Request, current: AuthenticatedSession):
    return {
        "generation_available": request.app.state.generation_service.available,
        "embedding_available": request.app.state.embedding_service.available,
    }


@router.get("/conversations", response_model=Page[ConversationInfo])
def conversations(
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    archived: bool = False,
):
    predicate = (Conversation.user_id == current.user_id) & (Conversation.archived == archived)
    return Page(
        items=[
            ConversationInfo.model_validate(item)
            for item in session.scalars(
                select(Conversation)
                .where(predicate)
                .order_by(Conversation.updated_at.desc(), Conversation.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ],
        total=session.scalar(select(func.count()).select_from(Conversation).where(predicate)),
        page=page,
        page_size=page_size,
    )


@router.post(
    "/conversations",
    status_code=201,
    response_model=ConversationInfo,
    dependencies=write_dependencies,
)
def new_conversation(
    data: ConversationInput,
    current: AuthenticatedSession,
    session: DatabaseSession,
    request: Request,
):
    require_csrf(request, current)
    return ConversationInfo.model_validate(create_conversation(session, current.user_id, data))


@router.get("/conversations/{identifier}", response_model=ConversationInfo)
def conversation(identifier: UUID, current: AuthenticatedSession, session: DatabaseSession):
    return ConversationInfo.model_validate(get_conversation(session, identifier, current.user_id))


@router.patch(
    "/conversations/{identifier}", response_model=ConversationInfo, dependencies=write_dependencies
)
def patch_conversation(
    identifier: UUID,
    data: ConversationPatch,
    current: AuthenticatedSession,
    session: DatabaseSession,
    request: Request,
):
    require_csrf(request, current)
    return ConversationInfo.model_validate(
        update_conversation(session, identifier, current.user_id, data)
    )


@router.get("/conversations/{identifier}/messages", response_model=Page[dict])
def messages(
    identifier: UUID,
    current: AuthenticatedSession,
    session: DatabaseSession,
    page: PageNumber = 1,
    page_size: PageSize = 100,
):
    get_conversation(session, identifier, current.user_id)
    predicate = Message.conversation_id == identifier
    return Page(
        items=[
            message_info(session, item)
            for item in session.scalars(
                select(Message)
                .where(predicate)
                .order_by(Message.sequence)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ],
        total=session.scalar(select(func.count()).select_from(Message).where(predicate)),
        page=page,
        page_size=page_size,
    )


def queued_response(message):
    return {
        "assistant_message_id": message.id,
        "user_message_id": message.reply_to_message_id,
        "stream_url": f"/api/v1/messages/{message.id}/events",
    }


@router.post(
    "/conversations/{identifier}/messages", status_code=202, dependencies=write_dependencies
)
def send(
    identifier: UUID,
    data: SendInput,
    current: AuthenticatedSession,
    session: DatabaseSession,
    request: Request,
):
    require_csrf(request, current)
    answer, fresh = queue_answer(
        session,
        identifier,
        current.user_id,
        data,
        request.app.state.generation_service.available
        and request.app.state.embedding_service.available,
    )
    result = queued_response(answer)
    if fresh:
        request.app.state.chat_runner.submit(answer.id)
    return result


@router.post("/messages/{identifier}/retry", status_code=202, dependencies=write_dependencies)
def retry(
    identifier: UUID,
    data: RequestKey,
    current: AuthenticatedSession,
    session: DatabaseSession,
    request: Request,
):
    require_csrf(request, current)
    conversation_id = get_message(session, identifier, current.user_id).conversation_id
    session.rollback()
    answer, fresh = queue_answer(
        session,
        conversation_id,
        current.user_id,
        data,
        request.app.state.generation_service.available
        and request.app.state.embedding_service.available,
        retry_id=identifier,
    )
    result = queued_response(answer)
    if fresh:
        request.app.state.chat_runner.submit(answer.id)
    return result


@router.post("/messages/{identifier}/cancel", dependencies=write_dependencies)
def cancel(
    identifier: UUID, current: AuthenticatedSession, session: DatabaseSession, request: Request
):
    require_csrf(request, current)
    with write_transaction(session):
        message = get_message(session, identifier, current.user_id)
        if message.role != "assistant":
            raise ApiError(409, "CANCEL_INVALID", "只能取消正在生成的回答。")
        if message.status == "generating":
            message.status = "cancelled"
    request.app.state.chat_runner.cancel(identifier)
    return message_info(session, message)


def stream_snapshot(request, identifier):
    with request.app.state.session_factory() as session:
        current = load_session(request, session)
        if current is None:
            return None
        return jsonable_encoder(
            message_info(session, get_message(session, identifier, current.user_id))
        )


@router.get("/messages/{identifier}/events")
def events(
    identifier: UUID, current: AuthenticatedSession, session: DatabaseSession, request: Request
):
    message = get_message(session, identifier, current.user_id)
    if message.role != "assistant":
        raise ApiError(409, "STREAM_INVALID", "这个消息不提供回答流。")
    session.rollback()

    async def stream():
        previous, heartbeat = None, 0
        while not await request.is_disconnected():
            snapshot = await run_in_threadpool(stream_snapshot, request, identifier)
            if snapshot is None:
                yield (
                    "event: failed\ndata: "
                    '{"code":"LOGIN_REQUIRED","message":"登录已失效，请重新登录。"}\n\n'
                )
                return
            if previous is None or not snapshot["content"].startswith(previous["content"]):
                yield "event: snapshot\ndata: " + json.dumps(snapshot, ensure_ascii=False) + "\n\n"
            else:
                delta = snapshot["content"][len(previous["content"]) :]
                if delta:
                    yield (
                        "event: delta\ndata: "
                        + json.dumps({"text": delta}, ensure_ascii=False)
                        + "\n\n"
                    )
                if snapshot["citations"] != previous["citations"]:
                    yield (
                        "event: citations\ndata: "
                        + json.dumps(snapshot["citations"], ensure_ascii=False)
                        + "\n\n"
                    )
            if snapshot["status"] != "generating":
                yield (
                    "event: "
                    + snapshot["status"]
                    + "\ndata: "
                    + json.dumps(snapshot, ensure_ascii=False)
                    + "\n\n"
                )
                return
            previous = snapshot
            heartbeat += 1
            if heartbeat % 60 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.15)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
