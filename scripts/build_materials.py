"""把 evaluation/course-materials.txt 转换成真实的 PDF / DOCX / TXT 样例资料，并生成金标准定位表。

输出到 data/samples/materials/{DB,NET,PY}/，另外生成：
- key_facts.jsonl：每条"关键事实"在生成文件中的位置（用后端 extract_units 的解析规则定位）
- manifest.json：每份资料的清单（大小、sha256、单元数、字数等）

只读取源文本和后端解析函数，不读 .env，不连数据库，不联网。可重复运行，输出逐字节一致。

运行：
  E:\\scf-env\\venv\\Scripts\\python.exe -I scripts\\build_materials.py
需要 reportlab（见 scripts/requirements-materials.txt）。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
DEFAULT_SOURCE = REPO_ROOT / "evaluation" / "course-materials.txt"
DEFAULT_OUT = REPO_ROOT / "data" / "samples" / "materials"

PAGE_MARK = "【分页】"
COURSE_PREFIXES = ("DB", "NET", "PY")
FORMATS = ("pdf", "docx", "txt")
EXPECTED_MATERIALS = 24
EXPECTED_FACT_TABLES = 3

SOURCE_NOTE = "由 AI 辅助生成的虚构教学资料，非真实机构内容"
LICENSE_NOTE = "自编虚构内容，可公开分发"
GENERATED_BY = "scripts/build_materials.py"
DOC_AUTHOR = "启明教育培训中心（虚构）"
DOC_COMMENT = SOURCE_NOTE

# 固定时间戳，保证重复生成的 DOCX 逐字节一致
FIXED_TIME = datetime(2026, 1, 1, 0, 0, 0)
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)

FONT_DIR = Path(r"C:\Windows\Fonts")
FONT_BODY_FILE = FONT_DIR / "simsun.ttc"  # 宋体，取 subfontIndex=0
FONT_HEADING_FILE = FONT_DIR / "msyhbd.ttc"  # 微软雅黑粗体，仅用于 PDF 小标题
DOCX_FONT = "宋体"

PDF_MARGINS_MM = (20, 16, 12)
PDF_FONT_SIZES = (11, 10.5, 10, 9.5, 9, 8.5, 8, 7.5)

MIME_BY_FORMAT = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}
LOCATOR_TYPE_BY_FORMAT = {"pdf": "pdf_page", "docx": "docx_paragraph", "txt": "txt_line"}

FACT_RE = re.compile(r"^(\d+)\.\s*「(.*)」\s*$")
HEADER_KEYS = ("编号", "课程", "类型", "标题", "格式", "版本")


class BuildError(Exception):
    """源文件结构或生成结果不符合预期。"""


# ---------------------------------------------------------------- 解析源文本


@dataclass(frozen=True)
class Fact:
    no: int
    text: str


@dataclass(frozen=True)
class Material:
    id: str
    course: str
    type: str
    title: str
    format: str
    version: str
    body_lines: tuple[str, ...]
    facts: tuple[Fact, ...]

    @property
    def prefix(self) -> str:
        return self.id.split("-")[0]

    @property
    def filename(self) -> str:
        type_name = re.sub(r"\s+", "", self.type)
        return f"{self.id}-{type_name}.{self.format}"

    @property
    def relative_path(self) -> str:
        return f"{self.prefix}/{self.filename}"


@dataclass(frozen=True)
class FactTable:
    course: str
    lines: tuple[str, ...]


def squash(text: str) -> str:
    """去掉所有空白字符，用于定位比较。"""
    return re.sub(r"\s+", "", text)


def parse_source(text: str) -> tuple[list[FactTable], list[Material]]:
    """解析资料文本。只认 === 块 ===；块外文字（如"本批完成"）一律忽略。"""
    lines = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tables: list[FactTable] = []
    materials: list[Material] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line == "=== 事实表开始 ===":
            end = _find(lines, i + 1, "=== 事实表结束 ===", "事实表")
            course = ""
            body = []
            for raw in lines[i + 1 : end]:
                if raw.startswith("课程："):
                    course = raw.split("：", 1)[1].strip()
                elif raw.strip():
                    body.append(raw)
            if not course:
                raise BuildError(f"第 {i + 1} 行起的事实表缺少课程名")
            tables.append(FactTable(course, tuple(body)))
            i = end + 1
        elif line == "=== 资料开始 ===":
            end = _find(lines, i + 1, "=== 资料结束 ===", "资料")
            materials.append(_parse_material(lines[i + 1 : end], i + 2))
            i = end + 1
        else:
            i += 1
    _check_collection(tables, materials)
    return tables, materials


def _find(lines: list[str], start: int, marker: str, what: str) -> int:
    for j in range(start, len(lines)):
        if lines[j].strip() == marker:
            return j
        if lines[j].strip() in ("=== 事实表开始 ===", "=== 资料开始 ==="):
            break
    raise BuildError(f"第 {start} 行起的{what}块没有找到结束标记 {marker}")


def _parse_material(block: list[str], first_line_no: int) -> Material:
    try:
        body_at = block.index("--- 正文 ---")
        facts_at = block.index("--- 关键事实 ---")
    except ValueError:
        raise BuildError(f"第 {first_line_no} 行起的资料块缺少 正文/关键事实 分隔行") from None
    if facts_at < body_at:
        raise BuildError(f"第 {first_line_no} 行起的资料块 正文/关键事实 顺序颠倒")

    header: dict[str, str] = {}
    for raw in block[:body_at]:
        if not raw.strip():
            continue
        if "：" not in raw:
            raise BuildError(f"第 {first_line_no} 行起的资料头部无法解析：{raw!r}")
        key, value = raw.split("：", 1)
        header[key.strip()] = value.strip()
    missing = [k for k in HEADER_KEYS if not header.get(k)]
    if missing:
        raise BuildError(f"第 {first_line_no} 行起的资料头部缺少：{missing}")

    body = block[body_at + 1 : facts_at]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if not body:
        raise BuildError(f"{header['编号']} 正文为空")

    facts: list[Fact] = []
    for raw in block[facts_at + 1 :]:
        if not raw.strip():
            continue
        m = FACT_RE.match(raw.strip())
        if not m:
            raise BuildError(f"{header['编号']} 关键事实行格式不对：{raw!r}")
        facts.append(Fact(int(m.group(1)), m.group(2)))
    if [f.no for f in facts] != list(range(1, len(facts) + 1)):
        raise BuildError(f"{header['编号']} 关键事实编号不是从 1 开始连续递增")

    material = Material(
        id=header["编号"],
        course=header["课程"],
        type=header["类型"],
        title=header["标题"],
        format=header["格式"].lower(),
        version=header["版本"],
        body_lines=tuple(body),
        facts=tuple(facts),
    )
    if material.prefix not in COURSE_PREFIXES:
        raise BuildError(f"{material.id} 的编号前缀不在 {COURSE_PREFIXES} 内")
    if material.format not in FORMATS:
        raise BuildError(f"{material.id} 的格式 {material.format!r} 不支持")
    if material.format == "pdf":
        for line in material.body_lines:
            if PAGE_MARK in line and line.strip() != PAGE_MARK:
                raise BuildError(f"{material.id} 有 {PAGE_MARK} 没有单独成行：{line[:30]!r}")
    elif any(PAGE_MARK in line for line in material.body_lines):
        raise BuildError(f"{material.id} 不是 PDF，却含有 {PAGE_MARK}")
    return material


def _check_collection(tables: list[FactTable], materials: list[Material]) -> None:
    if len(tables) != EXPECTED_FACT_TABLES:
        raise BuildError(f"事实表应有 {EXPECTED_FACT_TABLES} 个，实际 {len(tables)} 个")
    if len(materials) != EXPECTED_MATERIALS:
        raise BuildError(f"资料块应有 {EXPECTED_MATERIALS} 个，实际 {len(materials)} 个")
    ids = [m.id for m in materials]
    if len(set(ids)) != len(ids):
        raise BuildError("资料编号有重复")
    names = [m.relative_path for m in materials]
    if len(set(names)) != len(names):
        raise BuildError("生成的文件名有重复")


# ---------------------------------------------------------------- 正文结构


def is_heading(line: str) -> bool:
    """小标题：单行、不含句号和其他句内标点、不超过 30 字。

    源文件里大多数小标题形如"一、课程目标"，但 DB-05、DB-08 的小标题没有序号
    （如"实验一 器材登记"），所以不要求序号。docx 正文里不含"。"且不超过 30 字的行都是小标题。
    """
    return 0 < len(line) <= 30 and not any(ch in line for ch in "。，；：？！,;:?!")


def paragraphs(material: Material) -> list[str]:
    """所有非空行，每行一个段落（源文件里一个段落就是一整行）。PDF 的分页标记不算段落。"""
    return [ln for ln in material.body_lines if ln.strip() and ln.strip() != PAGE_MARK]


def split_pages(material: Material) -> tuple[list[list[str]], list[int]]:
    """把 PDF 正文按 【分页】 拆成页。返回 (每页的段落列表, 段落中间分页的页序号列表)。

    页序号从 0 开始，表示"该页末尾的段落被拆到了下一页"。
    """
    lines = material.body_lines
    pages: list[list[str]] = [[]]
    mid_breaks: list[int] = []
    for i, line in enumerate(lines):
        if line.strip() == PAGE_MARK:
            before = lines[i - 1].strip() if i > 0 else ""
            after = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if before and after and before != PAGE_MARK and after != PAGE_MARK:
                mid_breaks.append(len(pages) - 1)
            pages.append([])
        elif line.strip():
            pages[-1].append(line)
    if any(not page for page in pages):
        raise BuildError(f"{material.id} 有空白页（相邻的 {PAGE_MARK} 或首尾多余）")
    return pages, mid_breaks


def expected_units(material: Material) -> list[tuple[int, str]]:
    """按后端规则，从源文本推出每个位置单元应有的文字（未去空白）。"""
    if material.format == "pdf":
        pages, _ = split_pages(material)
        return [(n, "".join(page)) for n, page in enumerate(pages, start=1)]
    if material.format == "docx":
        return list(enumerate(paragraphs(material), start=1))
    return [(n, ln) for n, ln in enumerate(material.body_lines, start=1) if ln.strip()]


def physical_unit_count(material: Material) -> int:
    """位置单元的最大编号：PDF 页数、DOCX 段落数、TXT 物理行数。"""
    if material.format == "pdf":
        return len(split_pages(material)[0])
    if material.format == "docx":
        return len(paragraphs(material))
    return len(material.body_lines)


# ---------------------------------------------------------------- 生成文件


def build_txt(material: Material) -> bytes:
    return ("\n".join(material.body_lines) + "\n").encode("utf-8")


def build_docx(material: Material) -> bytes:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt

    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(25)
    section.top_margin = section.bottom_margin = Mm(22)

    def set_fonts(rfonts) -> None:
        for attr in list(rfonts.attrib):
            del rfonts.attrib[attr]  # 去掉 asciiTheme 等主题字体属性，避免覆盖显式字体
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rfonts.set(qn(attr), DOCX_FONT)

    styles = doc.styles
    for rfonts in styles.element.xpath("w:docDefaults/w:rPrDefault/w:rPr/w:rFonts"):
        set_fonts(rfonts)
    normal = styles["Normal"]
    normal.font.name = DOCX_FONT
    normal.font.size = Pt(11)
    set_fonts(normal.element.get_or_add_rPr().get_or_add_rFonts())

    for text in paragraphs(material):
        para = doc.add_paragraph()
        run = para.add_run(text)
        run.font.name = DOCX_FONT
        set_fonts(run._element.get_or_add_rPr().get_or_add_rFonts())
        fmt = para.paragraph_format
        fmt.space_after = Pt(8)
        fmt.line_spacing = 1.5
        if is_heading(text):
            run.bold = True
            fmt.space_before = Pt(10)
            fmt.keep_with_next = True

    props = doc.core_properties
    props.title = material.title
    props.author = DOC_AUTHOR
    props.last_modified_by = DOC_AUTHOR
    props.subject = f"{material.course} {material.type}"
    props.comments = DOC_COMMENT
    props.language = "zh-CN"
    props.created = props.modified = FIXED_TIME
    props.revision = 1

    buffer = io.BytesIO()
    doc.save(buffer)
    return _normalize_zip(buffer.getvalue())


def _normalize_zip(data: bytes) -> bytes:
    """统一 zip 内各条目的时间戳，使 DOCX 重复生成时逐字节一致。"""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            new = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            new.compress_type = zipfile.ZIP_DEFLATED
            new.external_attr = info.external_attr
            dst.writestr(new, src.read(info.filename))
    return out.getvalue()


_FONTS_READY = False
PDF_LAYOUT: dict[str, tuple[float, int]] = {}  # 资料编号 -> (正文字号 pt, 页边距 mm)，仅用于汇报


def _register_fonts():
    """注册 PDF 用字体并返回 (正文字体, 标题字体)。"""
    global _FONTS_READY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for path in (FONT_BODY_FILE, FONT_HEADING_FILE):
        if not path.exists():
            raise BuildError(f"找不到字体文件 {path}")
    if not _FONTS_READY:
        pdfmetrics.registerFont(TTFont("SimSun", str(FONT_BODY_FILE), subfontIndex=0))
        pdfmetrics.registerFont(TTFont("MSYH-Bold", str(FONT_HEADING_FILE), subfontIndex=0))
        _FONTS_READY = True
    return pdfmetrics.getFont("SimSun"), pdfmetrics.getFont("MSYH-Bold")


def _uncovered(font, text: str) -> set[str]:
    cmap = font.face.charToGlyph
    return {ch for ch in text if not ch.isspace() and ord(ch) not in cmap}


def build_pdf(material: Material) -> bytes:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph

    body_font, heading_font = _register_fonts()
    pages, _ = split_pages(material)

    gaps = _uncovered(body_font, "".join(ln for page in pages for ln in page))
    if gaps:
        raise BuildError(f"{material.id}：宋体缺少字形 {sorted(gaps)}")

    def make_story(size: float) -> list:
        body_style = ParagraphStyle(
            "body", fontName="SimSun", fontSize=size, leading=size * 1.7,
            wordWrap="CJK", alignment=TA_LEFT, spaceAfter=size * 0.8,
        )
        head_style = ParagraphStyle(
            "heading", parent=body_style, fontName="MSYH-Bold", spaceBefore=size * 0.4,
        )
        story: list = []
        for n, page in enumerate(pages):
            if n:
                story.append(PageBreak())
            for text in page:
                if is_heading(text) and not _uncovered(heading_font, text):
                    story.append(Paragraph(escape(text), head_style))
                else:
                    story.append(Paragraph(escape(text), body_style))
        return story

    def fits(size: float, margin: float) -> bool:
        width, height = A4[0] - 2 * margin, A4[1] - 2 * margin
        flows = [f for f in make_story(size) if isinstance(f, Paragraph)]
        start = 0
        for page in pages:
            used = 0.0
            for flow in flows[start : start + len(page)]:
                _, h = flow.wrap(width, height * 10)
                used += h + flow.style.spaceBefore + flow.style.spaceAfter
            start += len(page)
            if used > height - 6:  # 留 6pt 余量，避免最后一段因舍入溢出到下一页
                return False
        return True

    chosen = None
    for margin_mm in PDF_MARGINS_MM:
        for size in PDF_FONT_SIZES:
            if fits(size, margin_mm * mm):
                chosen = (size, margin_mm * mm)
                break
        if chosen:
            break
    if chosen is None:
        raise BuildError(f"{material.id}：某页内容在最小字号和最小页边距下仍放不进一页")
    size, margin = chosen
    PDF_LAYOUT[material.id] = (size, round(margin / mm))

    buffer = io.BytesIO()
    frame = Frame(
        margin, margin, A4[0] - 2 * margin, A4[1] - 2 * margin,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="body",
    )
    doc = BaseDocTemplate(
        buffer, pagesize=A4, title=material.title, author=DOC_AUTHOR,
        subject=f"{material.course} {material.type}", creator=GENERATED_BY,
        keywords=DOC_COMMENT, invariant=1, pageTemplates=[PageTemplate(id="main", frames=[frame])],
    )
    doc.build(make_story(size))
    return buffer.getvalue()


BUILDERS = {"pdf": build_pdf, "docx": build_docx, "txt": build_txt}


def build_bytes(material: Material) -> bytes:
    return BUILDERS[material.format](material)


# ---------------------------------------------------------------- 定位与校验


def load_backend():
    """导入后端的解析函数和上传校验函数（只读 import，不读 .env）。"""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from app.config import Settings
    from app.index_documents import extract_units
    from app.uploads import validate_content

    return extract_units, validate_content, Settings.model_construct()


def locate_fact(units: list[tuple[int, str]], fact_text: str) -> dict | None:
    """在位置单元里查找原句（去空白比较）。

    返回 {"start","end","occurrences","spans"}；找不到返回 None。
    优先选完全落在单个单元内的第一处命中；没有才选跨单元的命中。
    """
    target = squash(fact_text)
    if not target:
        return None
    parts = [squash(text) for _, text in units]
    starts: list[int] = []
    offset = 0
    for part in parts:
        starts.append(offset)
        offset += len(part)
    joined = "".join(parts)

    hits: list[tuple[int, int]] = []  # (首单元下标, 末单元下标)
    at = joined.find(target)
    while at != -1:
        first = bisect_right(starts, at) - 1
        last = bisect_right(starts, at + len(target) - 1) - 1
        hits.append((first, last))
        at = joined.find(target, at + 1)
    if not hits:
        return None
    singles = [h for h in hits if h[0] == h[1]]
    first, last = singles[0] if singles else hits[0]
    return {
        "start": units[first][0],
        "end": units[last][0],
        "occurrences": len(hits),
        "spans": first != last,
    }


def cross_page_facts(material: Material, located: dict[int, dict]) -> list[dict]:
    """针对"段落中间分页"的位置，独立从源文本推出每条相关事实应在的页，并与定位结果对照。"""
    if material.format != "pdf":
        return []
    pages, mid_breaks = split_pages(material)
    results = []
    for page_index in mid_breaks:
        first_half = pages[page_index][-1]
        second_half = pages[page_index + 1][0]
        whole = squash(first_half + second_half)
        cut = len(squash(first_half))
        for fact in material.facts:
            target = squash(fact.text)
            at = whole.find(target)
            if at == -1:
                continue
            end = at + len(target)
            if end <= cut:
                expect = (page_index + 1, page_index + 1)
            elif at >= cut:
                expect = (page_index + 2, page_index + 2)
            else:
                expect = (page_index + 1, page_index + 2)
            got = located.get(fact.no)
            actual = (got["start"], got["end"]) if got else None
            results.append(
                {"doc_id": material.id, "fact_no": fact.no, "break_after_page": page_index + 1,
                 "expected": expect, "actual": actual, "ok": actual == expect, "text": fact.text}
            )
    return results


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


# ---------------------------------------------------------------- 主流程


def run(source: Path, out_dir: Path) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        # 重定向到管道/文件时 Windows 默认按 GBK 输出，统一成 UTF-8；直接在控制台运行时不改
        sys.stdout.reconfigure(errors="replace", **({} if sys.stdout.isatty() else {"encoding": "utf-8"}))
        sys.stderr.reconfigure(errors="replace", **({} if sys.stderr.isatty() else {"encoding": "utf-8"}))
    tables, materials = parse_source(source.read_text(encoding="utf-8-sig"))
    print(f"源文件解析完成：事实表 {len(tables)} 个，资料 {len(materials)} 份。")

    problems: list[str] = []
    warnings: list[str] = []
    written = 0
    for m in materials:
        if write_if_changed(out_dir / m.relative_path, build_bytes(m)):
            written += 1
    print(f"已写入 {written} 个文件，{len(materials) - written} 个与现有内容一致而跳过。")
    for doc_id, (size, margin_mm) in PDF_LAYOUT.items():
        print(f"  PDF 版式 {doc_id}: 正文 {size} pt，页边距 {margin_mm} mm")

    extract_units, validate_content, settings = load_backend()
    manifest = []
    key_fact_records = []
    missing: list[tuple[str, int, str, str]] = []
    cross_reports: list[dict] = []
    page_chars: dict[str, list[int]] = {}
    rows = []

    for m in materials:
        path = out_dir / m.relative_path
        data = path.read_bytes()
        try:
            mime = validate_content(path, path.name)
        except Exception as exc:  # AppError 等
            problems.append(f"{m.id} 上传校验未通过：{exc}")
            continue
        if mime != MIME_BY_FORMAT[m.format]:
            problems.append(f"{m.id} 校验返回 {mime}，与格式 {m.format} 不匹配")
        location_type, units = extract_units(path, mime, settings)
        if location_type != LOCATOR_TYPE_BY_FORMAT[m.format]:
            problems.append(f"{m.id} 位置类型 {location_type} 与预期 {LOCATOR_TYPE_BY_FORMAT[m.format]} 不符")

        # 逐单元对照源文本，保证"不增不删不改"，且编号与预期一致
        want = [(n, squash(t)) for n, t in expected_units(m)]
        got = [(n, squash(t)) for n, t in units]
        if want != got:
            bad = next((w[0] for w, g in zip(want, got) if w != g), min(len(want), len(got)) + 1)
            problems.append(f"{m.id} 提取文字与源文本不一致（单元数 预期 {len(want)} 实际 {len(got)}，首个差异在单元 {bad}）")

        counts = _physical_count(path, m.format)
        if counts != physical_unit_count(m):
            problems.append(f"{m.id} 单元数 {counts} 与预期 {physical_unit_count(m)} 不符")
        if m.format == "pdf":
            page_chars[m.id] = [len(squash(t)) for _, t in units]
        _check_metadata(m, path, problems)

        located: dict[int, dict] = {}
        for fact in m.facts:
            hit = locate_fact(units, fact.text)
            if hit is None:
                reason = _missing_reason(m, units, fact.text)
                missing.append((m.id, fact.no, fact.text, reason))
                continue
            located[fact.no] = hit
            if hit["occurrences"] > 1:
                warnings.append(f"{m.id} #{fact.no} 原句在文件中出现 {hit['occurrences']} 次，已取第一处")
            if hit["spans"] and m.format != "pdf":
                warnings.append(f"{m.id} #{fact.no} 原句跨多个单元（{hit['start']}-{hit['end']}），请人工确认")
            key_fact_records.append(
                {"doc_id": m.id, "fact_no": fact.no, "text": fact.text,
                 "locator": {"type": location_type, "start": hit["start"], "end": hit["end"]}}
            )
        cross_reports.extend(cross_page_facts(m, located))

        char_count = sum(len(squash(t)) for _, t in units)
        manifest.append(
            {
                "id": m.id, "course": m.course, "type": m.type, "title": m.title,
                "format": m.format, "version": m.version, "relative_path": m.relative_path,
                "size_bytes": len(data), "sha256": sha256_of(data),
                "page_or_unit_count": counts, "char_count": char_count,
                "key_fact_count": len(m.facts),
                "source": SOURCE_NOTE, "license": LICENSE_NOTE, "generated_by_script": GENERATED_BY,
            }
        )
        found = len(located)
        rows.append((m.relative_path, len(data), counts, char_count, f"{found}/{len(m.facts)}"))

    write_if_changed(
        out_dir / "key_facts.jsonl",
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in key_fact_records).encode("utf-8"),
    )
    write_if_changed(
        out_dir / "manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )

    total = sum(len(m.facts) for m in materials)
    print("\n文件摘要（相对路径 | 字节 | 页/段/行数 | 字数(不含空白) | 事实 找到/总数）")
    for row in rows:
        print("  " + " | ".join(str(c) for c in row))
    print(f"\nkey_facts：共 {total} 条，找到 {len(key_fact_records)} 条，找不到 {len(missing)} 条。")
    for doc_id, no, text, reason in missing:
        print(f"  找不到 {doc_id} #{no}：{text}\n    原因：{reason}")
    print("\nPDF 每页字数（去空白）：")
    for doc_id, counts in page_chars.items():
        print(f"  {doc_id}: {counts}")
    print("\n段落中间分页处的关键事实定位：")
    for r in cross_reports:
        print(f"  {r['doc_id']} #{r['fact_no']} 分页在第 {r['break_after_page']} 页后 预期 {r['expected']} 实际 {r['actual']} "
              f"{'一致' if r['ok'] else '不一致'}")
        if not r["ok"]:
            problems.append(f"{r['doc_id']} #{r['fact_no']} 跨页定位 预期 {r['expected']} 实际 {r['actual']}")
    for w in warnings:
        print(f"警告：{w}")
    problems.extend(f"关键事实找不到：{d} #{n}" for d, n, _, _ in missing)
    if problems:
        print("\n存在问题：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n全部校验通过。")
    return 0


def _physical_count(path: Path, fmt: str) -> int:
    if fmt == "pdf":
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    if fmt == "docx":
        from docx import Document

        return len(Document(str(path)).paragraphs)
    return len(path.read_bytes().decode("utf-8").splitlines())


def _check_metadata(m: Material, path: Path, problems: list[str]) -> None:
    title = None
    if m.format == "pdf":
        from pypdf import PdfReader

        info = PdfReader(str(path)).metadata
        title = info.title if info else None
    elif m.format == "docx":
        from docx import Document

        title = Document(str(path)).core_properties.title
    else:
        return
    if title != m.title:
        problems.append(f"{m.id} 元数据标题 {title!r} 与源文件标题不一致")


def _missing_reason(m: Material, units: list[tuple[int, str]], fact_text: str) -> str:
    """给出"找不到"的可能原因，便于人工判断是源文件问题还是转换问题。"""
    target = squash(fact_text)
    in_source = target in squash("".join(m.body_lines).replace(PAGE_MARK, ""))
    in_source_with_mark = target in squash("".join(m.body_lines))
    if not in_source and not in_source_with_mark:
        # 找最长公共前缀，提示原句偏离正文的位置
        body = squash("".join(m.body_lines).replace(PAGE_MARK, ""))
        for cut in range(len(target), 0, -1):
            if target[:cut] in body:
                return f"源文件正文里也没有这句原文；前 {cut} 个字符能对上，第 {cut + 1} 个字符起不一致：{target[cut:cut + 12]!r}"
        return "源文件正文里也没有这句原文（关键事实与正文对不上）"
    if in_source and not any(target in squash(t) for _, t in units):
        return "源文件正文有这句，但生成文件提取的文字里没有（转换或提取问题）"
    return "未知原因"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="资料文本路径")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT, help="输出目录")
    args = parser.parse_args(argv)
    try:
        return run(args.source, args.out_dir)
    except BuildError as exc:
        print(f"生成失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
