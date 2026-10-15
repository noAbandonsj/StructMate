import json
from copy import deepcopy
from hashlib import sha256
from secrets import SystemRandom
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from capstone.core.errors import ApiError
from capstone.db.models import (
    Attempt,
    Document,
    PracticeItem,
    PracticeSession,
    Question,
    WrongQuestion,
    utc_now,
)
from capstone.db.session import write_transaction
from capstone.services.conversations import get_conversation
from capstone.services.performance import performance, selected_points


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


def snapshot(question):
    return deepcopy(
        {
            **question.content,
            "source_type": question.source_type,
            "knowledge_point_id": str(question.knowledge_point_id),
            "difficulty": question.difficulty,
            "source_info": question.source_info,
        }
    )


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
    if not questions:
        practice.error_code, practice.error_message = (
            "BANK_EMPTY",
            "没有符合条件的题目，请调整知识点或难度。",
        )


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


def create_practice(session, user_id, data, generation_available):
    settings = data.model_dump(mode="json", exclude={"client_request_id"})
    settings["knowledge_point_ids"] = sorted(set(settings["knowledge_point_ids"]))
    digest = request_digest(settings)
    with write_transaction(session):
        if previous := existing_request(session, user_id, data.client_request_id, digest):
            return previous, False
        if data.source_conversation_id:
            get_conversation(session, data.source_conversation_id, user_id)
        points = selected_points(session, data.knowledge_point_ids)
        if not set(data.knowledge_point_ids).issubset({point.id for point in points}):
            raise ApiError(422, "KNOWLEDGE_POINT_INVALID", "所选知识点不存在。")
        practice = PracticeSession(
            user_id=user_id,
            mode=data.mode,
            question_source=data.question_source,
            settings=settings,
            source_conversation_id=data.source_conversation_id,
            request_id=data.client_request_id,
            request_hash=digest,
        )
        session.add(practice)
        session.flush()
        if data.question_source == "ai":
            if not generation_available:
                practice.status, practice.error_code = "failed", "GENERATION_NOT_CONFIGURED"
                practice.error_message = (
                    "生成模型尚未接通。设置已保留，可配置后重试，或主动切换题库。"
                )
            return practice, generation_available
        questions = session.scalars(
            select(Question).where(
                Question.source_type == "bank",
                Question.available.is_(True),
                Question.is_valid.is_(True),
                Question.difficulty == data.difficulty,
                Question.knowledge_point_id.in_([point.id for point in points]),
            )
        ).all()
        seen = set(session.scalars(select(Attempt.question_id).where(Attempt.user_id == user_id)))
        codes = {point.id: point.code for point in points}
        ranks = {
            item["code"]: index for index, item in enumerate(performance(session, user_id)["items"])
        }
        random = SystemRandom()
        questions.sort(
            key=lambda question: (
                ranks.get(codes[question.knowledge_point_id].split(".")[0], 99)
                if data.mode == "adaptive"
                else 0,
                question.id in seen,
                random.random(),
            )
        )
        distribute(session, practice, questions[: data.count])
        if practice.actual_count < data.count and practice.actual_count:
            practice.notice = (
                f"题库符合条件的题目不足 {data.count} 道，本组实际 {practice.actual_count} 道。"
            )
    return practice, False


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
            if question.owner_id is not None and question.owner_id != user_id:
                raise ApiError(404, "WRONG_QUESTION_NOT_FOUND", "错题不存在或不可访问。")
            questions.append(question)
        practice = PracticeSession(
            user_id=user_id,
            mode="review",
            question_source=None,
            settings={"wrong_question_ids": identifiers, "count": len(questions)},
            request_id=data.client_request_id,
            request_hash=digest,
        )
        session.add(practice)
        session.flush()
        distribute(session, practice, questions)
    return practice


def submit(session, identifier, user_id, data):
    with write_transaction(session):
        item = get_item(session, identifier, user_id)
        previous = session.scalar(select(Attempt).where(Attempt.practice_item_id == item.id))
        if previous:
            if previous.answer != data.answer:
                raise ApiError(409, "ALREADY_SUBMITTED", "这道题已提交，请查看原结果。")
            return previous
        question = session.get(Question, item.question_id)
        if not question.is_valid:
            raise ApiError(409, "QUESTION_INVALID", "此题已确认有误，不计分，请继续其他题目。")
        if data.answer not in {option["key"] for option in item.snapshot["options"]}:
            raise ApiError(422, "ANSWER_INVALID", "请选择题目提供的选项。")
        practice = get_practice(session, item.practice_session_id, user_id)
        seen = session.scalar(
            select(Attempt.id)
            .where(Attempt.user_id == user_id, Attempt.question_id == question.id)
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
            question_id=question.id,
            request_id=data.client_request_id,
            answer=data.answer,
            is_correct=data.answer == item.snapshot["answer"],
            hinted=item.hinted_at is not None,
            category=category,
            created_at=now,
        )
        session.add(attempt)
        wrong = session.scalar(
            select(WrongQuestion).where(
                WrongQuestion.user_id == user_id, WrongQuestion.question_id == question.id
            )
        )
        if not attempt.is_correct:
            if wrong is None:
                wrong = WrongQuestion(user_id=user_id, question_id=question.id)
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
        remaining = session.scalar(
            select(func.count())
            .select_from(PracticeItem)
            .join(Question)
            .outerjoin(Attempt, Attempt.practice_item_id == PracticeItem.id)
            .where(
                PracticeItem.practice_session_id == practice.id,
                Question.is_valid.is_(True),
                Attempt.id.is_(None),
            )
        )
        if remaining == 0:
            practice.status, practice.completed_at = "completed", now
    return attempt


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


