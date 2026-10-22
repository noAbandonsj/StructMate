import json
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select

from capstone.core.errors import ApiError
from capstone.db.models import (
    Conversation,
    Document,
    KnowledgeBase,
    Message,
    utc_now,
)
from capstone.db.session import write_transaction
from capstone.services.chapters import require_chapter
from capstone.services.learning_readiness import ready_document_count
from capstone.services.retrieval import document_predicate


def get_conversation(session, identifier, user_id):
    record = session.scalar(
        select(Conversation).where(Conversation.id == identifier, Conversation.user_id == user_id)
    )
    if record is None:
        raise ApiError(404, "CONVERSATION_NOT_FOUND", "会话不存在或不可访问。")
    return record


def get_message(session, identifier, user_id):
    record = session.scalar(
        select(Message)
        .join(Conversation)
        .where(Message.id == identifier, Conversation.user_id == user_id)
    )
    if record is None:
        raise ApiError(404, "MESSAGE_NOT_FOUND", "消息不存在或不可访问。")
    return record


def validate_scope(session, user_id, scope, identifiers, point_id):
    if point_id is not None:
        require_chapter(session, point_id)
    if identifiers:
        found = set(
            session.scalars(
                select(Document.id)
                .join(KnowledgeBase)
                .where(*document_predicate(user_id, scope, identifiers))
            )
        )
        if found != {UUID(str(identifier)) for identifier in identifiers}:
            raise ApiError(404, "DOCUMENT_NOT_READY", "所选资料尚未就绪或不可访问，请重新选择。")


def create_conversation(session, user_id, data):
    with write_transaction(session):
        validate_scope(session, user_id, data.scope, data.document_ids, data.chapter_id)
        record = Conversation(user_id=user_id, **data.model_dump())
        session.add(record)
    return record


def update_conversation(session, identifier, user_id, data):
    with write_transaction(session):
        record = get_conversation(session, identifier, user_id)
        changes = data.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(record, key, value)
    return record


def queue_answer(session, identifier, user_id, data, available, retry_id=None):
    # Serialize idempotency, sequence allocation and the active-answer check.
    with write_transaction(session):
        conversation = get_conversation(session, identifier, user_id)
        digest = sha256(
            json.dumps(
                {"retry": str(retry_id)} if retry_id else {"content": data.content},
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        previous = session.scalar(
            select(Message).where(
                Message.conversation_id == identifier, Message.request_id == data.client_request_id
            )
        )
        if previous:
            if previous.request_hash != digest:
                raise ApiError(409, "REQUEST_CONFLICT", "请求标识已用于不同内容。")
            return previous, False
        if conversation.archived:
            raise ApiError(409, "CONVERSATION_ARCHIVED", "会话已归档，请恢复后继续学习。")
        if session.scalar(
            select(Message.id).where(
                Message.conversation_id == identifier, Message.status == "generating"
            )
        ):
            raise ApiError(409, "CONVERSATION_BUSY", "已有回答正在生成，请等待或取消。")
        latest = (
            session.scalar(
                select(func.max(Message.sequence)).where(Message.conversation_id == identifier)
            )
            or 0
        )
        if retry_id:
            original = get_message(session, retry_id, user_id)
            if (
                original.conversation_id != identifier
                or original.sequence != latest
                or original.role != "assistant"
                or original.status not in ("failed", "cancelled")
            ):
                raise ApiError(
                    409, "RETRY_NOT_LATEST", "仅能重试最近失败或取消的回答，请重新提问。"
                )
            question_id, snapshot = (
                original.reply_to_message_id,
                original.scope_snapshot,
            )
        else:
            question = Message(
                conversation_id=identifier,
                sequence=latest + 1,
                role="user",
                content=data.content,
                status="completed",
            )
            session.add(question)
            session.flush()
            question_id = question.id
            snapshot = {"scope": conversation.scope, "document_ids": conversation.document_ids}
            latest += 1
        if not available:
            raise ApiError(
                503, "MODELS_NOT_CONFIGURED", "生成模型或向量模型尚未接通，请配置后重试。"
            )
        if not ready_document_count(session, user_id, snapshot["scope"], snapshot["document_ids"]):
            raise ApiError(
                409,
                "NO_READY_MATERIALS",
                "当前资料范围没有可用于学习的资料。请补充就绪资料，或先做 AI 练习。",
            )
        answer = Message(
            conversation_id=identifier,
            sequence=latest + 1,
            role="assistant",
            reply_to_message_id=question_id,
            scope_snapshot=snapshot,
            request_id=data.client_request_id,
            request_hash=digest,
            status="generating",
        )
        session.add(answer)
        conversation.updated_at = utc_now()
        if conversation.title == "新的学习" and not retry_id:
            conversation.title = data.content[:40]
    return answer, True


def message_info(session, message):
    citations = []
    for citation in message.citations:
        document = session.get(Document, UUID(citation["document_id"]))
        citations.append(
            {**citation, "source_deleted": document is None or document.status == "deleted"}
        )
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sequence": message.sequence,
        "role": message.role,
        "content": message.content,
        "reply_to_message_id": message.reply_to_message_id,
        "status": message.status,
        "answer_outcome": message.answer_outcome,
        "citations": citations,
        "error_code": message.error_code,
        "error_message": message.error_message,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
    }
