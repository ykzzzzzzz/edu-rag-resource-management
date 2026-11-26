import io
import os
import re
from datetime import datetime, timezone

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select

from app.index_documents import Fragment, IndexingError, extract_units, split_document
from app.index_worker import DocumentProcessor, TIMEOUT_REASON, claim, finish, run_once
from app.models import ResourceChunk
from tests.resource_helpers import API, MIME_DOCX, MIME_PDF, MIME_TXT, fetch_resource, make_docx, make_in_state, update_resource_row


class CharacterTokenizer:
    def __call__(self, text, **kwargs):
        spans = [match.span() for match in re.finditer(r"\S", text)]
        return {"input_ids": list(range(len(spans))), "offset_mapping": spans}

    def num_special_tokens_to_add(self, pair):
        return 2


class TestDocumentProcessor:
    __test__ = False

    def __init__(self, settings):
        self.settings = settings

    def run(self, path, mime_type, timeout):
        fragments = split_document(path, mime_type, self.settings, CharacterTokenizer(), 512)
        return [(chunk, [1.0] + [0.0] * 511) for chunk in fragments]

    def close(self):
        pass


def _pdf_sample():
    writer = PdfWriter()
    for line in ("First page of teaching notes.", None, "Third page of teaching notes."):
        page = writer.add_blank_page(width=200, height=200)
        if line is not None:
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({
                    NameObject("/F1"): DictionaryObject({
                        NameObject("/Type"): NameObject("/Font"),
                        NameObject("/Subtype"): NameObject("/Type1"),
                        NameObject("/BaseFont"): NameObject("/Helvetica"),
                    }),
                }),
            })
            data = DecodedStreamObject()
            data.set_data(f"BT /F1 12 Tf 10 30 Td ({line}) Tj ET".encode("ascii"))
            page.replace_contents(data)
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def _docx_sample():
    document = Document()
    for paragraph in ("第一段教学资料。", "", "第三段教学资料。"):
        document.add_paragraph(paragraph)
    target = io.BytesIO()
    document.save(target)
    return target.getvalue()


def _chunks(factory, rid):
    with factory() as db:
        stmt = select(ResourceChunk).where(ResourceChunk.resource_id == rid).order_by(ResourceChunk.chunk_index)
        return db.scalars(stmt).all()


def test_worker_indexes_three_formats_with_original_positions(actors, course, db_session_factory, app):
    settings = app.state.settings
    samples = [
        ("notes.pdf", _pdf_sample(), "pdf_page", [(1, 1), (3, 3)]),
        ("notes.docx", _docx_sample(), "docx_paragraph", [(1, 3)]),
        ("notes.txt", "第一行教学资料。\r\n\r\n第三行教学资料。".encode("utf-8-sig"), "txt_line", [(1, 3)]),
    ]
    ids = [make_in_state(actors, course["id"], "published", filename=name, content=data) for name, data, _, _ in samples]
    processor = DocumentProcessor(settings) if os.environ.get("SCF_TEST_REAL_EMBEDDINGS") == "1" else TestDocumentProcessor(settings)
    try:
        for _ in ids:
            assert run_once(db_session_factory, settings, processor)
        assert not run_once(db_session_factory, settings, processor)
    finally:
        processor.close()
    for rid, (_, _, locator_type, locations) in zip(ids, samples, strict=True):
        rows = _chunks(db_session_factory, rid)
        assert fetch_resource(db_session_factory, rid).index_status == "ready"
        assert [row.locator for row in rows] == [
            {"type": locator_type, "start": start, "end": end} for start, end in locations
        ]
        assert all(len(row.embedding) == 512 for row in rows)
        assert all(row.embedding_model.endswith(settings.embedding_revision) for row in rows)