def feedback(session, identifier, user_id, reason):
    with write_transaction(session):
        item = get_item(session, identifier, user_id)
        if not session.scalar(select(Attempt.id).where(Attempt.practice_item_id == item.id)):
            raise ApiError(409, "SUBMISSION_REQUIRED", "请先提交作答，再反馈题目问题。")
        if item.feedback and item.feedback["reason"] != reason:
            raise ApiError(409, "FEEDBACK_EXISTS", "该题反馈已保存，等待维护者核对。")
        if item.feedback is None:
            item.feedback = {"reason": reason, "created_at": utc_now().isoformat()}
    return item.feedback


def attempt_info(session, attempt, item=None):
    item = item or session.get(PracticeItem, attempt.practice_item_id)
    question = session.get(Question, attempt.question_id)
    wrong = session.scalar(
        select(WrongQuestion).where(
            WrongQuestion.user_id == attempt.user_id,
            WrongQuestion.question_id == attempt.question_id,
        )
    )
    return {
        "id": attempt.id,
        "practice_item_id": item.id,
        "answer": attempt.answer,
        "is_correct": attempt.is_correct,
        "hinted": attempt.hinted,
        "category": attempt.category,
        "is_valid": attempt.is_valid and question.is_valid,
        "created_at": attempt.created_at,
        "reference_answer": item.snapshot["answer"],
        "explanation": item.snapshot["explanation"],
        "source_type": item.snapshot["source_type"],
        "source_info": current_source_info(session, item.snapshot["source_info"]),
        "wrong_question_id": wrong.id if wrong else None,
    }


def item_info(session, item):
    question = session.get(Question, item.question_id)
    content = item.snapshot
    attempt = session.scalar(select(Attempt).where(Attempt.practice_item_id == item.id))
    return {
        "id": item.id,
        "position": item.position,
        "question_id": item.question_id,
        "type": content["type"],
        "stem": content["stem"],
        "options": content["options"],
        "source_type": content["source_type"],
        "difficulty": content["difficulty"],
        "knowledge_point_id": content["knowledge_point_id"],
        "hinted": item.hinted_at is not None,
        "hint": content["hint"] if item.hinted_at else None,
        "is_valid": question.is_valid,
        "disabled_reason": question.disabled_reason,
        "attempt": attempt_info(session, attempt, item) if attempt else None,
        "feedback": item.feedback,
    }


def practice_info(session, practice):
    rows = session.execute(
        select(Question.is_valid, Attempt)
        .select_from(PracticeItem)
        .join(Question)
        .outerjoin(Attempt, Attempt.practice_item_id == PracticeItem.id)
        .where(PracticeItem.practice_session_id == practice.id)
    ).all()
    attempts = [attempt for valid, attempt in rows if valid and attempt and attempt.is_valid]
    total = sum(valid for valid, _ in rows)
    return {
        "id": practice.id,
        "mode": practice.mode,
        "question_source": practice.question_source,
        "settings": practice.settings,
        "source_conversation_id": practice.source_conversation_id,
        "status": practice.status,
        "actual_count": practice.actual_count,
        "effective_count": total,
        "submitted_count": len(attempts),
        "correct_count": sum(attempt.is_correct for attempt in attempts),
        "notice": practice.notice,
        "error_code": practice.error_code,
        "error_message": practice.error_message,
        "created_at": practice.created_at,
        "completed_at": practice.completed_at,
    }


def wrong_info(session, wrong, include_history=False):
    question = session.get(Question, wrong.question_id)
    attempts = session.scalars(
        select(Attempt)
        .where(Attempt.user_id == wrong.user_id, Attempt.question_id == wrong.question_id)
        .order_by(Attempt.created_at, Attempt.id)
    ).all()
    result = {
        "id": wrong.id,
        "question_id": question.id,
        "knowledge_point_id": question.knowledge_point_id,
        "stem": question.content["stem"],
        "source_type": question.source_type,
        "status": wrong.status,
        "correct_days": wrong.correct_days,
        "last_correct_date": wrong.last_correct_date,
        "is_valid": question.is_valid,
        "disabled_reason": question.disabled_reason,
        "attempt_count": len(attempts),
        "error_count": sum(not attempt.is_correct for attempt in attempts),
        "updated_at": wrong.updated_at,
    }
    if include_history:
        result["question"] = snapshot(question)
        result["question"]["source_info"] = current_source_info(session, question.source_info)
        result["attempts"] = [attempt_info(session, attempt) for attempt in attempts]
    return result


def current_source_info(session, source):
    result = deepcopy(source)
    for citation in result.get("citations", []):
        document = session.get(Document, UUID(citation["document_id"]))
        citation["source_deleted"] = document is None or document.status == "deleted"
    return result
