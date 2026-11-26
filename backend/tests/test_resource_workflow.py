"""资源可见性、审核状态和列表查询的集成测试。"""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from tests.resource_helpers import (
    API,
    TXT_BYTES,
    approve,
    fetch_resource,
    insert_published,
    make_in_state,
    reject,
    reviews_of,
    update_resource_row,
    upload,
)


def test_review_publish_download_and_archive(actors, course, db_session_factory, seed_users):
    rid = make_in_state(actors, course["id"], "pending")
    detail = f"{API}/resources/{rid}"
    assert actors.student.get(detail).status_code == 404
    assert actors.student.get(f"{detail}/download").status_code == 404

    response = approve(actors.admin, rid)
    assert response.status_code == 200
    assert response.json()["review_status"] == "published"
    assert response.json()["index_status"] == "queued"
    assert response.json()["published_at"]
    assert approve(actors.admin, rid).status_code == 409
    assert actors.student.get(f"{detail}/download").content == TXT_BYTES

    archive = actors.admin.post(f"{API}/admin/resources/{rid}/archive")
    assert archive.status_code == 200
    assert archive.json()["index_status"] == "not_indexed"
    assert actors.student.get(detail).status_code == 404
    assert actors.student.get(f"{detail}/download").status_code == 404
    assert actors.other.get(detail).status_code == 404
    assert actors.owner.get(detail).json()["review_status"] == "archived"
    assert actors.admin.get(f"{detail}/download").content == TXT_BYTES
    events = reviews_of(db_session_factory, rid)
    assert [event.action for event in events] == ["approve", "archive"]
    assert all(str(event.reviewer_id) == seed_users["admin01"] for event in events)


def test_rejected_resource_can_be_revised_and_resubmitted(actors, course, db_session_factory):
    rid = make_in_state(actors, course["id"], "pending")
    detail = f"{API}/resources/{rid}"
    assert reject(actors.admin, rid, "  ").status_code == 422
    assert reviews_of(db_session_factory, rid) == []
    assert reject(actors.admin, rid, "补充章节").status_code == 200
    assert actors.owner.get(detail).json()["review_reason"] == "补充章节"
    assert actors.other.get(detail).status_code == 404
    assert actors.owner.post(f"{detail}/submit").status_code == 409
    assert actors.owner.post(f"{detail}/revise").json()["review_status"] == "draft"
    assert actors.owner.patch(detail, json={"title": "补充后的资料"}).status_code == 200
    assert actors.owner.post(f"{detail}/submit").json()["review_status"] == "pending"
    published = approve(actors.admin, rid).json()
    assert published["title"] == "补充后的资料"
    assert published["review_reason"] is None


def test_resource_permissions_for_roles(actors, course, client, storage_dir):
    assert upload(client, course["id"]).status_code == 401
    assert upload(actors.student, course["id"]).status_code == 403
    assert upload(actors.admin, course["id"]).status_code == 403
    assert list(storage_dir.iterdir()) == []

    rid = make_in_state(actors, course["id"], "draft")
    detail = f"{API}/resources/{rid}"
    assert actors.other.get(detail).status_code == 404
    assert actors.other.get(f"{detail}/download").status_code == 404
    assert actors.other.post(f"{detail}/submit").status_code == 404
    assert actors.admin.post(f"{detail}/submit").status_code == 403
    assert actors.student.get(f"{API}/resources/mine").status_code == 403
    assert actors.other.get(f"{API}/resources/mine").json()["total"] == 0
    assert actors.owner.get(f"{API}/resources/mine", params={"review_status": "draft"}).json()["total"] == 1
    assert approve(actors.owner, rid).status_code == 403
    assert actors.student.get(f"{API}/admin/resources").status_code == 403


def test_published_listing_search_filter_and_stable_pagination(actors, course, course2, db_session_factory, seed_users):
    owner = seed_users["teacher01"]
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    earlier_id = insert_published(db_session_factory, owner, course["id"], title="事务%", published_at=when, rid=UUID(int=1))
    newer_id = insert_published(db_session_factory, owner, course["id"], title="讲义", description="事务%", published_at=when, rid=UUID(int=2))
    insert_published(db_session_factory, owner, course["id"], title="事务 A")
    insert_published(db_session_factory, owner, course2["id"], title="事务%")
    make_in_state(actors, course["id"], "pending", title="事务%")

    params = {"q": " 事务% ", "course_id": course["id"], "page_size": 1}
    for page, expected_id in ((1, newer_id), (2, earlier_id)):
        response = actors.student.get(f"{API}/resources", params={**params, "page": page})
        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert [item["id"] for item in response.json()["items"]] == [expected_id]
    pending = actors.admin.get(f"{API}/admin/resources", params={"review_status": "pending", "index_status": "not_indexed"})
    assert pending.status_code == 200
    assert pending.json()["total"] == 1


@pytest.mark.parametrize("index_status", ["processing", "ready", "failed"])
def test_archive_handles_index_state(actors, course, db_session_factory, index_status):
    rid = make_in_state(actors, course["id"], "published")
    processing = index_status == "processing"
    update_resource_row(
        db_session_factory,
        rid,
        index_status=index_status,
        index_attempt_id=UUID(int=10) if processing else None,
        index_lease_until=datetime(2026, 12, 1, tzinfo=timezone.utc) if processing else None,
    )
    response = actors.admin.post(f"{API}/admin/resources/{rid}/archive")
    assert response.status_code == 200
    row = fetch_resource(db_session_factory, rid)
    assert row.index_status == ("not_indexed" if processing else index_status)
    assert row.index_attempt_id is None and row.index_lease_until is None
    assert actors.admin.post(f"{API}/admin/resources/{rid}/index/retry").status_code == 409


def test_only_admin_can_retry_failed_published_index(actors, course, db_session_factory):
    rid = make_in_state(actors, course["id"], "published")
    retry = f"{API}/admin/resources/{rid}/index/retry"
    assert actors.admin.post(retry).status_code == 409
    update_resource_row(db_session_factory, rid, index_status="failed", index_error="内部错误")
    detail = f"{API}/resources/{rid}"
    assert actors.student.get(detail).json()["index_error"] is None
    assert actors.owner.get(detail).json()["index_error"] == "内部错误"
    assert actors.owner.post(retry).status_code == 403
    response = actors.admin.post(retry)
    assert response.status_code == 202
    assert response.json()["index_status"] == "queued"
    assert response.json()["index_error"] is None
    assert actors.admin.post(retry).status_code == 409
