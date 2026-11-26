"""Extract document text with one-based positions and split by model tokens."""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from pypdf import PdfReader

from app.config import Settings

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT = "text/plain"
MAX_EXTRACTED_CHARS = 1_000_000
MAX_CHUNKS = 4096
SENTENCE_ENDS = frozenset("。！？；.!?;")


class IndexingError(Exception):
    """A short, displayable reason for an indexing failure."""


@dataclass(frozen=True)
class Fragment:
    content: str
    locator: dict[str, str | int]


def extract_units(path: Path, mime_type: str, settings: Settings) -> tuple[str, list[tuple[int, str]]]:
    units = []
    total = 0

    def collect(texts):
        nonlocal total
        for position, raw in enumerate(texts, start=1):
            text = re.sub(r"[^\S\n]+", " ", raw.replace("\x00", " ")).strip()
            if not text:
                continue
            total += len(text)
            if total > MAX_EXTRACTED_CHARS:
                raise IndexingError("文档可提取文字超过索引上限")
            units.append((position, text))

    try:
        with path.open("rb") as stream:
            if mime_type == PDF:
                reader = PdfReader(stream)
                if reader.is_encrypted:
                    raise IndexingError("无法索引加密的 PDF")
                if len(reader.pages) > settings.max_pdf_pages:
                    raise IndexingError("PDF 页数超过索引上限")
                collect(page.extract_text() or "" for page in reader.pages)
                location_type = "pdf_page"
            elif mime_type == DOCX:
                with ZipFile(stream) as archive:
                    if any(entry.flag_bits & 1 for entry in archive.infolist()):
                        raise IndexingError("无法索引加密的 DOCX")
                    if sum(entry.file_size for entry in archive.infolist()) > settings.max_docx_unpacked_bytes:
                        raise IndexingError("DOCX 解包体积超过索引上限")
                stream.seek(0)
                collect(paragraph.text for paragraph in Document(stream).paragraphs)
                location_type = "docx_paragraph"
            elif mime_type == TXT:
                # Decode strictly and preserve physical line positions, including blank lines.
                collect(stream.read().decode("utf-8-sig").splitlines())
                location_type = "txt_line"
            else:
                raise IndexingError("不支持此文档格式")
    except IndexingError:
        raise
    except FileNotFoundError:
        raise IndexingError("找不到资源原件") from None
    except Exception:
        raise IndexingError("无法读取文档正文") from None

    if not units:
        raise IndexingError("未提取到可用文本")
    return location_type, units


def _split_group(units, location_type, tokenizer, size, overlap):
    starts = []
    parts = []
    offset = 0
    for _, text in units:
        starts.append(offset)
        parts.append(text)
        offset += len(text) + 1
    content = "\n".join(parts)
    offsets = tokenizer(content, add_special_tokens=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
    offsets = [(start, end) for start, end in offsets if start < end]
    cursor = 0
    while cursor < len(offsets):
        stop = min(cursor + size, len(offsets))
        if stop < len(offsets):
            # Search the final fifth for a paragraph or sentence ending.
            earliest = max(cursor + overlap + 1, stop - size // 5)
            for boundary in range(stop, earliest - 1, -1):
                end = offsets[boundary - 1][1]
                gap = content[end:offsets[boundary][0]]
                if content[end - 1] in SENTENCE_ENDS or "\n" in gap:
                    stop = boundary
                    break

        start = offsets[cursor][0]
        while stop > cursor:
            end = offsets[stop - 1][1]
            fragment = content[start:end].strip()
            if len(tokenizer(fragment, add_special_tokens=False, verbose=False)["input_ids"]) <= size:
                break
            stop -= 1
        if stop <= cursor:
            raise IndexingError("无法在嵌入模型长度限制内切分正文")

        first = bisect_right(starts, start) - 1
        last = bisect_left(starts, end) - 1
        yield Fragment(fragment, {"type": location_type, "start": units[first][0], "end": units[last][0]})
        if stop == len(offsets):
            return
        cursor = max(cursor + 1, stop - overlap)


def split_document(path: Path, mime_type: str, settings: Settings, tokenizer, model_limit: int) -> list[Fragment]:
    location_type, units = extract_units(path, mime_type, settings)
    special_tokens = tokenizer.num_special_tokens_to_add(pair=False)
    if settings.chunk_overlap >= settings.chunk_size or settings.chunk_size + special_tokens > model_limit:
        raise IndexingError("切块长度或重叠配置超出模型限制")
    groups = ([unit] for unit in units) if location_type == "pdf_page" else (units,)
    fragments = []
    for group in groups:
        for fragment in _split_group(group, location_type, tokenizer, settings.chunk_size, settings.chunk_overlap):
            if len(fragments) == MAX_CHUNKS:
                raise IndexingError("文档片段数超过索引上限")
            fragments.append(fragment)
    if not fragments:
        raise IndexingError("未提取到可用文本")
    return fragments
