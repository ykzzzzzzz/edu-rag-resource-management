"""GET /resources/{id}/citations/{chunk_id}、GET /admin/stats、GET /admin/qa-logs。"""

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.common import utcnow
from app.models import QaLog
from tests.qa_helpers import add_chunk, ask, ready_resource
from tests.resource_helpers import API, make_in_state, update_resource_row

SHANGHAI = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------- 引用详情

def citation_url(rid, chunk_id) -> str:
    return f"{API}/resources/{rid}/citations/{chunk_id}"


def test_citation_returns_full_chunk_for_any_role(actors, db_session_factory, app, course, login, seed_users):
    rid = ready_resource(actors, db_session_factory, course["id"], title="事务讲义", filename="课件.txt")
    content = "完整片段文本。" * 80  # 比问答里的摘录长
    chunk = add_chunk(db_session_factory, app.state.settings, rid, content, 0.9,
                      locator={"type": "pdf_page", "start": 3, "end": 3})
    for username in ("student01", "teacher01", "teacherx", "admin01"):
        resp = login(username).get(citation_url(rid, chunk))
        assert resp.status_code == 200, (username, resp.text)
        assert resp.json() == {
            "resource_id": rid, "chunk_id": chunk, "title": "事务讲义", "course_name": "数据库原理",
            "original_filename": "课件.txt", "locator": {"type": "pdf_page", "start": 3, "end": 3}, "content": content,
        }


def test_citation_excerpt_in_answer_is_shorter_than_full_content(student_client, actors, db_session_factory, app, course):
    rid = ready_resource(actors, db_session_factory, course["id"])
    chunk = add_chunk(db_session_factory, app.state.settings, rid, "长" * 500, 0.9)
    citation = ask(student_client).json()["citations"][0]
    assert len(citation["excerpt"]) < 500
    assert student_client.get(citation_url(rid, chunk)).json()["content"] == "长" * 500


def test_citation_requires_login(make_client, actors, db_session_factory, app, course):
    rid = ready_resource(actors, db_session_factory, course["id"])
    chunk = add_chunk(db_session_factory, app.state.settings, rid, "内容", 0.9)
    assert make_client().get(citation_url(rid, chunk)).status_code == 401


def test_citation_404_for_archived_resource_even_for_owner_and_admin(
    actors, student_client, db_session_factory, app, course
):
    rid = ready_resource(actors, db_session_factory, course["id"])
    chunk = add_chunk(db_session_factory, app.state.settings, rid, "内容", 0.9)
    assert student_client.get(citation_url(rid, chunk)).status_code == 200
    assert actors.admin.post(f"{API}/admin/resources/{rid}/archive").status_code == 200
    for client in (student_client, actors.owner, actors.admin):
        resp = client.get(citation_url(rid, chunk))
        assert resp.status_code == 404 and resp.json()["error"]["code"] == "citation_not_found"


@pytest.mark.parametrize("state", ["queued", "processing", "failed", "not_indexed"])
def test_citation_404_unless_index_is_ready(actors, student_client, db_session_factory, app, course, state):
    rid = ready_resource(actors, db_session_factory, course["id"])
    chunk = add_chunk(db_session_factory, app.state.settings, rid, "内容", 0.9)
    update_resource_row(db_session_factory, rid, index_status=state)
    assert student_client.get(citation_url(rid, chunk)).status_code == 404


@pytest.mark.parametrize("state", ["draft", "pending", "rejected"])
def test_citation_404_for_unpublished_resource(actors, student_client, db_session_factory, app, course, state):
    rid = make_in_state(actors, course["id"], state)
    chunk = add_chunk(db_session_factory, app.state.settings, rid, "内容", 0.9)
    assert student_client.get(citation_url(rid, chunk)).status_code == 404


def test_citation_404_when_chunk_belongs_to_another_resource(actors, student_client, db_session_factory, app, course):
    a = ready_resource(actors, db_session_factory, course["id"], title="A")
    b = ready_resource(actors, db_session_factory, course["id"], title="B")
    chunk_a = add_chunk(db_session_factory, app.state.settings, a, "A 内容", 0.9)
    add_chunk(db_session_factory, app.state.settings, b, "B 内容", 0.9)
    assert student_client.get(citation_url(b, chunk_a)).status_code == 404
    assert student_client.get(citation_url(a, chunk_a)).status_code == 200


def test_citation_404_for_unknown_ids_and_422_for_malformed(actors, student_client, db_session_factory, course):
    rid = ready_resource(actors, db_session_factory, course["id"])
    assert student_client.get(citation_url(rid, uuid.uuid4())).status_code == 404
    assert student_client.get(citation_url(uuid.uuid4(), uuid.uuid4())).status_code == 404
    assert student_client.get(citation_url(rid, "not-a-uuid")).status_code == 422


