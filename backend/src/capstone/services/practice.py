import json
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from capstone.core.errors import ApiError
from capstone.db.models import (
    Attempt,
    PracticeItem,
    PracticeSession,
    Question,
    WrongQuestion,
    utc_now,
)
from capstone.db.session import write_transaction
from capstone.services.chapters import require_chapter
from capstone.services.conversations import get_conversation
from capstone.services.documents import get_document
from capstone.services.practice_serialization import item_info, practice_info, snapshot


def get_practice(session, identifier, user_id):
    record = session.scalar(
        select(PracticeSession).where(
            PracticeSession.id == identifier, PracticeSession.user_id == user_id
        )
    )
    if record is None:
        raise ApiError(404, "PRACTICE_NOT_FOUND", "练习不存在或不可访问。")
    return record


def get_item(session, identifier, user_id):
    record = session.scalar(
        select(PracticeItem)
        .join(PracticeSession)
        .where(PracticeItem.id == identifier, PracticeSession.user_id == user_id)
    )
    if record is None:
        raise ApiError(404, "PRACTICE_ITEM_NOT_FOUND", "题目不存在或不可访问。")
    return record


def get_wrong(session, identifier, user_id):
    record = session.scalar(
        select(WrongQuestion).where(
            WrongQuestion.id == identifier, WrongQuestion.user_id == user_id
        )
    )
    if record is None:
        raise ApiError(404, "WRONG_QUESTION_NOT_FOUND", "错题不存在或不可访问。")
    return record


def distribute(session, practice, questions):
    for position, question in enumerate(questions, 1):
        session.add(
            PracticeItem(
                practice_session_id=practice.id,
                question_id=question.id,
                position=position,
                snapshot=snapshot(question),
            )
        )
    practice.actual_count = len(questions)
    practice.status = "ready" if questions else "failed"


def request_digest(data):
    return sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def existing_request(session, user_id, request_id, digest):
    previous = session.scalar(
        select(PracticeSession).where(
            PracticeSession.user_id == user_id, PracticeSession.request_id == request_id
        )
    )
    if previous and previous.request_hash != digest:
        raise ApiError(409, "REQUEST_CONFLICT", "请求标识已用于不同练习设置。")
    return previous


def reference_documents(session, user_id, identifiers, chapter_id=None):
    result = []
    for identifier in sorted(set(identifiers), key=str):
        document = get_document(session, identifier, user_id)
        if document.status != "ready":
            raise ApiError(
                409, "PRACTICE_DOCUMENT_NOT_READY", "所选参考资料已删除或尚未就绪，请重新选择。"
            )
        if chapter_id and document.chapter_id not in {None, chapter_id}:
            raise ApiError(422, "MATERIAL_CHAPTER_MISMATCH", "参考资料属于其他章节，请重新选择。")
        result.append(
            {
                "id": str(document.id),
                "filename": document.filename,
                "index_revision": document.index_revision,
                "content_hash": document.content_hash,
            }
        )
    return result


def create_practice(session, user_id, data, generation_available):
    settings = data.model_dump(mode="json", exclude={"client_request_id"})
    settings["document_ids"] = sorted(set(settings["document_ids"]))
    digest = request_digest(settings)
    with write_transaction(session):
        if previous := existing_request(session, user_id, data.client_request_id, digest):
            return previous, False
        if data.source_conversation_id:
            get_conversation(session, data.source_conversation_id, user_id)
        chapter = require_chapter(session, data.chapter_id)
        settings["reference_documents"] = reference_documents(
            session, user_id, data.document_ids, chapter.id
        )
        practice = PracticeSession(
            user_id=user_id,
            mode="chapter",
            settings=settings,
            source_conversation_id=data.source_conversation_id,
            request_id=data.client_request_id,
            request_hash=digest,
        )
        session.add(practice)
        session.flush()
        if not generation_available:
            practice.status, practice.error_code = "failed", "GENERATION_NOT_CONFIGURED"
            practice.error_message = "生成模型尚未接通，设置已保留，请联系管理员配置后重试。"
        return practice, generation_available


