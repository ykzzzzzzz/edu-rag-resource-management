import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app import resource_queries as rq
from app.common import utcnow
from app.config import Settings
from app.deps import AdminDep, CurrentUserDep, DbDep, TeacherDep
from app.errors import AppError
from app.models import Resource, ResourceReview
from app.schemas import (
    IndexStatus,
    ResourceCreateForm,
    ResourceListOut,
    ResourceOut,
    ResourceUpdate,
    ReviewIn,
    ReviewStatus,
)
from app.uploads import (
    content_disposition,
    new_storage_key,
    receive_upload,
    stored_path,
    unlink_quietly,
    validate_content,
)

router = APIRouter(prefix="/resources", tags=["resources"])
admin_router = APIRouter(prefix="/admin/resources", tags=["admin-resources"])

COURSE_NOT_FOUND = ("course_not_found", "课程不存在")


class PageParams:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ):
        self.page = page
        self.page_size = page_size


PageDep = Annotated[PageParams, Depends()]


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _paged(db: Session, viewer, stmt, page: PageParams) -> ResourceListOut:
    rows, total = rq.paginate(db, stmt, page.page, page.page_size)
    return ResourceListOut(
        items=rq.serialize(db, rows, viewer), total=total, page=page.page, page_size=page.page_size
    )


def _newest_first(stmt):
    return stmt.order_by(Resource.published_at.desc(), Resource.id.desc())


# ---------- 列表 ----------


@router.get("", response_model=ResourceListOut)
def list_published(
    db: DbDep,
    user: CurrentUserDep,
    page: PageDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    course_id: uuid.UUID | None = None,
) -> ResourceListOut:
    stmt = rq.base_select().where(Resource.review_status == "published")
    if course_id is not None:
        stmt = stmt.where(Resource.course_id == course_id)
    keyword = (q or "").strip()
    if keyword:
        pattern = f"%{rq.escape_like(keyword)}%"
        stmt = stmt.where(
            or_(Resource.title.ilike(pattern, escape="\\"), Resource.description.ilike(pattern, escape="\\"))
        )
    return _paged(db, user, _newest_first(stmt), page)


@router.get("/mine", response_model=ResourceListOut)
def list_mine(
    db: DbDep,
    teacher: TeacherDep,
    page: PageDep,
    review_status: ReviewStatus | None = None,
) -> ResourceListOut:
    stmt = rq.base_select().where(Resource.owner_id == teacher.id)
    if review_status is not None:
        stmt = stmt.where(Resource.review_status == review_status)
    stmt = stmt.order_by(Resource.created_at.desc(), Resource.id.desc())
    return _paged(db, teacher, stmt, page)


@admin_router.get("", response_model=ResourceListOut)
def list_admin(
    db: DbDep,
    admin: AdminDep,
    page: PageDep,
    review_status: ReviewStatus | None = None,
    index_status: IndexStatus | None = None,
    course_id: uuid.UUID | None = None,
) -> ResourceListOut:
    stmt = rq.base_select()
    if review_status is not None:
        stmt = stmt.where(Resource.review_status == review_status)
    if index_status is not None:
        stmt = stmt.where(Resource.index_status == index_status)
    if course_id is not None:
        stmt = stmt.where(Resource.course_id == course_id)
    stmt = stmt.order_by(Resource.created_at.desc(), Resource.id.desc())
    return _paged(db, admin, stmt, page)


# ---------- 上传与修改 ----------


def _store_upload(db: Session, teacher, storage_dir, upload) -> ResourceOut:
    """在线程池中执行：校验内容、改名落盘、写库。任何失败都清理本次生成的文件。"""
    final_path = None
    try:
        try:
            form = ResourceCreateForm.model_validate(upload.fields)
        except ValidationError:
            raise AppError(422, "validation_error", "请求参数不合法") from None
        if not rq.course_exists(db, form.course_id):
            raise AppError(422, *COURSE_NOT_FOUND)

        mime_type = validate_content(upload.temp_path, upload.filename)

        storage_key = new_storage_key()
        final_path = stored_path(storage_dir, storage_key)
        # 临时文件与正式文件在同一目录，replace 在同一文件系统内是原子的
        upload.temp_path.replace(final_path)

        resource = Resource(
            owner_id=teacher.id,
            course_id=form.course_id,
            title=form.title,
            description=form.description or None,
            original_filename=upload.filename,
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=upload.size,
            review_status="draft",
            index_status="not_indexed",
        )
        db.add(resource)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # 课程在校验之后被删除等竞态，仍按课程不存在处理
            if not rq.course_exists(db, form.course_id):
                raise AppError(422, *COURSE_NOT_FOUND) from None
            raise
    except BaseException:
        # 校验失败、数据库失败或任何其他异常：清理本次生成的全部文件
        upload.discard()
        unlink_quietly(final_path)
        try:
            db.rollback()
        except SQLAlchemyError:
            pass
        raise
    return rq.load_out(db, teacher, resource.id)


@router.post("", status_code=201, response_model=ResourceOut)
async def upload_resource(request: Request, db: DbDep, teacher: TeacherDep) -> ResourceOut:
    # 角色校验在读取请求体之前完成（依赖先于函数体执行），学生和管理员不会触发任何落盘
    settings = _settings(request)
    upload = await receive_upload(request, settings.resource_storage_dir, settings.max_upload_bytes)
    return await run_in_threadpool(_store_upload, db, teacher, settings.resource_storage_dir, upload)