# ---------------------------------------------------------------- 统计

def insert_log(factory, *, status="answered", created_at=None, course_id=None, question="问题", **extra) -> str:
    with factory() as db:
        entry = QaLog(
            question=question, status=status, course_id=uuid.UUID(str(course_id)) if course_id else None,
            created_at=created_at or utcnow(), **extra,
        )
        db.add(entry)
        db.commit()
        return str(entry.id)


def scalar(factory, sql, **params):
    with factory() as db:
        return db.execute(text(sql), params).scalar_one()


def local_noon(day_offset: int) -> datetime:
    today = utcnow().astimezone(SHANGHAI).date()
    return datetime.combine(today + timedelta(days=day_offset), datetime.min.time(), SHANGHAI).replace(hour=12)


def test_stats_requires_admin(student_client, teacher_client, make_client, seed_users):
    assert make_client().get(f"{API}/admin/stats").status_code == 401
    assert student_client.get(f"{API}/admin/stats").status_code == 403
    assert teacher_client.get(f"{API}/admin/stats").status_code == 403


@pytest.mark.parametrize("days", [0, -1, 181, "abc", ""])
def test_stats_days_out_of_range_returns_422(admin_client, days):
    assert admin_client.get(f"{API}/admin/stats", params={"days": days}).status_code == 422


def test_stats_on_empty_system_has_all_keys_with_zeros(admin_client):
    body = admin_client.get(f"{API}/admin/stats").json()
    assert body["days"] == 30 and body["courses"] == []
    assert body["review_status"] == dict.fromkeys(("draft", "pending", "published", "rejected", "archived"), 0)
    assert body["index_status"] == dict.fromkeys(("not_indexed", "queued", "processing", "ready", "failed"), 0)
    assert len(body["daily_qa"]) == 30
    assert all(d["total"] == 0 and d["insufficient_evidence"] == 0 for d in body["daily_qa"])
    assert (body["qa_total"], body["insufficient_evidence_total"], body["insufficient_evidence_ratio"]) == (0, 0, 0.0)


def test_stats_numbers_match_direct_sql(actors, admin_client, db_session_factory, course, course2):
    empty = admin_client.post(f"{API}/courses", json={"name": "Python 程序设计"}).json()
    ready_resource(actors, db_session_factory, course["id"], title="已发布一")
    ready_resource(actors, db_session_factory, course["id"], title="已发布二")
    make_in_state(actors, course2["id"], "published", title="排队中")  # published + queued
    make_in_state(actors, course2["id"], "archived", title="已下架")
    make_in_state(actors, course["id"], "pending", title="待审")
    make_in_state(actors, course["id"], "rejected", title="驳回")
    make_in_state(actors, course["id"], "draft", title="草稿")
    failed = make_in_state(actors, course["id"], "published", title="失败")
    update_resource_row(db_session_factory, failed, index_status="failed")

    body = admin_client.get(f"{API}/admin/stats").json()

    by_course = {c["course_name"]: c for c in body["courses"]}
    assert by_course["数据库原理"]["published_resources"] == 3
    assert by_course["计算机网络"]["published_resources"] == 1
    assert by_course["Python 程序设计"] == {
        "course_id": empty["id"], "course_name": "Python 程序设计", "published_resources": 0,
    }
    for item in body["courses"]:
        assert item["published_resources"] == scalar(
            db_session_factory,
            "SELECT count(*) FROM resources WHERE course_id = :c AND review_status = 'published'",
            c=item["course_id"],
        )
    for status, count in body["review_status"].items():
        assert count == scalar(db_session_factory, "SELECT count(*) FROM resources WHERE review_status = :s", s=status)
    for status, count in body["index_status"].items():
        assert count == scalar(db_session_factory, "SELECT count(*) FROM resources WHERE index_status = :s", s=status)
    assert body["review_status"] == {"draft": 1, "pending": 1, "published": 4, "rejected": 1, "archived": 1}
    assert body["index_status"] == {"not_indexed": 4, "queued": 1, "processing": 0, "ready": 2, "failed": 1}
    assert sum(body["review_status"].values()) == scalar(db_session_factory, "SELECT count(*) FROM resources")


