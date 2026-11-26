"""资源相关测试的共用辅助：样例文件、上传、直接读写数据库。"""

import io
import secrets
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Resource, ResourceReview

API = "/api/v1"

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
TXT_BYTES = "事务的隔离性要求并发事务互不干扰。\n第二行。".encode("utf-8")
MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_TXT = "text/plain"


def make_docx(extra: dict[str, bytes] | None = None, with_document: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        if with_document:
            zf.writestr("word/document.xml", "<w:document/>")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def upload(
    client,
    course_id,
    *,
    title="示例资料",
    filename="note.txt",
    content=TXT_BYTES,
    content_type=None,
    description=None,
    data_extra=None,
    include_file=True,
):
    data = {"title": title, "course_id": str(course_id)}
    if description is not None:
        data["description"] = description
    data.update(data_extra or {})
    files = {"file": (filename, content, content_type)} if include_file else None
    return client.post(f"{API}/resources", data=data, files=files)


def uploaded_id(client, course_id, **kwargs) -> str:
    resp = upload(client, course_id, **kwargs)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def approve(admin, rid):
    return admin.post(f"{API}/admin/resources/{rid}/review", json={"action": "approve"})


def reject(admin, rid, reason="内容不完整"):
    return admin.post(f"{API}/admin/resources/{rid}/review", json={"action": "reject", "reason": reason})


def make_in_state(actors, course_id, state: str, **upload_kwargs) -> str:
    """通过真实接口把一个新资源推进到指定审核状态，返回资源 ID。"""
    rid = uploaded_id(actors.owner, course_id, **upload_kwargs)
    if state == "draft":
        return rid
    assert actors.owner.post(f"{API}/resources/{rid}/submit").status_code == 200
    if state == "pending":
        return rid
    if state == "rejected":
        assert reject(actors.admin, rid).status_code == 200
        return rid
    assert approve(actors.admin, rid).status_code == 200
    if state == "published":
        return rid
    assert actors.admin.post(f"{API}/admin/resources/{rid}/archive").status_code == 200
    assert state == "archived"
    return rid


def fetch_resource(factory, rid) -> Resource:
    with factory() as db:
        return db.get(Resource, uuid.UUID(str(rid)))


def update_resource_row(factory, rid, **values) -> None:
    with factory() as db:
        res = db.get(Resource, uuid.UUID(str(rid)))
        for k, v in values.items():
            setattr(res, k, v)
        db.commit()


def reviews_of(factory, rid) -> list[ResourceReview]:
    with factory() as db:
        stmt = (
            select(ResourceReview)
            .where(ResourceReview.resource_id == uuid.UUID(str(rid)))
            .order_by(ResourceReview.created_at, ResourceReview.id)
        )
        return list(db.execute(stmt).scalars())


def insert_published(
    factory,
    owner_id,
    course_id,
    *,
    title,
    description=None,
    published_at: datetime | None = None,
    rid: uuid.UUID | None = None,
) -> str:
    """直接写入一条已发布资源（不产生磁盘文件），用于列表、排序和搜索测试。"""
    when = published_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    with factory() as db:
        res = Resource(
            id=rid or uuid.uuid4(),
            owner_id=uuid.UUID(str(owner_id)),
            course_id=uuid.UUID(str(course_id)),
            title=title,
            description=description,
            original_filename="x.txt",
            storage_key=secrets.token_hex(16),
            mime_type=MIME_TXT,
            size_bytes=3,
            review_status="published",
            index_status="ready",
            published_at=when,
        )
        db.add(res)
        db.commit()
        return str(res.id)


def minutes(base: datetime, n: int) -> datetime:
    return base + timedelta(minutes=n)


def disk_files(storage_dir) -> list[str]:
    return sorted(p.name for p in storage_dir.iterdir())
