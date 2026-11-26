"""资源上传、元数据修改、详情、下载与文件校验。"""

import json
import re
import threading
import uuid

import pytest
from sqlalchemy.exc import OperationalError

from tests.resource_helpers import (
    API,
    MIME_DOCX,
    MIME_PDF,
    MIME_TXT,
    PDF_BYTES,
    TXT_BYTES,
    disk_files,
    fetch_resource,
    make_docx,
    upload,
    uploaded_id,
)


# ---------- 上传成功 ----------


@pytest.mark.parametrize(
    ("filename", "content", "mime"),
    [
        ("讲义.pdf", PDF_BYTES, MIME_PDF),
        ("讲义.docx", make_docx(), MIME_DOCX),
        ("讲义.txt", TXT_BYTES, MIME_TXT),
        ("UPPER.PDF", PDF_BYTES, MIME_PDF),
    ],
)
def test_teacher_uploads_valid_file_as_draft(teacher_client, course, storage_dir, filename, content, mime):
    resp = upload(
        teacher_client,
        course["id"],
        title="  事务讲义  ",
        description="第一章",
        filename=filename,
        content=content,
        content_type="application/octet-stream",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "事务讲义"
    assert body["review_status"] == "draft"
    assert body["index_status"] == "not_indexed"
    assert body["mime_type"] == mime
    assert body["size_bytes"] == len(content)
    assert body["original_filename"] == filename
    assert body["course_name"] == course["name"]
    assert body["published_at"] is None
    assert len(disk_files(storage_dir)) == 1


def test_mime_type_is_decided_by_server_not_client(teacher_client, course):
    resp = upload(teacher_client, course["id"], filename="a.txt", content=TXT_BYTES, content_type="application/pdf")
    assert resp.status_code == 201
    assert resp.json()["mime_type"] == MIME_TXT


def test_upload_response_and_all_views_never_leak_storage_key_or_path(
    teacher_client, admin_client, student_client, course, storage_dir, db_session_factory
):
    created = upload(teacher_client, course["id"])
    assert created.status_code == 201
    rid = created.json()["id"]
    key = fetch_resource(db_session_factory, rid).storage_key
    assert re.fullmatch(r"[0-9a-f]{32}", key)
    assert disk_files(storage_dir) == [key]
    assert teacher_client.post(f"{API}/resources/{rid}/submit").status_code == 200
    assert admin_client.post(f"{API}/admin/resources/{rid}/review", json={"action": "approve"}).status_code == 200

    responses = [
        teacher_client.get(f"{API}/resources/{rid}"),
        teacher_client.get(f"{API}/resources/mine"),
        admin_client.get(f"{API}/resources/{rid}"),
        admin_client.get(f"{API}/admin/resources"),
        student_client.get(f"{API}/resources/{rid}"),
        student_client.get(f"{API}/resources"),
    ]
    assert all(resp.status_code == 200 for resp in responses)
    responses.append(created)
    escaped_path = json.dumps(str(storage_dir), ensure_ascii=False)[1:-1]
    for resp in responses:
        assert key not in resp.text
        assert escaped_path not in resp.text
        assert "storage_key" not in resp.text
    dl = teacher_client.get(f"{API}/resources/{rid}/download")
    assert dl.status_code == 200
    assert key not in str(dl.headers)
    assert str(storage_dir) not in str(dl.headers)


def test_storage_key_is_random_and_distinct(teacher_client, course, db_session_factory):
    keys = {
        fetch_resource(db_session_factory, uploaded_id(teacher_client, course["id"])).storage_key for _ in range(3)
    }
    assert len(keys) == 3


def test_uploaded_file_is_not_served_statically(teacher_client, course, storage_dir, db_session_factory):
    rid = uploaded_id(teacher_client, course["id"])
    key = fetch_resource(db_session_factory, rid).storage_key
    for url in (f"/uploads/{key}", f"/static/{key}", f"/data/local/uploads/{key}", f"{API}/uploads/{key}"):
        assert teacher_client.get(url).status_code == 404


def test_filename_path_components_are_stripped(teacher_client, course):
    resp = upload(teacher_client, course["id"], filename="../../etc/passwd/..\\..\\讲义.txt")
    assert resp.status_code == 201
    assert resp.json()["original_filename"] == "讲义.txt"


def test_long_filename_is_truncated_keeping_extension(teacher_client, course):
    resp = upload(teacher_client, course["id"], filename="很" * 400 + ".txt")
    assert resp.status_code == 201
    name = resp.json()["original_filename"]
    assert len(name) <= 200 and name.endswith(".txt")


def test_title_is_required_and_trimmed_blank_rejected(teacher_client, course, storage_dir):
    assert upload(teacher_client, course["id"], title="   ").status_code == 422
    resp = teacher_client.post(
        f"{API}/resources", data={"course_id": course["id"]}, files={"file": ("a.txt", TXT_BYTES)}
    )
    assert resp.status_code == 422
    assert disk_files(storage_dir) == []


def test_missing_file_returns_422(teacher_client, course):
    assert upload(teacher_client, course["id"], include_file=False).status_code == 422


def test_unknown_form_field_returns_422(teacher_client, course, storage_dir):
    resp = upload(teacher_client, course["id"], data_extra={"review_status": "published"})
    assert resp.status_code == 422
    assert disk_files(storage_dir) == []


def test_non_multipart_upload_returns_422(teacher_client, course):
    resp = teacher_client.post(f"{API}/resources", json={"title": "x", "course_id": course["id"]})
    assert resp.status_code == 422


def test_unknown_course_returns_422_and_cleans_disk(teacher_client, storage_dir):
    resp = upload(teacher_client, uuid.uuid4())
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "course_not_found"
    assert disk_files(storage_dir) == []


def test_malformed_course_id_returns_422(teacher_client, course):
    resp = upload(teacher_client, "not-a-uuid")
    assert resp.status_code == 422


def test_title_with_nul_character_returns_422(teacher_client, course, storage_dir):
    assert upload(teacher_client, course["id"], title="a\x00b").status_code == 422
    assert disk_files(storage_dir) == []


# ---------- 文件内容校验（415） ----------


@pytest.mark.parametrize(
    ("label", "filename", "content"),
    [
        ("扩展名不在白名单", "script.exe", b"MZ\x90\x00"),
        ("扩展名伪造：PDF 内容改名 .png", "a.png", PDF_BYTES),
        ("无扩展名", "README", TXT_BYTES),
        ("空文件 txt", "empty.txt", b""),
        ("空文件 pdf", "empty.pdf", b""),
        ("空文件 docx", "empty.docx", b""),
        ("伪造 PDF 头的纯文本", "fake.pdf", b"%PDF- this is just text, not a pdf"),
        ("PDF 头正确但无结束标记", "trunc.pdf", b"%PDF-1.4\n" + b"x" * 100),
        ("文本改名为 pdf", "text.pdf", "普通文本".encode()),
        ("非 UTF-8 的 txt（GBK）", "gbk.txt", "中文内容".encode("gbk")),
        ("txt 含 NUL 字节", "nul.txt", b"hello\x00world"),
        ("txt 实为 PDF", "pdf-as.txt", PDF_BYTES),
        ("txt 实为 docx", "docx-as.txt", make_docx()),
        ("非 zip 的 docx", "fake.docx", b"this is not a zip file at all"),
        ("zip 魔数但已损坏的 docx", "broken.docx", b"PK\x03\x04" + b"\x00" * 30),
        ("缺 word/document.xml 的 zip", "nodoc.docx", make_docx(with_document=False)),
        ("document.xml 位置错误的 zip", "wrongpath.docx", make_docx(with_document=False, extra={"document.xml": b"x"})),
        ("PDF 内容改名 docx", "pdf-as.docx", PDF_BYTES),
    ],
)
def test_invalid_content_returns_415_and_leaves_no_file(teacher_client, course, storage_dir, label, filename, content):
    resp = upload(teacher_client, course["id"], filename=filename, content=content, content_type=MIME_PDF)
    assert resp.status_code == 415, label
    assert resp.json()["error"]["code"] == "unsupported_file_type"
    assert disk_files(storage_dir) == [], label


def test_utf8_txt_with_bom_and_crlf_is_accepted(teacher_client, course):
    resp = upload(teacher_client, course["id"], filename="bom.txt", content=b"\xef\xbb\xbf" + "你好\r\n世界".encode())
    assert resp.status_code == 201


def test_docx_check_does_not_decompress_contents(teacher_client, course, monkeypatch):
    """防 zip 炸弹：校验只读文件名列表，不得调用 read / extract。"""
    import zipfile

    content = make_docx()

    def boom(*args, **kwargs):
        raise AssertionError("不应解压 zip 内容")

    monkeypatch.setattr(zipfile.ZipFile, "read", boom)
    monkeypatch.setattr(zipfile.ZipFile, "extract", boom)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", boom)
    monkeypatch.setattr(zipfile.ZipFile, "open", boom)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", boom)
    resp = upload(teacher_client, course["id"], filename="a.docx", content=content)
    assert resp.status_code == 201


def test_high_compression_docx_is_accepted_without_expanding(teacher_client, course):
    bomb = make_docx(extra={"word/media/big.bin": b"\x00" * (50 * 1024 * 1024)})
    assert len(bomb) < 1024 * 1024
    resp = upload(teacher_client, course["id"], filename="bomb.docx", content=bomb)
    assert resp.status_code == 201


# ---------- 超限（413） ----------


@pytest.fixture
def small_limit(app):
    """把上传上限调到 1 KiB，便于流式超限测试。"""
    app.state.settings.max_upload_bytes = 1024
    return 1024


def test_file_at_limit_is_accepted_and_one_over_is_413(teacher_client, course, storage_dir, small_limit):
    ok = upload(teacher_client, course["id"], content=b"a" * small_limit)
    assert ok.status_code == 201
    assert len(disk_files(storage_dir)) == 1

    over = upload(teacher_client, course["id"], content=b"a" * (small_limit + 1))
    assert over.status_code == 413
    assert over.json()["error"]["code"] == "file_too_large"
    assert len(disk_files(storage_dir)) == 1  # 只剩第一次成功的那个，超限的没有残留


def test_oversize_aborts_streaming_without_reading_everything(teacher_client, course, storage_dir, small_limit, monkeypatch):
    """解析中途超限即中止：磁盘上的临时文件字节数不会超过上限，且没有残留。"""
    from app import uploads

    peak = {"bytes": 0}
    original = uploads._Collector.on_part_data

    def spy(self, data, start, end):
        original(self, data, start, end)
        peak["bytes"] = max(peak["bytes"], self.size)

    monkeypatch.setattr(uploads._Collector, "on_part_data", spy)
    resp = upload(teacher_client, course["id"], content=b"a" * (small_limit * 50))
    assert resp.status_code == 413
    assert peak["bytes"] <= small_limit
    assert disk_files(storage_dir) == []


def test_oversize_declared_content_length_is_rejected_early(teacher_client, course, storage_dir, small_limit, monkeypatch):
    from app import uploads

    called = {"stream": False}
    original = uploads._Collector.on_part_begin

    def spy(self):
        called["stream"] = True
        original(self)

    monkeypatch.setattr(uploads._Collector, "on_part_begin", spy)
    resp = upload(teacher_client, course["id"], content=b"a" * (uploads.BODY_OVERHEAD_BYTES + small_limit + 10))
    assert resp.status_code == 413
    assert called["stream"] is False  # 根据 Content-Length 在解析前就拒绝
    assert disk_files(storage_dir) == []


def test_default_upload_limit_is_20_mib(app):
    from app.config import Settings

    assert Settings(database_url="postgresql://x").max_upload_bytes == 20 * 1024 * 1024


def test_default_storage_dir_is_under_ignored_data_local():
    from app.config import REPO_ROOT, Settings

    default = Settings(database_url="postgresql://x").resource_storage_dir
    assert default == REPO_ROOT / "data" / "local" / "uploads"


# ---------- 数据库失败时清理 ----------


def test_database_commit_failure_leaves_no_file(teacher_client, course, storage_dir, app, monkeypatch):
    from sqlalchemy.orm import Session

    original_commit = Session.commit

    def failing_commit(self):
        if any(type(obj).__name__ == "Resource" for obj in self.new):
            raise OperationalError("INSERT", {}, Exception("simulated db failure"))
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", failing_commit)
    quiet = type(teacher_client)(app, headers={"Origin": "http://localhost:5173"}, raise_server_exceptions=False)
    quiet.cookies.update(teacher_client.cookies)
    resp = upload(quiet, course["id"])
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    assert disk_files(storage_dir) == []


def test_database_failure_does_not_leave_row_either(teacher_client, admin_client, course, storage_dir, app, monkeypatch):
    from sqlalchemy.orm import Session

    original_commit = Session.commit

    def failing_commit(self):
        if any(type(obj).__name__ == "Resource" for obj in self.new):
            raise OperationalError("INSERT", {}, Exception("simulated db failure"))
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", failing_commit)
    quiet = type(teacher_client)(app, headers={"Origin": "http://localhost:5173"}, raise_server_exceptions=False)
    quiet.cookies.update(teacher_client.cookies)
    assert upload(quiet, course["id"]).status_code == 500
    monkeypatch.undo()
    assert admin_client.get(f"{API}/admin/resources").json()["total"] == 0


def test_validation_failure_after_temp_write_cleans_temp_file(teacher_client, course, storage_dir):
    assert upload(teacher_client, course["id"], filename="x.docx", content=b"nope").status_code == 415
    assert disk_files(storage_dir) == []  # 包括 .upload-*.tmp


def test_response_read_failure_preserves_committed_file(teacher_client, course, app, monkeypatch):
    from app import resource_queries

    def fail_to_read(*args):
        raise OperationalError("SELECT", {}, Exception("simulated response read failure"))

    with type(teacher_client)(app, headers=teacher_client.headers, raise_server_exceptions=False) as quiet:
        quiet.cookies.update(teacher_client.cookies)
        with monkeypatch.context() as patch:
            patch.setattr(resource_queries, "load_out", fail_to_read)
            assert upload(quiet, course["id"]).status_code == 500

    items = teacher_client.get(f"{API}/resources/mine").json()["items"]
    assert len(items) == 1
    download = teacher_client.get(f"{API}/resources/{items[0]['id']}/download")
    assert download.status_code == 200
    assert download.content == TXT_BYTES


# ---------- PATCH ----------


def test_teacher_patches_own_draft(teacher_client, course, course2):
    rid = uploaded_id(teacher_client, course["id"], description="旧描述")
    resp = teacher_client.patch(
        f"{API}/resources/{rid}",
        json={"title": "  新标题 ", "course_id": course2["id"], "description": "新描述"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["title"], body["course_id"], body["description"]) == ("新标题", course2["id"], "新描述")
    assert body["course_name"] == course2["name"]


def test_patch_can_clear_description(teacher_client, course):
    rid = uploaded_id(teacher_client, course["id"], description="有描述")
    resp = teacher_client.patch(f"{API}/resources/{rid}", json={"description": None})
    assert resp.status_code == 200 and resp.json()["description"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},
        {"title": "   "},
        {"title": None},
        {"course_id": None},
        {"course_id": "bad"},
        {"review_status": "published"},
        {"storage_key": "x"},
        {"owner_id": str(uuid.uuid4())},
        {"title": "x" * 201},
    ],
)
def test_patch_invalid_payload_returns_422(teacher_client, course, payload):
    rid = uploaded_id(teacher_client, course["id"])
    assert teacher_client.patch(f"{API}/resources/{rid}", json=payload).status_code == 422