def test_split_long_text_uses_token_overlap_and_keeps_line_numbers(tmp_path, app):
    path = tmp_path / "lines.txt"
    path.write_text("abcdefghij\n\nklmnop", encoding="utf-8")
    settings = app.state.settings.model_copy(update={"chunk_size": 6, "chunk_overlap": 2})
    fragments = split_document(path, MIME_TXT, settings, CharacterTokenizer(), 8)
    assert [fragment.content for fragment in fragments] == ["abcdef", "efghij", "ij\nklmn", "mnop"]
    assert [(item.locator["start"], item.locator["end"]) for item in fragments] == [(1, 1), (1, 1), (1, 3), (3, 3)]
    with pytest.raises(IndexingError, match="模型限制"):
        split_document(path, MIME_TXT, settings, CharacterTokenizer(), 7)


def test_parser_limits_pdf_pages_and_docx_unpacked_size(tmp_path, app):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(_pdf_sample())
    settings = app.state.settings.model_copy(update={"max_pdf_pages": 2, "max_docx_unpacked_bytes": 100})
    with pytest.raises(IndexingError, match="PDF 页数"):
        extract_units(pdf, MIME_PDF, settings)
    docx = tmp_path / "test.docx"
    docx.write_bytes(make_docx({"word/media/compressed.bin": b"x" * 1024}))
    with pytest.raises(IndexingError, match="DOCX 解包体积"):
        extract_units(docx, MIME_DOCX, settings)


def test_worker_empty_resource_can_be_retried_without_chunks(actors, course, db_session_factory, app):
    rid = make_in_state(actors, course["id"], "published", content=b" \n\n")
    settings = app.state.settings
    processor = TestDocumentProcessor(settings)
    assert run_once(db_session_factory, settings, processor)
    row = fetch_resource(db_session_factory, rid)
    assert row.index_status == "failed"
    assert row.index_error == "未提取到可用文本"
    assert _chunks(db_session_factory, rid) == []
    (settings.resource_storage_dir / row.storage_key).write_text("修复后的测试正文", encoding="utf-8")
    assert actors.admin.post(f"{API}/admin/resources/{rid}/index/retry").status_code == 202
    assert run_once(db_session_factory, settings, processor)
    assert fetch_resource(db_session_factory, rid).index_status == "ready"
    assert len(_chunks(db_session_factory, rid)) == 1


def test_replacement_is_idempotent_and_keeps_other_configurations(actors, course, db_session_factory, app):
    rid = make_in_state(actors, course["id"], "published")
    settings = app.state.settings
    variants = [settings, settings.model_copy(update={"chunk_size": 200}), settings]
    for variant in variants:
        update_resource_row(db_session_factory, rid, index_status="queued")
        assert run_once(db_session_factory, variant, TestDocumentProcessor(variant))
    rows = _chunks(db_session_factory, rid)
    assert sorted(row.chunk_config for row in rows) == ["v1:200:50", "v1:350:50"]


@pytest.mark.parametrize("cancel", ["archive", "expire"])
def test_cancelled_or_expired_attempt_cannot_write_chunks(actors, course, db_session_factory, app, cancel):
    rid = make_in_state(actors, course["id"], "published")
    job = claim(db_session_factory, 300)
    if cancel == "archive":
        assert actors.admin.post(f"{API}/admin/resources/{rid}/archive").status_code == 200
    else:
        update_resource_row(db_session_factory, rid, index_lease_until=datetime(2020, 1, 1, tzinfo=timezone.utc))
        assert claim(db_session_factory, 300) is None
        assert fetch_resource(db_session_factory, rid).index_error == TIMEOUT_REASON
        assert actors.admin.post(f"{API}/admin/resources/{rid}/index/retry").status_code == 202
        retry = claim(db_session_factory, 300)
        assert retry.token != job.token

    records = [(Fragment("旧任务结果", {"type": "txt_line", "start": 1, "end": 1}), [0.0] * 512)]
    assert not finish(db_session_factory, app.state.settings, job, records)
    assert _chunks(db_session_factory, rid) == []
    if cancel == "expire":
        assert fetch_resource(db_session_factory, rid).index_attempt_id == retry.token
