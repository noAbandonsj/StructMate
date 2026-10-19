from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from capstone.core.auth import (
    AuthenticatedSession,
    DatabaseSession,
    clear_session_cookie,
    issue_session,
    load_session,
    no_store,
    password_hasher,
    require_csrf,
    require_json,
    require_origin,
    set_session_cookie,
    verify_password,
)
from capstone.core.errors import ApiError
from capstone.db.models import AuthSession, KnowledgeBase, User, utc_now
from capstone.db.session import write_transaction

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(no_store)])
credential_dependencies = [Depends(require_origin), Depends(require_json)]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-z0-9_]+$")
    password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=32)

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_display_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class RegisterInput(LoginInput):
    display_name: str | None = Field(default=None, min_length=1, max_length=32)

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_display_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PublicUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    username: str
    display_name: str
    role: Literal["user", "admin"]


class PublicKnowledgeBase(BaseModel):
    id: UUID
    kind: Literal["personal"]
    name: str
    is_readonly: bool = False


class AccountResponse(BaseModel):
    user: PublicUser
    default_knowledge_base: PublicKnowledgeBase
    csrf_token: str


def account_response(session: Session, user: User, csrf_token: str) -> AccountResponse:
    library = session.scalars(
        select(KnowledgeBase).where(
            KnowledgeBase.kind == "personal", KnowledgeBase.owner_id == user.id
        )
    ).one_or_none()
    if library is None:
        raise ApiError(503, "LIBRARY_NOT_READY", "个人知识库未就绪，请稍后重试。")
    return AccountResponse(
        user=PublicUser.model_validate(user),
        default_knowledge_base=PublicKnowledgeBase(
            id=library.id, kind="personal", name=library.name
        ),
        csrf_token=csrf_token,
    )


@router.post(
    "/register",
    status_code=201,
    response_model=AccountResponse,
    dependencies=credential_dependencies,
)
def register(
    data: RegisterInput, request: Request, response: Response, session: DatabaseSession
) -> AccountResponse:
    password_hash = password_hasher.hash(data.password.get_secret_value())
    try:
        with write_transaction(session):
            user = User(
                username=data.username,
                display_name=data.display_name or data.username,
                password_hash=password_hash,
            )
            session.add(user)
            session.flush()
            session.add(KnowledgeBase(kind="personal", owner_id=user.id, name="我的资料"))
            token, record = issue_session(session, user.id, request)
            result = account_response(session, user, record.csrf_token)
            expires_at = record.expires_at
    except IntegrityError:
        if session.scalar(select(User.id).where(User.username == data.username)) is not None:
            raise ApiError(409, "USERNAME_TAKEN", "这个用户名已被使用，请换一个。") from None
        raise ApiError(503, "REGISTRATION_FAILED", "账号创建失败，请稍后重试。") from None
    set_session_cookie(response, token, expires_at, request.app.state.settings)
    return result


@router.post("/login", response_model=AccountResponse, dependencies=credential_dependencies)
def login(
    data: LoginInput, request: Request, response: Response, session: DatabaseSession
) -> AccountResponse:
    row = session.execute(
        select(User.id, User.password_hash).where(User.username == data.username)
    ).one_or_none()
    session.rollback()
    password_hash = row.password_hash if row is not None else None
    if not verify_password(data.password.get_secret_value(), password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "用户名或密码不正确。")
    with write_transaction(session):
        user = session.get(User, row.id)
        if user is None or user.password_hash != password_hash:
            raise ApiError(401, "INVALID_CREDENTIALS", "用户名或密码不正确。")
        token, record = issue_session(session, user.id, request)
        result = account_response(session, user, record.csrf_token)
        expires_at = record.expires_at
    set_session_cookie(response, token, expires_at, request.app.state.settings)
    return result


@router.get("/me", response_model=AccountResponse)
def me(current: AuthenticatedSession, session: DatabaseSession) -> AccountResponse:
    user = session.get(User, current.user_id)
    if user is None:
        raise ApiError(401, "LOGIN_REQUIRED", "登录已失效，请重新登录。")
    return account_response(session, user, current.csrf_token)


@router.get("/csrf")
def csrf(current: AuthenticatedSession) -> dict[str, str]:
    return {"csrf_token": current.csrf_token}


@router.patch("/me", response_model=PublicUser, dependencies=[Depends(require_origin)])
def update_profile(
    data: ProfileInput,
    request: Request,
    current: AuthenticatedSession,
    session: DatabaseSession,
) -> PublicUser:
    require_csrf(request, current)
    with write_transaction(session):
        record = session.get(AuthSession, current.id)
        user = session.get(User, current.user_id)
        if record is None or record.expires_at <= utc_now() or user is None:
            raise ApiError(401, "LOGIN_REQUIRED", "登录已失效，请重新登录。")
        user.display_name = data.display_name
        session.flush()
        result = PublicUser.model_validate(user)
    return result


@router.post("/logout", status_code=204, dependencies=[Depends(require_origin)])
def logout(request: Request, session: DatabaseSession) -> Response:
    current = load_session(request, session)
    if current is not None:
        require_csrf(request, current)
        with write_transaction(session):
            session.execute(delete(AuthSession).where(AuthSession.id == current.id))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    clear_session_cookie(response, request.app.state.settings)
    return response