def create_review(session, user_id, data):
    identifiers = sorted({str(value) for value in data.wrong_question_ids})
    digest = request_digest({"review": identifiers})
    with write_transaction(session):
        if previous := existing_request(session, user_id, data.client_request_id, digest):
            return previous
        questions = []
        for identifier in identifiers:
            wrong = get_wrong(session, UUID(identifier), user_id)
            question = session.get(Question, wrong.question_id)
            if not question.is_valid:
                raise ApiError(409, "QUESTION_INVALID", "包含已停用的错题，请刷新后重新选择。")
            if question.owner_id != user_id:
                raise ApiError(404, "WRONG_QUESTION_NOT_FOUND", "错题不存在或不可访问。")
            questions.append(question)
        practice = PracticeSession(
            user_id=user_id,
            mode="review",
            settings={"wrong_question_ids": identifiers, "count": len(questions)},
            request_id=data.client_request_id,
            request_hash=digest,
        )
        session.add(practice)
        session.flush()
        distribute(session, practice, questions)
    return practice


def _record_answer(session, item, practice, user_id, answer, request_id):
    seen = session.scalar(
        select(Attempt.id)
        .where(Attempt.user_id == user_id, Attempt.question_id == item.question_id)
        .limit(1)
    )
    category = (
        "review"
        if practice.mode == "review"
        else "repeat"
        if seen
        else "first_hinted"
        if item.hinted_at
        else "first_independent"
    )
    now = utc_now()
    attempt = Attempt(
        user_id=user_id,
        practice_item_id=item.id,
        question_id=item.question_id,
        request_id=request_id,
        answer=answer,
        is_correct=answer == item.snapshot["answer"],
        hinted=item.hinted_at is not None,
        category=category,
        created_at=now,
    )
    session.add(attempt)
    wrong = session.scalar(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id, WrongQuestion.question_id == item.question_id
        )
    )
    if not attempt.is_correct:
        if wrong is None:
            wrong = WrongQuestion(user_id=user_id, question_id=item.question_id)
            session.add(wrong)
        wrong.status, wrong.correct_days, wrong.last_correct_date = "pending", 0, None
    elif wrong is not None:
        today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
        if wrong.last_correct_date != today:
            wrong.correct_days = min(2, wrong.correct_days + 1)
            wrong.last_correct_date = today
        wrong.status = "consolidated" if wrong.correct_days >= 2 else "pending"
    if wrong:
        wrong.updated_at = now
    session.flush()
    return attempt


def submit_practice(session, identifier, user_id, data):
    with write_transaction(session):
        practice = get_practice(session, identifier, user_id)
        if practice.status not in {"ready", "completed"}:
            raise ApiError(409, "PRACTICE_NOT_READY", "本组练习尚未就绪，暂不能提交。")
        items = session.scalars(
            select(PracticeItem)
            .join(Question)
            .where(PracticeItem.practice_session_id == practice.id, Question.is_valid.is_(True))
            .order_by(PracticeItem.position)
        ).all()
        answers = {item.practice_item_id: item.answer for item in data.answers}
        if not items or set(answers) != {item.id for item in items}:
            raise ApiError(422, "PRACTICE_ANSWERS_INCOMPLETE", "请完成本组全部有效题目后统一提交。")
        previous_attempts = {
            attempt.practice_item_id: attempt
            for attempt in session.scalars(
                select(Attempt).where(Attempt.practice_item_id.in_([item.id for item in items]))
            )
        }
        # Validate every answer before writing any attempts or wrong-question state.
        for item in items:
            if answers[item.id] not in {option["key"] for option in item.snapshot["options"]}:
                raise ApiError(422, "ANSWER_INVALID", "部分答案无效，请检查后重新提交。")
            previous = previous_attempts.get(item.id)
            if previous is not None and previous.answer != answers[item.id]:
                raise ApiError(
                    409, "ALREADY_SUBMITTED", "本组包含已提交的答案，请刷新后查看原结果。"
                )
        for item in items:
            if item.id in previous_attempts:
                continue
            _record_answer(
                session, item, practice, user_id, answers[item.id], data.client_request_id
            )
        if practice.status != "completed":
            practice.status, practice.completed_at = "completed", utc_now()
        return {
            "practice": practice_info(session, practice),
            "items": [
                item_info(session, item)
                for item in session.scalars(
                    select(PracticeItem)
                    .where(PracticeItem.practice_session_id == practice.id)
                    .order_by(PracticeItem.position)
                )
            ],
        }


def use_hint(session, identifier, user_id):
    with write_transaction(session):
        item = get_item(session, identifier, user_id)
        if session.scalar(select(Attempt.id).where(Attempt.practice_item_id == item.id)):
            raise ApiError(409, "ALREADY_SUBMITTED", "这道题已提交，可直接查看解析。")
        if not session.get(Question, item.question_id).is_valid:
            raise ApiError(409, "QUESTION_INVALID", "此题已停用。")
        if item.hinted_at is None:
            item.hinted_at = utc_now()
        hint = item.snapshot["hint"]
    return {"hint": hint, "hinted": True}
