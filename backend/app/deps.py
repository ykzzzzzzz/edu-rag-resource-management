from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import utcnow
from app.errors import AppError
from app.models import AuthSession, User
from app.security import hash_session_token

SESSION_COOKIE_NAME = "scf_session"


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


DbDep = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbDep) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise AppError(401, "unauthenticated", "请先登录")
    # 会话未过期且账号仍启用才有效；停用账号后即使会话行残留也无法通过
    stmt = (
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == hash_session_token(token),
            AuthSession.expires_at > utcnow(),
            User.is_active.is_(True),
        )
    )
    user = db.execute(stmt).scalar_one_or_none()
    if user is None:
        raise AppError(401, "unauthenticated", "登录已失效，请重新登录")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUserDep) -> User:
    if user.role != "admin":
        raise AppError(403, "forbidden", "需要管理员权限")
    return user


AdminDep = Annotated[User, Depends(require_admin)]


def require_teacher(user: CurrentUserDep) -> User:
    if user.role != "teacher":
        raise AppError(403, "forbidden", "需要教师权限")
    return user


TeacherDep = Annotated[User, Depends(require_teacher)]