def test_stats_daily_qa_buckets_by_shanghai_day_and_fills_empty_days(admin_client, db_session_factory):
    today = utcnow().astimezone(SHANGHAI).date()
    # 上海时间 00:30 在 UTC 是前一天 16:30；上海时间 23:30 在 UTC 是同一天 15:30
    start_of_day = datetime.combine(today, datetime.min.time(), SHANGHAI).replace(minute=30)
    end_of_day = datetime.combine(today, datetime.min.time(), SHANGHAI).replace(hour=23, minute=30)
    assert start_of_day.astimezone(timezone.utc).date() == today - timedelta(days=1)
    insert_log(db_session_factory, created_at=start_of_day)
    insert_log(db_session_factory, created_at=end_of_day, status="insufficient_evidence")
    insert_log(db_session_factory, created_at=local_noon(-2), status="insufficient_evidence")
    insert_log(db_session_factory, created_at=local_noon(-2), status="llm_timeout")
    insert_log(db_session_factory, created_at=local_noon(-2))
    insert_log(db_session_factory, created_at=local_noon(-40))  # 超出 30 天窗口

    body = admin_client.get(f"{API}/admin/stats", params={"days": 30}).json()

    daily = body["daily_qa"]
    assert len(daily) == 30
    assert [d["date"] for d in daily] == [(today - timedelta(days=29 - i)).isoformat() for i in range(30)]
    by_date = {d["date"]: d for d in daily}
    assert by_date[today.isoformat()] == {"date": today.isoformat(), "total": 2, "insufficient_evidence": 1}
    two_days_ago = (today - timedelta(days=2)).isoformat()
    assert by_date[two_days_ago] == {"date": two_days_ago, "total": 3, "insufficient_evidence": 1}
    assert by_date[(today - timedelta(days=1)).isoformat()]["total"] == 0
    assert body["qa_total"] == 5 and body["insufficient_evidence_total"] == 2
    assert body["insufficient_evidence_ratio"] == pytest.approx(0.4)

    short = admin_client.get(f"{API}/admin/stats", params={"days": 1}).json()
    assert [d["date"] for d in short["daily_qa"]] == [today.isoformat()] and short["qa_total"] == 2
    wide = admin_client.get(f"{API}/admin/stats", params={"days": 180}).json()
    assert len(wide["daily_qa"]) == 180 and wide["qa_total"] == 6


def test_stats_total_matches_database_count_in_window(admin_client, db_session_factory):
    for offset in (0, -1, -1, -5, -29, -30, -31):
        insert_log(db_session_factory, created_at=local_noon(offset))
    body = admin_client.get(f"{API}/admin/stats", params={"days": 30}).json()
    assert body["qa_total"] == 5  # 偏移 -30、-31 在 30 天窗口之外
    assert body["qa_total"] == sum(d["total"] for d in body["daily_qa"])


def test_stats_reflect_questions_asked_through_api(student_client, admin_client):
    ask(student_client)  # 空库：证据不足
    ask(student_client)
    body = admin_client.get(f"{API}/admin/stats").json()
    assert body["qa_total"] == 2 and body["insufficient_evidence_total"] == 2
    assert body["insufficient_evidence_ratio"] == 1.0
    assert body["daily_qa"][-1]["total"] == 2


# ---------------------------------------------------------------- 问答日志

def logs(client, **params):
    resp = client.get(f"{API}/admin/qa-logs", params=params)
    return resp


def test_qa_logs_require_admin(student_client, teacher_client, make_client, seed_users):
    assert make_client().get(f"{API}/admin/qa-logs").status_code == 401
    assert logs(student_client).status_code == 403
    assert logs(teacher_client).status_code == 403


def test_qa_logs_item_shape_and_field_names(admin_client, student_client, db_session_factory, app, course):
    ask(student_client, "没有资料的问题", course_id=course["id"])
    body = logs(admin_client).json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert (body["total"], body["page"], body["page_size"]) == (1, 1, 20)
    item = body["items"][0]
    assert set(item) == {
        "id", "created_at", "course_id", "course_name", "question", "status", "answer", "retrieved",
        "cited_chunk_ids", "timings", "model_config",
    }
    assert item["course_id"] == course["id"] and item["course_name"] == "数据库原理"
    assert item["question"] == "没有资料的问题" and item["status"] == "insufficient_evidence"
    assert item["answer"] == "已发布资料中未找到足够依据" and item["retrieved"] == [] and item["cited_chunk_ids"] == []
    assert set(item["timings"]) == {"retrieval_ms", "generation_ms", "total_ms"}
    assert item["model_config"]["qa_mode"] == "demo"
    forbidden = ("user", "owner", "session", "username")
    assert not [key for key in item if any(word in key for word in forbidden)]


def test_qa_logs_contain_no_user_identifiers(admin_client, student_client, seed_users):
    ask(student_client)
    raw = logs(admin_client).text
    assert not any(user_id in raw for user_id in seed_users.values())
    assert "student01" not in raw and "学生甲" not in raw


