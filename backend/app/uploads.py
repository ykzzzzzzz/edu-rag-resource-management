"""资源原件的接收、校验与落盘。

要点：
- multipart 请求体按块流式解析，文件部分边收边写入临时文件并累计字节数，超限立即中止，不会整体读入内存。
- 文件类型按内容校验，扩展名只用来选择校验规则；mime_type 由服务端根据校验结果设定。
- 任何失败路径都清理本次生成的临时文件和正式文件。
"""

import codecs
import os
import re
import secrets
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from app.errors import AppError

MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_TXT = "text/plain"

# 扩展名只决定用哪套内容校验规则，内容不符一律 415
_EXTENSION_TO_MIME = {".pdf": MIME_PDF, ".docx": MIME_DOCX, ".txt": MIME_TXT}

STORAGE_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")

FILENAME_MAX_LENGTH = 200
# 文本字段（标题、课程、描述）的单字段上限，以及整个请求体在文件上限之外允许的开销
MAX_FIELD_BYTES = 16 * 1024
MAX_PARTS = 8
BODY_OVERHEAD_BYTES = 256 * 1024
TEXT_FIELDS = frozenset({"title", "course_id", "description"})
READ_CHUNK = 64 * 1024
PDF_EOF_WINDOW = 4096
PDF_HEADER = re.compile(rb"^%PDF-[12]\.\d")


def _too_large(max_bytes: int) -> AppError:
    return AppError(413, "file_too_large", f"文件大小超过上限（{max_bytes} 字节）")


def _bad_form(message: str = "上传请求格式不正确") -> AppError:
    return AppError(422, "validation_error", message)


def _unsupported(message: str) -> AppError:
    return AppError(415, "unsupported_file_type", message)


def sanitize_filename(raw: str) -> str:
    """去掉路径成分、控制字符和首尾点与空白，并限制长度。仅用于展示和下载名。"""
    name = raw.replace("\\", "/").split("/")[-1]
    # Cc 控制字符、Cf 格式字符（含用于伪装扩展名的双向控制符）
    name = "".join(ch for ch in name if unicodedata.category(ch) not in ("Cc", "Cf"))
    name = name.strip(" .")
    if len(name) > FILENAME_MAX_LENGTH:
        stem, ext = os.path.splitext(name)
        name = stem[: FILENAME_MAX_LENGTH - len(ext)] + ext if len(ext) <= 20 else name[:FILENAME_MAX_LENGTH]
    return name


def content_disposition(filename: str) -> str:
    """生成 attachment 头，同时给出 ASCII 回退名和 RFC 5987 的 filename*。"""
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", filename) or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def unlink_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def stored_path(storage_dir: Path, storage_key: str) -> Path:
    """由 storage_key 得到磁盘路径。storage_key 必须是 32 位小写十六进制，防止路径穿越。"""
    if not STORAGE_KEY_PATTERN.fullmatch(storage_key):
        raise ValueError("invalid storage key")
    return storage_dir / storage_key


@dataclass
class ReceivedUpload:
    """解析完成的上传请求：文本字段、净化后的文件名、已写好的临时文件和字节数。"""

    fields: dict[str, str]
    filename: str
    temp_path: Path
    size: int

    def discard(self) -> None:
        unlink_quietly(self.temp_path)


@dataclass
class _Collector:
    """multipart 解析回调的状态。在线程池中被同步调用。"""

    temp_dir: Path
    max_bytes: int
    fields: dict[str, str] = field(default_factory=dict)
    filename: str | None = None
    temp_path: Path | None = None
    size: int = 0
    finished: bool = False
    _file = None
    _headers: dict[bytes, bytes] = field(default_factory=dict)
    _hname: list[bytes] = field(default_factory=list)
    _hvalue: list[bytes] = field(default_factory=list)
    _kind: str = "none"  # field / file / discard
    _field_name: str = ""
    _buffer: bytearray = field(default_factory=bytearray)
    _parts: int = 0

    def callbacks(self) -> dict:
        return {
            "on_part_begin": self.on_part_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
            "on_end": self.on_end,
        }

    def on_part_begin(self) -> None:
        self._parts += 1
        if self._parts > MAX_PARTS:
            raise _bad_form("上传请求包含过多字段")
        self._headers = {}
        self._hname.clear()
        self._hvalue.clear()
        self._kind = "none"

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._hname.append(data[start:end])

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._hvalue.append(data[start:end])

    def on_header_end(self) -> None:
        self._headers[b"".join(self._hname).lower()] = b"".join(self._hvalue).strip(b" \t")
        self._hname.clear()
        self._hvalue.clear()

    def on_headers_finished(self) -> None:
        _, options = parse_options_header(self._headers.get(b"content-disposition"))
        raw_name = options.get(b"name")
        if raw_name is None:
            raise _bad_form()
        name = raw_name.decode("utf-8", errors="replace")
        raw_filename = options.get(b"filename")

        if raw_filename is None:
            if name not in TEXT_FIELDS or name in self.fields:
                raise _bad_form()
            self._kind = "field"
            self._field_name = name
            self._buffer = bytearray()
            return

        if name != "file" or self.filename is not None:
            raise _bad_form()
        try:
            filename = raw_filename.decode("utf-8")
        except UnicodeDecodeError:
            filename = raw_filename.decode("latin-1")
        if filename == "":
            # 浏览器未选文件时会发送空文件名的部分，按未提供文件处理
            self._kind = "discard"
            return
        self.filename = filename
        self._kind = "file"
        self.temp_path = self.temp_dir / f".upload-{secrets.token_hex(16)}.tmp"
        self._file = open(self.temp_path, "wb")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        if self._kind == "field":
            if len(self._buffer) + len(chunk) > MAX_FIELD_BYTES:
                raise _bad_form("文本字段过长")
            self._buffer += chunk
        elif self._kind == "file":
            # 先检查再写，临时文件永远不会超过上限
            if self.size + len(chunk) > self.max_bytes:
                raise _too_large(self.max_bytes)
            self._file.write(chunk)
            self.size += len(chunk)

    def on_part_end(self) -> None:
        if self._kind == "field":
            try:
                self.fields[self._field_name] = self._buffer.decode("utf-8")
            except UnicodeDecodeError:
                raise _bad_form("文本字段必须是 UTF-8") from None
        elif self._kind == "file":
            self._file.close()
            self._file = None
        self._kind = "none"

    def on_end(self) -> None:
        self.finished = True

    def abort(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        unlink_quietly(self.temp_path)


async def receive_upload(request: Request, storage_dir: Path, max_bytes: int) -> ReceivedUpload:
    """流式解析 multipart 上传。失败时已清理临时文件；成功时由调用方负责 discard 或改名。"""
    content_type, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary")
    if content_type != b"multipart/form-data" or not boundary:
        raise _bad_form("上传必须使用 multipart/form-data")

    limit = max_bytes + BODY_OVERHEAD_BYTES
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise _too_large(max_bytes)

    storage_dir.mkdir(parents=True, exist_ok=True)
    collector = _Collector(temp_dir=storage_dir, max_bytes=max_bytes)
    try:
        parser = MultipartParser(boundary, callbacks=collector.callbacks())
        total = 0
        async for chunk in request.stream():
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise _too_large(max_bytes)
            await run_in_threadpool(parser.write, chunk)
        parser.finalize()
        if not collector.finished:
            raise _bad_form()
        if collector.filename is None or collector.temp_path is None:
            raise _bad_form("缺少上传文件")
    except FormParserError:
        collector.abort()
        raise _bad_form() from None
    except BaseException:
        collector.abort()
        raise
    return ReceivedUpload(
        fields=collector.fields,
        filename=sanitize_filename(collector.filename),
        temp_path=collector.temp_path,
        size=collector.size,
    )


def validate_content(path: Path, filename: str) -> str:
    """按内容校验文件，返回由服务端决定的 mime_type；不合法抛 415。"""
    suffix = os.path.splitext(filename)[1].lower()
    mime = _EXTENSION_TO_MIME.get(suffix)
    if mime is None:
        raise _unsupported("仅支持 PDF、DOCX、UTF-8 TXT 文件")
    size = path.stat().st_size
    if size == 0:
        raise _unsupported("文件为空")

    with open(path, "rb") as fh:
        head = fh.read(8)
        if mime == MIME_PDF:
            # 以 %PDF-1.x / %PDF-2.x 开头，且文件末尾附近有 %%EOF 结束标记，
            # 只在头部写了 %PDF- 的文本文件会被拒绝
            if not PDF_HEADER.match(head):
                raise _unsupported("文件内容不是有效的 PDF")
            fh.seek(max(0, size - PDF_EOF_WINDOW))
            if b"%%EOF" not in fh.read():
                raise _unsupported("文件内容不是有效的 PDF")
        elif mime == MIME_DOCX:
            if not head.startswith(b"PK\x03\x04"):
                raise _unsupported("文件内容不是有效的 DOCX")
            _check_docx(path)
        else:
            # 伪装成文本的 PDF 或 zip 容器直接拒绝
            if head.startswith(b"%PDF-") or head.startswith(b"PK\x03\x04"):
                raise _unsupported("文件内容不是 UTF-8 文本")
            fh.seek(0)
            _check_utf8_text(fh)
    return mime


def _check_docx(path: Path) -> None:
    # 只读取 zip 中央目录的文件名列表，不解压任何内容，避免 zip 炸弹
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, EOFError):
        raise _unsupported("文件内容不是有效的 DOCX") from None
    if "word/document.xml" not in names:
        raise _unsupported("文件内容不是有效的 DOCX")


def _check_utf8_text(fh) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    try:
        while chunk := fh.read(READ_CHUNK):
            if b"\x00" in chunk:
                raise _unsupported("文件内容不是 UTF-8 文本")
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise _unsupported("文件内容不是 UTF-8 文本") from None


def new_storage_key() -> str:
    return secrets.token_hex(16)