def test_patch_unknown_course_returns_422_and_keeps_data(teacher_client, course):
    rid = uploaded_id(teacher_client, course["id"], title="原标题")
    resp = teacher_client.patch(f"{API}/resources/{rid}", json={"title": "改", "course_id": str(uuid.uuid4())})
    assert resp.status_code == 422
    assert teacher_client.get(f"{API}/resources/{rid}").json()["title"] == "原标题"


@pytest.mark.parametrize("state", ["pending", "published", "rejected", "archived"])
def test_patch_non_draft_returns_409(actors, course, state):
    from tests.resource_helpers import make_in_state

    rid = make_in_state(actors, course["id"], state)
    resp = actors.owner.patch(f"{API}/resources/{rid}", json={"title": "改"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invalid_state"


def test_patch_other_teachers_draft_returns_404(teacher_client, teacher2_client, course):
    rid = uploaded_id(teacher_client, course["id"])
    assert teacher2_client.patch(f"{API}/resources/{rid}", json={"title": "抢改"}).status_code == 404
    assert teacher_client.get(f"{API}/resources/{rid}").json()["title"] == "示例资料"


def test_patch_unknown_resource_returns_404(teacher_client):
    assert teacher_client.patch(f"{API}/resources/{uuid.uuid4()}", json={"title": "x"}).status_code == 404


# ---------- 下载 ----------


def test_download_returns_original_bytes_and_safe_headers(teacher_client, course):
    rid = uploaded_id(teacher_client, course["id"], filename="a.pdf", content=PDF_BYTES)
    resp = teacher_client.get(f"{API}/resources/{rid}/download")
    assert resp.status_code == 200
    assert resp.content == PDF_BYTES
    assert resp.headers["content-type"] == MIME_PDF
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-disposition"].startswith("attachment;")
    assert "no-store" in resp.headers["cache-control"]


def test_download_chinese_filename_uses_rfc5987(teacher_client, course):
    from urllib.parse import quote

    name = "数据库原理 讲义（第1章）.txt"
    rid = uploaded_id(teacher_client, course["id"], filename=name)
    disp = teacher_client.get(f"{API}/resources/{rid}/download").headers["content-disposition"]
    disp.encode("latin-1")  # 头必须是纯 ASCII，否则会在传输层出错
    assert f"filename*=UTF-8''{quote(name, safe='')}" in disp
    assert 'filename="' in disp and "数据库" not in disp


def test_download_filename_cannot_inject_header_or_break_quoting(teacher_client, course):
    rid = uploaded_id(teacher_client, course["id"], filename='a";b\r\nX-Evil: 1.txt')
    resp = teacher_client.get(f"{API}/resources/{rid}/download")
    assert resp.status_code == 200
    assert "x-evil" not in resp.headers
    assert "\r" not in resp.headers["content-disposition"] and "\n" not in resp.headers["content-disposition"]
    fallback = re.search(r'filename="([^"]*)"', resp.headers["content-disposition"]).group(1)
    assert '"' not in fallback and ";" not in fallback


def test_download_when_disk_file_missing_returns_404(teacher_client, course, storage_dir):
    rid = uploaded_id(teacher_client, course["id"])
    for p in storage_dir.iterdir():
        p.unlink()
    resp = teacher_client.get(f"{API}/resources/{rid}/download")
    assert resp.status_code == 404
    assert str(storage_dir) not in resp.text


def test_download_unknown_resource_returns_404(student_client):
    assert student_client.get(f"{API}/resources/{uuid.uuid4()}/download").status_code == 404


def test_malformed_resource_id_returns_422(student_client):
    assert student_client.get(f"{API}/resources/not-a-uuid").status_code == 422


def test_concurrent_uploads_do_not_collide(teacher_client, course, storage_dir):
    results: list[int] = []

    def worker():
        results.append(upload(teacher_client, course["id"], content=TXT_BYTES + uuid.uuid4().hex.encode()).status_code)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [201] * 4
    assert len(disk_files(storage_dir)) == 4