@router.patch("/{resource_id}", response_model=ResourceOut)
def update_resource(resource_id: uuid.UUID, body: ResourceUpdate, db: DbDep, teacher: TeacherDep) -> ResourceOut:
    changes = body.model_dump(exclude_unset=True)
    resource = rq.get_owned_for_update(db, teacher, resource_id)
    if resource.review_status != "draft":
        db.rollback()
        raise rq.conflict("只有草稿状态的资源可以修改")
    if "course_id" in changes and not rq.course_exists(db, changes["course_id"]):
        db.rollback()
        raise AppError(422, *COURSE_NOT_FOUND)
    for field, value in changes.items():
        if field == "description":
            value = value or None
        setattr(resource, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(422, *COURSE_NOT_FOUND) from None
    return rq.load_out(db, teacher, resource_id)


# ---------- 详情与下载 ----------


@router.get("/{resource_id}", response_model=ResourceOut)
def get_resource(resource_id: uuid.UUID, db: DbDep, user: CurrentUserDep) -> ResourceOut:
    rq.get_visible(db, user, resource_id)
    return rq.load_out(db, user, resource_id)


@router.get("/{resource_id}/download")
def download_resource(resource_id: uuid.UUID, request: Request, db: DbDep, user: CurrentUserDep) -> FileResponse:
    resource = rq.get_visible(db, user, resource_id)
    path = stored_path(_settings(request).resource_storage_dir, resource.storage_key)
    if not path.is_file():
        raise AppError(404, "file_missing", "资源文件不存在")
    return FileResponse(
        path,
        media_type=resource.mime_type,
        headers={
            "Content-Disposition": content_disposition(resource.original_filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


# ---------- 教师状态流转 ----------


@router.post("/{resource_id}/submit", response_model=ResourceOut)
def submit_resource(resource_id: uuid.UUID, db: DbDep, teacher: TeacherDep) -> ResourceOut:
    resource = rq.get_owned_for_update(db, teacher, resource_id)
    if resource.review_status != "draft":
        db.rollback()
        raise rq.conflict("只有草稿状态的资源可以提交审核")
    resource.review_status = "pending"
    db.commit()
    return rq.load_out(db, teacher, resource_id)


@router.post("/{resource_id}/revise", response_model=ResourceOut)
def revise_resource(resource_id: uuid.UUID, db: DbDep, teacher: TeacherDep) -> ResourceOut:
    resource = rq.get_owned_for_update(db, teacher, resource_id)
    if resource.review_status != "rejected":
        db.rollback()
        raise rq.conflict("只有被驳回的资源可以退回草稿")
    resource.review_status = "draft"
    db.commit()
    return rq.load_out(db, teacher, resource_id)


# ---------- 管理员审核、下架、重试索引 ----------


@admin_router.post("/{resource_id}/review", response_model=ResourceOut)
def review_resource(resource_id: uuid.UUID, body: ReviewIn, db: DbDep, admin: AdminDep) -> ResourceOut:
    resource = rq.get_for_update(db, resource_id)
    if resource.review_status != "pending":
        db.rollback()
        raise rq.conflict("只有待审核的资源可以审核")

    db.add(
        ResourceReview(
            resource_id=resource.id,
            reviewer_id=admin.id,
            action=body.action,
            reason=body.reason or None,
        )
    )
    if body.action == "approve":
        resource.review_status = "published"
        resource.published_at = utcnow()
        # M2 只负责置为 queued，真正的索引进程在 M3
        resource.index_status = "queued"
        resource.index_error = None
        resource.index_attempt_id = None
        resource.index_lease_until = None
    else:
        resource.review_status = "rejected"
    db.commit()
    return rq.load_out(db, admin, resource_id)


@admin_router.post("/{resource_id}/archive", response_model=ResourceOut)
def archive_resource(resource_id: uuid.UUID, db: DbDep, admin: AdminDep) -> ResourceOut:
    resource = rq.get_for_update(db, resource_id)
    if resource.review_status != "published":
        db.rollback()
        raise rq.conflict("只有已发布的资源可以下架")

    db.add(ResourceReview(resource_id=resource.id, reviewer_id=admin.id, action="archive", reason=None))
    resource.review_status = "archived"
    # ready / failed 保持不变；排队或处理中的任务作废，令牌与到期时间清空，工作进程完成时核对不到令牌会放弃结果
    if resource.index_status in ("queued", "processing"):
        resource.index_status = "not_indexed"
        resource.index_attempt_id = None
        resource.index_lease_until = None
    db.commit()
    return rq.load_out(db, admin, resource_id)


@admin_router.post("/{resource_id}/index/retry", status_code=202, response_model=ResourceOut)
def retry_index(resource_id: uuid.UUID, db: DbDep, admin: AdminDep) -> ResourceOut:
    resource = rq.get_for_update(db, resource_id)
    if resource.review_status != "published" or resource.index_status != "failed":
        db.rollback()
        raise rq.conflict("只有已发布且索引失败的资源可以重试索引")
    resource.index_status = "queued"
    resource.index_error = None
    resource.index_attempt_id = None
    resource.index_lease_until = None
    db.commit()
    return rq.load_out(db, admin, resource_id)
