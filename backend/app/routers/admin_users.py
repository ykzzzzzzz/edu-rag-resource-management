import uuid
from typing import Literal

from fastapi import APIRouter, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.deps import AdminDep, DbDep
from app.errors import AppError, raise_for_unique_violation
from app.models import AuthSession, User
from app.schemas import AdminUserCreate, AdminUserOut, AdminUserUpdate, ResetPasswordIn, UserListOut
from app.security import hash_password

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("", response_model=UserListOut)
def list_users(
    db: DbDep,
    _admin: AdminDep,
    role: Literal["student", "teacher", "admin"] | None = None,
    is_active: bool | None = None,
) -> dict:
    stmt = select(User).order_by(User.created_at, User.username)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    users = db.execute(stmt).scalars().all()
    return {"items": [AdminUserOut.model_validate(u) for u in users]}


@router.post("", status_code=201, response_model=AdminUserOut)
def create_user(body: AdminUserCreate, db: DbDep, _admin: AdminDep) -> User:
    user = User(
        username=body.username,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise_for_unique_violation(exc, "username_taken", "用户名已存在")
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=AdminUserOut)
def update_user(user_id: uuid.UUID, body: AdminUserUpdate, db: DbDep, admin: AdminDep) -> User:
    changes = body.model_dump(exclude_unset=True)

    # 先锁定全部启用中的管理员行（按 id 排序），串行化对管理员集合的修改，防止并发把最后一个管理员降级或停用
    enabled_admin_ids = (
        db.execute(
            select(User.id)
            .where(User.role == "admin", User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        )
        .scalars()
        .all()
    )

    target = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if target is None:
        raise AppError(404, "user_not_found", "用户不存在")

    new_role = changes.get("role", target.role)
    new_active = changes.get("is_active", target.is_active)

    if target.id == admin.id and new_active is False:
        raise AppError(409, "cannot_disable_self", "管理员不能停用自己")

    was_enabled_admin = target.role == "admin" and target.is_active
    stays_enabled_admin = new_role == "admin" and new_active
    if was_enabled_admin and not stays_enabled_admin and len(enabled_admin_ids) <= 1:
        raise AppError(409, "last_admin", "不能修改最后一个启用管理员的角色或停用该账号")

    for field, value in changes.items():
        setattr(target, field, value)

    if new_active is False:
        db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))

    db.commit()
    db.refresh(target)
    return target


@router.post("/{user_id}/reset-password", status_code=204)
def reset_password(user_id: uuid.UUID, body: ResetPasswordIn, db: DbDep, _admin: AdminDep) -> Response:
    target = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if target is None:
        raise AppError(404, "user_not_found", "用户不存在")

    target.password_hash = hash_password(body.new_password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
    db.commit()
    return Response(status_code=204)
