import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from sqlalchemy import Date, case, cast, func, select

from app import qa_service
from app import resource_queries as rq
from app.common import utcnow
from app.deps import AdminDep, CurrentUserDep, DbDep
from app.errors import AppError
from app.models import Course, QaLog, Resource, ResourceChunk
from app.routers.resources import COURSE_NOT_FOUND, PageDep
from app.schemas import (
    AskIn,
    AskOut,
    CitationDetailOut,
    QaLogListOut,
    QaLogOut,
    QaLogStatus,
    QaLogTimingsOut,
    StatsOut,
)

router = APIRouter(prefix="/qa", tags=["qa"])
citation_router = APIRouter(prefix="/resources", tags=["qa"])
admin_router = APIRouter(prefix="/admin", tags=["admin-qa"])

DISPLAY_TZ = ZoneInfo("Asia/Shanghai")
REVIEW_STATUSES = ("draft", "pending", "published", "rejected", "archived")
INDEX_STATUSES = ("not_indexed", "queued", "processing", "ready", "failed")


@router.post("/ask", response_model=AskOut)
def ask(body: AskIn, request: Request, db: DbDep, user: CurrentUserDep) -> dict:
    state = request.app.state
    if body.course_id is not None and not rq.course_exists(db, body.course_id):
        raise AppError(422, *COURSE_NOT_FOUND)
    if state.embedder_provider.state == "loading":
        raise AppError(503, "retrieval_warming_up", "检索模型正在加载，请稍后重试")
    if not state.qa_rate_limiter.allow(str(user.id)):
        raise AppError(429, "qa_rate_limited", "提问过于频繁，请稍后再试")
    return qa_service.ask(
        db=db,
        session_factory=state.session_factory,
        settings=state.settings,
        provider=state.embedder_provider,
        transport=state.llm_transport,
        question=body.question,
        course_id=body.course_id,
    )


# ---------- 引用详情 ----------


@citation_router.get("/{resource_id}/citations/{chunk_id}", response_model=CitationDetailOut)
def get_citation(resource_id: uuid.UUID, chunk_id: uuid.UUID, db: DbDep, _user: CurrentUserDep) -> dict:
    """只有资源为 published 且 ready、片段属于该资源时返回；其余一律 404，不区分原因。"""
    row = db.execute(
        select(
            ResourceChunk.id,
            ResourceChunk.resource_id,
            ResourceChunk.content,
            ResourceChunk.locator,
            Resource.title,
            Resource.original_filename,
            Course.name,
        )
        .join(Resource, Resource.id == ResourceChunk.resource_id)
        .join(Course, Course.id == Resource.course_id)
        .where(
            ResourceChunk.id == chunk_id,
            ResourceChunk.resource_id == resource_id,
            Resource.review_status == "published",
            Resource.index_status == "ready",
        )
    ).one_or_none()
    if row is None:
        raise AppError(404, "citation_not_found", "出处不存在或已不可用")
    return {
        "resource_id": row[1],
        "chunk_id": row[0],
        "title": row[4],
        "course_name": row[6],
        "original_filename": row[5],
        "locator": row[3],
        "content": row[2],
    }


# ---------- 统计 ----------


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=DISPLAY_TZ)


@admin_router.get("/stats", response_model=StatsOut)
def stats(db: DbDep, _admin: AdminDep, days: Annotated[int, Query(ge=1, le=180)] = 30) -> dict:
    today = utcnow().astimezone(DISPLAY_TZ).date()
    first_day = today - timedelta(days=days - 1)

    published = func.count(Resource.id).filter(Resource.review_status == "published")
    courses = db.execute(
        select(Course.id, Course.name, published)
        .outerjoin(Resource, Resource.course_id == Course.id)
        .group_by(Course.id, Course.name)
        .order_by(Course.name, Course.id)
    ).all()

    review = dict.fromkeys(REVIEW_STATUSES, 0)
    review.update(dict(db.execute(select(Resource.review_status, func.count()).group_by(Resource.review_status)).all()))
    index = dict.fromkeys(INDEX_STATUSES, 0)
    index.update(dict(db.execute(select(Resource.index_status, func.count()).group_by(Resource.index_status)).all()))

    local_day = cast(func.timezone("Asia/Shanghai", QaLog.created_at), Date)
    per_day = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            select(
                local_day,
                func.count(),
                func.coalesce(func.sum(case((QaLog.status == "insufficient_evidence", 1), else_=0)), 0),
            )
            .where(QaLog.created_at >= _local_midnight(first_day))
            .group_by(local_day)
        ).all()
    }
    daily = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        total, insufficient = per_day.get(day, (0, 0))
        daily.append({"date": day.isoformat(), "total": int(total), "insufficient_evidence": int(insufficient)})

    qa_total = sum(item["total"] for item in daily)
    insufficient_total = sum(item["insufficient_evidence"] for item in daily)
    return {
        "days": days,
        "courses": [
            {"course_id": cid, "course_name": name, "published_resources": count} for cid, name, count in courses
        ],
        "review_status": review,
        "index_status": index,
        "daily_qa": daily,
        "qa_total": qa_total,
        "insufficient_evidence_total": insufficient_total,
        "insufficient_evidence_ratio": round(insufficient_total / qa_total, 4) if qa_total else 0.0,
    }


# ---------- 问答日志 ----------


@admin_router.get("/qa-logs", response_model=QaLogListOut, response_model_by_alias=True)
def qa_logs(
    db: DbDep,
    _admin: AdminDep,
    page: PageDep,
    status: QaLogStatus | None = None,
    course_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> QaLogListOut:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise AppError(422, "validation_error", "请求参数不合法")
    conditions = []
    if status is not None:
        conditions.append(QaLog.status == status)
    if course_id is not None:
        conditions.append(QaLog.course_id == course_id)
    if date_from is not None:
        conditions.append(QaLog.created_at >= _local_midnight(date_from))
    if date_to is not None:
        conditions.append(QaLog.created_at < _local_midnight(date_to + timedelta(days=1)))

    total = db.execute(select(func.count()).select_from(QaLog).where(*conditions)).scalar_one()
    rows = db.execute(
        select(QaLog, Course.name)
        .outerjoin(Course, Course.id == QaLog.course_id)
        .where(*conditions)
        .order_by(QaLog.created_at.desc(), QaLog.id.desc())
        .limit(page.page_size)
        .offset((page.page - 1) * page.page_size)
    ).all()
    items = [
        QaLogOut(
            id=entry.id,
            created_at=entry.created_at,
            course_id=entry.course_id,
            course_name=course_name,
            question=entry.question,
            status=entry.status,
            answer=entry.answer,
            retrieved=entry.retrieved,
            cited_chunk_ids=entry.cited_chunk_ids,
            timings=QaLogTimingsOut.model_validate(entry.timings),
            llm_config=entry.llm_config,
        )
        for entry, course_name in rows
    ]
    return QaLogListOut(items=items, total=total, page=page.page, page_size=page.page_size)