def test_qa_logs_ordering_created_at_desc_then_id_desc(admin_client, db_session_factory):
    same = utcnow().replace(microsecond=0)
    ids = sorted(insert_log(db_session_factory, created_at=same, question=f"同时{i}") for i in range(3))
    older = insert_log(db_session_factory, created_at=same - timedelta(minutes=5), question="更早")
    newer = insert_log(db_session_factory, created_at=same + timedelta(minutes=5), question="更晚")
    body = logs(admin_client).json()
    assert [i["id"] for i in body["items"]] == [newer] + ids[::-1] + [older]


def test_qa_logs_pagination(admin_client, db_session_factory):
    base = utcnow().replace(microsecond=0)
    created = [insert_log(db_session_factory, created_at=base + timedelta(seconds=i), question=f"问题{i}") for i in range(5)]
    expected = created[::-1]
    page1 = logs(admin_client, page=1, page_size=2).json()
    page2 = logs(admin_client, page=2, page_size=2).json()
    page3 = logs(admin_client, page=3, page_size=2).json()
    page9 = logs(admin_client, page=9, page_size=2).json()
    assert [i["id"] for i in page1["items"]] == expected[:2]
    assert [i["id"] for i in page2["items"]] == expected[2:4]
    assert [i["id"] for i in page3["items"]] == expected[4:]
    assert page9["items"] == [] and page9["total"] == 5
    assert (page2["page"], page2["page_size"], page2["total"]) == (2, 2, 5)


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"status": "bad"},
                                    {"course_id": "x"}, {"date_from": "2026-13-01"}, {"date_to": "昨天"},
                                    {"date_from": "2026-05-02", "date_to": "2026-05-01"}])
def test_qa_logs_invalid_parameters_return_422(admin_client, params):
    assert logs(admin_client, **params).status_code == 422


def test_qa_logs_page_size_100_is_allowed(admin_client):
    assert logs(admin_client, page_size=100).status_code == 200


def test_qa_logs_filter_by_status_and_course(admin_client, db_session_factory, course, course2):
    a = insert_log(db_session_factory, status="answered", course_id=course["id"])
    b = insert_log(db_session_factory, status="insufficient_evidence", course_id=course["id"])
    c = insert_log(db_session_factory, status="llm_timeout", course_id=course2["id"])
    d = insert_log(db_session_factory, status="answered")  # 不限课程
    ids = lambda **p: {i["id"] for i in logs(admin_client, **p).json()["items"]}  # noqa: E731
    assert ids(status="answered") == {a, d}
    assert ids(status="llm_timeout") == {c}
    assert ids(course_id=course["id"]) == {a, b}
    assert ids(course_id=course["id"], status="answered") == {a}
    assert ids(course_id=str(uuid.uuid4())) == set()
    assert logs(admin_client, status="answered").json()["total"] == 2


def test_qa_logs_date_range_uses_shanghai_days_inclusive(admin_client, db_session_factory):
    def at(day, hour, minute=0):
        return datetime(2026, 5, day, hour, minute, tzinfo=SHANGHAI)

    first_minute = insert_log(db_session_factory, created_at=at(10, 0, 0), question="10日0点")
    last_minute = insert_log(db_session_factory, created_at=at(10, 23, 59), question="10日23点59")
    next_day = insert_log(db_session_factory, created_at=at(11, 0, 0), question="11日0点")
    prev_day = insert_log(db_session_factory, created_at=at(9, 23, 59), question="9日23点59")
    ids = lambda **p: {i["id"] for i in logs(admin_client, **p).json()["items"]}  # noqa: E731
    assert ids(date_from="2026-05-10", date_to="2026-05-10") == {first_minute, last_minute}
    assert ids(date_from="2026-05-10") == {first_minute, last_minute, next_day}
    assert ids(date_to="2026-05-10") == {prev_day, first_minute, last_minute}
    assert ids(date_from="2026-05-09", date_to="2026-05-11") == {prev_day, first_minute, last_minute, next_day}
    assert ids(date_from="2026-05-12") == set()


def test_qa_logs_survive_course_deletion_with_null_course(admin_client, db_session_factory, course):
    insert_log(db_session_factory, course_id=course["id"])
    with db_session_factory() as db:
        db.execute(text("DELETE FROM courses WHERE id = :c"), {"c": course["id"]})
        db.commit()
    item = logs(admin_client).json()["items"][0]
    assert item["course_id"] is None and item["course_name"] is None


def test_qa_log_constraints(db_session_factory):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        insert_log(db_session_factory, status="made_up")
    with pytest.raises(IntegrityError):
        insert_log(db_session_factory, question="   ")
