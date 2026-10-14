from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from secrets import compare_digest, token_urlsafe
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, Response
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from capstone.core.errors import ApiError
from capstone.core.settings import Settings
from capstone.db.models import AuthSession, utc_now
from capstone.db.session import get_session

SESSION_COOKIE = "capstone_session"
password_hasher = PasswordHash.recommended()
_dummy_hash = password_hasher.hash("unregistered-account-password")
DatabaseSession = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class CurrentSession:
    id: UUID
    user_id: UUID
    csrf_token: str
    expires_at: datetime


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        verified = password_hasher.verify(password, password_hash or _dummy_hash)
    except PwdlibError:
        return False
    return password_hash is not None and verified


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def require_origin(request: Request) -> None:
    allowed = set(request.app.state.settings.cors_origins)
    allowed.add(str(request.base_url).rstrip("/"))
    if request.headers.get("origin") not in allowed:
        raise ApiError(403, "ORIGIN_REJECTED", "请求来源无效，请从本网站操作。")


def require_json(request: Request) -> None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ApiError(415, "JSON_REQUIRED", "请使用 JSON 提交账户信息。")


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def load_session(request: Request, session: Session) -> CurrentSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 128:
        return None
    try:
        record = session.scalars(
            select(AuthSession).where(
                AuthSession.token_hash == token_digest(token),
                AuthSession.expires_at > utc_now(),
            )
        ).one_or_none()
        if record is None:
            return None
        return CurrentSession(record.id, record.user_id, record.csrf_token, record.expires_at)
    finally:
        # End the read transaction before later password work or writes.
        session.rollback()


def require_session(request: Request, session: DatabaseSession) -> CurrentSession:
    current = load_session(request, session)
    if current is None:
        raise ApiError(401, "LOGIN_REQUIRED", "登录已失效，请重新登录。")
    return current


AuthenticatedSession = Annotated[CurrentSession, Depends(require_session)]


def require_csrf(request: Request, current: CurrentSession) -> None:
    supplied = request.headers.get("x-csrf-token", "")
    if not compare_digest(supplied.encode("utf-8"), current.csrf_token.encode("utf-8")):
        raise ApiError(403, "CSRF_REJECTED", "操作凭据已失效，请刷新后重试。")


def issue_session(session: Session, user_id: UUID, request: Request) -> tuple[str, AuthSession]:
    previous = request.cookies.get(SESSION_COOKIE)
    if previous and len(previous) <= 128:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(previous)))
    token = token_urlsafe(32)
    now = utc_now()
    record = AuthSession(
        user_id=user_id,
        token_hash=token_digest(token),
        csrf_token=token_urlsafe(32),
        created_at=now,
        expires_at=now + timedelta(days=request.app.state.settings.session_days),
    )
    session.add(record)
    session.flush()
    return token, record


def set_session_cookie(
    response: Response, token: str, expires_at: datetime, settings: Settings
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 24 * 60 * 60,
        expires=expires_at,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )
