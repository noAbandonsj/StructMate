from copy import deepcopy

from sqlalchemy import func, select

from capstone.core.errors import ApiError
from capstone.db.models import Message
from capstone.db.session import write_transaction
from capstone.services.conversations import get_conversation


def completed_pairs(session, conversation_id):
    rows = session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.sequence)
    ).all()
    users = {row.id: row for row in rows if row.role == "user" and row.status == "completed"}
    answers = {}
    for row in rows:
        if (
            row.role == "assistant"
            and row.status == "completed"
            and row.reply_to_message_id in users
        ):
            answers[row.reply_to_message_id] = row
    result = []
    for user in users.values():
        if user.id not in answers:
            continue
        answer = answers[user.id]
        for message in (user, answer):
            result.append(
                {
                    "id": str(message.id),
                    "sequence": message.sequence,
                    "role": message.role,
                    "content": message.content,
                    "updated_at": message.updated_at.isoformat(),
                }
            )
    return result


def queue_summary(session, identifier, user_id, request_id, available):
    with write_transaction(session):
        conversation = get_conversation(session, identifier, user_id)
        previous = conversation.summary_data or {}
        if previous.get("request_id") == request_id:
            return conversation, False
        if request_id in previous.get("used_request_ids", []):
            raise ApiError(
                409, "SUMMARY_REQUEST_SUPERSEDED", "该请求已有更新的总结，请查看当前总结。"
            )
        if previous.get("status") == "generating":
            raise ApiError(409, "SUMMARY_BUSY", "总结正在生成，请稍候。")
        if not available:
            raise ApiError(503, "GENERATION_NOT_CONFIGURED", "生成模型尚未接通，暂不能总结会话。")
        snapshot = completed_pairs(session, identifier)
        if not snapshot:
            raise ApiError(409, "SUMMARY_EMPTY", "请先完成至少一轮答疑。")
        # Keep the last successful summary readable until its replacement succeeds.
        conversation.summary_data = {
            "status": "generating",
            "request_id": request_id,
            "used_request_ids": [*previous.get("used_request_ids", []), request_id],
            "content": previous.get("content", ""),
            "generated_at": previous.get("generated_at"),
            "cutoff_sequence": previous.get("cutoff_sequence", 0),
            "cutoff_at": previous.get("cutoff_at"),
            "message_count": previous.get("message_count", 0),
            "target_sequence": max(message["sequence"] for message in snapshot),
            "target_cutoff_at": max(snapshot, key=lambda message: message["sequence"])[
                "updated_at"
            ],
            "target_message_count": len(snapshot),
            "snapshot": snapshot,
            "error_code": None,
            "error_message": None,
        }
    return conversation, True


def summary_info(session, conversation):
    data = conversation.summary_data or {}
    latest = (
        session.scalar(
            select(func.max(Message.sequence)).where(
                Message.conversation_id == conversation.id,
                Message.role == "assistant",
                Message.status == "completed",
            )
        )
        or 0
    )
    return {
        "status": data.get("status", "empty"),
        "client_request_id": data.get("request_id"),
        "content": data.get("content", ""),
        "generated_at": data.get("generated_at"),
        "cutoff_sequence": data.get("cutoff_sequence", 0),
        "cutoff_at": data.get("cutoff_at"),
        "message_count": data.get("message_count", 0),
        "target_sequence": data.get("target_sequence"),
        "has_newer_messages": latest > data.get("cutoff_sequence", 0),
        "error_code": data.get("error_code"),
        "error_message": data.get("error_message"),
    }


def fail_summary(conversation, code, message):
    data = deepcopy(conversation.summary_data)
    data["status"], data["error_code"], data["error_message"] = "failed", code, message
    data.pop("snapshot", None)
    conversation.summary_data = data
