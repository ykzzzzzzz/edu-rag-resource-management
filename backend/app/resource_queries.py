"""资源的查询、可见性判断与响应序列化，供用户侧和管理员侧路由共用。"""

import uuid
from typing import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Course, Resource, ResourceReview, User
from app.schemas import ResourceOut

RESOURCE_NOT_FOUND = ("resource_not_found", "资源不存在")
INVALID_STATE = "invalid_state"


def not_found() -> AppError:
    return AppError(404, *RESOURCE_NOT_FOUND)


def conflict(message: str) -> AppError:
    return AppError(409, INVALID_STATE, message)


def escape_like(value: str) -> str:
    """转义 LIKE 通配符，配合 escape="\\" 使用。顺序：先转义转义符本身。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def base_select() -> Select:
    return (
        select(Resource, User.display_name.label("owner_name"), Course.name.label("course_name"))
        .join(User, User.id == Resource.owner_id)
        .join(Course, Course.id == Resource.course_id)
    )


def is_visible(viewer: User, resource: Resource) -> bool:
    """对象级可见性：管理员全部；教师本人全部状态加他人已发布；学生仅已发布。"""
    if viewer.role == "admin":
        return True
    if resource.review_status == "published":
        return True
    return viewer.role == "teacher" and resource.owner_id == viewer.id


def latest_reject_reasons(db: Session, resource_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """每个资源最近一条审核记录若为驳回，返回其原因。"""
    ids = list(resource_ids)
    if not ids:
        return {}
    stmt = (
        select(ResourceReview.resource_id, ResourceReview.action, ResourceReview.reason)
        .where(ResourceReview.resource_id.in_(ids))
        .order_by(ResourceReview.resource_id, ResourceReview.created_at.desc(), ResourceReview.id.desc())
        .distinct(ResourceReview.resource_id)
    )
    return {
        rid: reason or ""
        for rid, action, reason in db.execute(stmt).all()
        if action == "reject"
    }


def serialize(db: Session, rows: list, viewer: User) -> list[ResourceOut]:
    """rows 为 base_select() 的结果行。内部处理细节（索引错误、驳回原因）只给所有者和管理员。"""
    reasons = latest_reject_reasons(
        db, [res.id for res, _, _ in rows if res.review_status in ("rejected", "draft")]
    )
    items = []
    for res, owner_name, course_name in rows:
        privileged = viewer.role == "admin" or res.owner_id == viewer.id
        reason = reasons.get(res.id) if privileged else None
        items.append(
            ResourceOut(
                id=res.id,
                owner_id=res.owner_id,
                owner_name=owner_name,
                course_id=res.course_id,
                course_name=course_name,
                title=res.title,
                description=res.description,
                original_filename=res.original_filename,
                mime_type=res.mime_type,
                size_bytes=res.size_bytes,
                review_status=res.review_status,
                index_status=res.index_status,
                index_error=res.index_error if privileged else None,
                review_reason=reason,
                published_at=res.published_at,
                created_at=res.created_at,
                updated_at=res.updated_at,
            )
        )
    return items


def load_out(db: Session, viewer: User, resource_id: uuid.UUID) -> ResourceOut:
    """在最新数据上重新读取资源并序列化（用于写操作提交之后）。"""
    row = db.execute(base_select().where(Resource.id == resource_id)).one_or_none()
    if row is None:
        raise not_found()
    return serialize(db, [row], viewer)[0]


def get_visible(db: Session, viewer: User, resource_id: uuid.UUID) -> Resource:
    """取得对 viewer 可见的资源；不存在或不可见一律 404。"""
    res = db.get(Resource, resource_id)
    if res is None or not is_visible(viewer, res):
        raise not_found()
    return res


def get_for_update(db: Session, resource_id: uuid.UUID) -> Resource:
    """SELECT ... FOR UPDATE 锁定资源行。调用方在同一事务内校验状态。"""
    res = db.execute(select(Resource).where(Resource.id == resource_id).with_for_update()).scalar_one_or_none()
    if res is None:
        raise not_found()
    return res


def get_owned_for_update(db: Session, owner: User, resource_id: uuid.UUID) -> Resource:
    """锁定本人资源。他人的资源按不存在处理，避免泄露其存在。"""
    res = get_for_update(db, resource_id)
    if res.owner_id != owner.id:
        db.rollback()
        raise not_found()
    return res


def course_exists(db: Session, course_id: uuid.UUID) -> bool:
    return db.execute(select(func.count()).select_from(Course).where(Course.id == course_id)).scalar_one() > 0


def paginate(db: Session, stmt: Select, page: int, page_size: int) -> tuple[list, int]:
    """stmt 为已带过滤和排序的 base_select()；返回当前页的行和总数。"""
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).with_only_columns(Resource.id).subquery())).scalar_one()
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return rows, total
