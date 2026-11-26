from datetime import timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, select

from app.common import utcnow
from app.deps import SESSION_COOKIE_NAME, CurrentUserDep, DbDep
from app.errors import AppError
from app.models import AuthSession, User
from app.schemas import LoginIn, MeOut
from app.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    password_needs_rehash,
    verify_dummy_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: DbDep) -> User:
    settings = request.app.state.settings
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()

    if user is None:
        verify_dummy_password(body.password)
        password_ok = False
    else:
        password_ok = verify_password(user.password_hash, body.password)

    # 用户不存在、密码错误、账号停用统一返回同一错误，不泄露账号状态
    if user is None or not password_ok or not user.is_active:
        raise AppError(401, "invalid_credentials", "用户名或密码错误")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    token = new_session_token()
    db.add(
        AuthSession(
            token_hash=hash_session_token(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
        )
    )
    db.commit()

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )
    db.refresh(user)
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, db: DbDep) -> Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_session_token(token)))
        db.commit()

    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.session_cookie_secure,
    )
    return response


@router.get("/me", response_model=MeOut)
def me(user: CurrentUserDep) -> User:
    return user
