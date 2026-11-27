"""build_materials.py 的单元测试。只使用标准库和已安装的 pypdf / python-docx / reportlab，
不联网、不读 .env、不连数据库。

运行：
  E:\\scf-env\\venv\\Scripts\\python.exe -I -m unittest discover -s D:\\codex\\scf\\scripts\\tests -v

涉及"已生成文件"的测试需要先运行 scripts/build_materials.py；文件不存在时这些测试会被跳过。
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
import zipfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import build_materials as bm  # noqa: E402

MATERIALS_DIR = bm.DEFAULT_OUT
SOURCE = bm.DEFAULT_SOURCE

SAMPLE = """=== 事实表开始 ===
课程：数据库原理
1. 总评：平时 20%。
=== 事实表结束 ===

=== 资料开始 ===
编号：DB-02
课程：数据库原理
类型：讲义 第 1 部分
标题：示例标题
格式：pdf
版本：v1
--- 正文 ---
一、第一节

甲乙丙。丁戊己。

【分页】

庚辛壬癸，子丑寅卯，
【分页】
辰巳午未。

申酉戌亥。
--- 关键事实 ---
1. 「丁戊己。」
2. 「子丑寅卯，辰巳午未。」
=== 资料结束 ===

本批完成：DB-02。
"""


def load_sample_materials() -> list[bm.Material]:
    """把 SAMPLE 里的资料块单独解析出来（绕过"必须 24 份"的整体校验）。"""
    start = SAMPLE.index("=== 资料开始 ===")
    block = SAMPLE[start:].split("=== 资料结束 ===")[0].split("\n")[1:]
    return [bm._parse_material(block, 1)]


class ParseTests(unittest.TestCase):
    def test_header_body_and_facts(self):
        (m,) = load_sample_materials()
        self.assertEqual((m.id, m.course, m.type, m.format, m.version), ("DB-02", "数据库原理", "讲义 第 1 部分", "pdf", "v1"))
        self.assertEqual(m.title, "示例标题")
        self.assertEqual(m.filename, "DB-02-讲义第1部分.pdf")
        self.assertEqual(m.relative_path, "DB/DB-02-讲义第1部分.pdf")
        self.assertEqual([f.no for f in m.facts], [1, 2])
        self.assertEqual(m.facts[1].text, "子丑寅卯，辰巳午未。")
        self.assertEqual(m.body_lines[0], "一、第一节")
        self.assertEqual(m.body_lines[-1], "申酉戌亥。")

    def test_pages_and_mid_paragraph_break(self):
        (m,) = load_sample_materials()
        pages, mid = bm.split_pages(m)
        self.assertEqual(len(pages), 3)
        self.assertEqual(pages[0], ["一、第一节", "甲乙丙。丁戊己。"])
        self.assertEqual(pages[1], ["庚辛壬癸，子丑寅卯，"])
        self.assertEqual(pages[2], ["辰巳午未。", "申酉戌亥。"])
        self.assertEqual(mid, [1])  # 第 2 页末尾的段落被拆到第 3 页（第 0 页后的分页前后有空行，不算）

    def test_mid_break_not_flagged_for_blank_separated_pages(self):
        (m,) = load_sample_materials()
        _, mid = bm.split_pages(m)
        self.assertNotIn(0, mid)

    def test_text_outside_blocks_is_ignored_and_counts_are_checked(self):
        with self.assertRaises(bm.BuildError):
            bm.parse_source(SAMPLE)  # 只有 1 个事实表、1 份资料

    def test_missing_end_marker_is_reported(self):
        broken = SAMPLE.replace("=== 资料结束 ===", "")
        with self.assertRaises(bm.BuildError):
            bm.parse_source(broken)

    def test_bad_fact_line_is_reported(self):
        block = ["编号：DB-02", "课程：数据库原理", "类型：讲义", "标题：t", "格式：pdf", "版本：v1",
                 "--- 正文 ---", "正文。", "--- 关键事实 ---", "1. 没有引号"]
        with self.assertRaises(bm.BuildError):
            bm._parse_material(block, 1)

    def test_heading_rule(self):
        self.assertTrue(bm.is_heading("一、课程目标与教学安排"))
        self.assertTrue(bm.is_heading("十二、其他"))
        self.assertTrue(bm.is_heading("实验一 器材登记"))  # 个别资料的小标题没有序号
        self.assertFalse(bm.is_heading("一、这是一句带句号的话。"))
        self.assertFalse(bm.is_heading("一、" + "字" * 40))
        self.assertFalse(bm.is_heading("这是一个很短的句子，但带逗号"))
        self.assertFalse(bm.is_heading(""))

    def test_squash_removes_all_whitespace(self):
        self.assertEqual(bm.squash(" a\tb\nc\u3000d "), "abcd")


class LocateTests(unittest.TestCase):
    UNITS = [(1, "甲乙丙丁"), (2, "戊己 庚辛"), (3, "壬癸子丑")]

    def test_inside_one_unit(self):
        hit = bm.locate_fact(self.UNITS, "戊己庚辛")
        self.assertEqual((hit["start"], hit["end"]), (2, 2))

    def test_across_adjacent_units(self):
        hit = bm.locate_fact(self.UNITS, "丙丁戊己")
        self.assertEqual((hit["start"], hit["end"]), (1, 2))
        self.assertTrue(hit["spans"])

    def test_missing_returns_none(self):
        self.assertIsNone(bm.locate_fact(self.UNITS, "不存在的句子"))
        self.assertIsNone(bm.locate_fact(self.UNITS, "   "))

    def test_prefers_single_unit_hit_over_spanning_hit(self):
        units = [(1, "甲乙"), (2, "丙甲乙丙")]
        hit = bm.locate_fact(units, "甲乙")
        self.assertEqual((hit["start"], hit["end"]), (1, 1))
        self.assertEqual(hit["occurrences"], 2)


class SourceFileTests(unittest.TestCase):
    """针对 evaluation/course-materials.txt 本身的结构检查（只读）。"""

    @classmethod
    def setUpClass(cls):
        if not SOURCE.exists():
            raise unittest.SkipTest(f"源文件不存在：{SOURCE}")
        cls.tables, cls.materials = bm.parse_source(SOURCE.read_text(encoding="utf-8-sig"))

    def test_counts(self):
        self.assertEqual(len(self.tables), 3)
        self.assertEqual(len(self.materials), 24)
        for prefix in bm.COURSE_PREFIXES:
            ids = [m.id for m in self.materials if m.prefix == prefix]
            self.assertEqual(ids, [f"{prefix}-{n:02d}" for n in range(1, 9)])

    def test_formats_follow_the_brief(self):
        expected = {1: "docx", 2: "pdf", 3: "pdf", 4: "pdf", 5: "docx", 6: "txt", 7: "txt", 8: "docx"}
        for m in self.materials:
            self.assertEqual(m.format, expected[int(m.id.split("-")[1])], m.id)

    def test_each_pdf_has_three_pages_and_at_most_one_mid_break(self):
        for m in self.materials:
            if m.format != "pdf":
                continue
            pages, mid = bm.split_pages(m)
            self.assertEqual(len(pages), 3, m.id)
            self.assertLessEqual(len(mid), 1, m.id)

    def test_the_three_known_mid_paragraph_breaks(self):
        found = {m.id: bm.split_pages(m)[1] for m in self.materials if m.format == "pdf"}
        with_break = sorted(k for k, v in found.items() if v)
        self.assertEqual(with_break, ["DB-04", "NET-04", "PY-04"])
        for doc_id in with_break:
            self.assertEqual(found[doc_id], [1], doc_id)  # 都在第 2 页和第 3 页之间

    def test_non_pdf_bodies_have_no_page_marker(self):
        for m in self.materials:
            if m.format != "pdf":
                self.assertFalse(any(bm.PAGE_MARK in ln for ln in m.body_lines), m.id)

    def test_every_material_has_enough_facts(self):
        for m in self.materials:
            self.assertGreaterEqual(len(m.facts), 8, m.id)


class GeneratedFilesTestCase(unittest.TestCase):
    """依赖已生成文件的测试基类：文件不存在时跳过。"""

    @classmethod
    def setUpClass(cls):
        if not SOURCE.exists():
            raise unittest.SkipTest(f"源文件不存在：{SOURCE}")
        cls.materials = bm.parse_source(SOURCE.read_text(encoding="utf-8-sig"))[1]
        missing = [m.relative_path for m in cls.materials if not (MATERIALS_DIR / m.relative_path).exists()]
        if missing:
            raise unittest.SkipTest(
                f"尚未生成样例资料（缺 {len(missing)} 个），请先运行 scripts/build_materials.py"
            )
        extract_units, validate_content, cls.settings = bm.load_backend()
        cls.extract_units = staticmethod(extract_units)  # 避免被当成绑定方法
        cls.validate_content = staticmethod(validate_content)

    def of_format(self, fmt):
        return [m for m in self.materials if m.format == fmt]

    def units(self, m):
        path = MATERIALS_DIR / m.relative_path
        mime = self.validate_content(path, path.name)
        return self.extract_units(path, mime, self.settings)


class PdfTests(GeneratedFilesTestCase):
    def test_pages_match_blocks_one_to_one(self):
        for m in self.of_format("pdf"):
            with self.subTest(m.id):
                location_type, units = self.units(m)
                self.assertEqual(location_type, "pdf_page")
                pages, _ = bm.split_pages(m)
                self.assertEqual([n for n, _ in units], [1, 2, 3])
                for (n, text), source_page in zip(units, pages):
                    self.assertEqual(bm.squash(text), bm.squash("".join(source_page)), f"{m.id} 第 {n} 页")

    def test_page_text_is_in_a_real_text_layer_with_chinese(self):
        for m in self.of_format("pdf"):
            _, units = self.units(m)
            for _, text in units:
                self.assertGreater(len(bm.squash(text)), 400, m.id)

    def test_title_is_metadata_only(self):
        from pypdf import PdfReader

        for m in self.of_format("pdf"):
            path = MATERIALS_DIR / m.relative_path
            self.assertEqual(PdfReader(str(path)).metadata.title, m.title, m.id)
            _, units = self.units(m)
            self.assertNotIn(bm.squash(m.title), bm.squash("".join(t for _, t in units)), m.id)

    def test_pdf_starts_and_ends_like_a_pdf(self):
        for m in self.of_format("pdf"):
            data = (MATERIALS_DIR / m.relative_path).read_bytes()
            self.assertTrue(data.startswith(b"%PDF-"), m.id)
            self.assertIn(b"%%EOF", data[-1024:], m.id)


class DocxTests(GeneratedFilesTestCase):
    def paragraphs(self, m):
        from docx import Document

        return Document(str(MATERIALS_DIR / m.relative_path)).paragraphs

    def test_no_empty_paragraphs_and_one_paragraph_per_source_paragraph(self):
        for m in self.of_format("docx"):
            with self.subTest(m.id):
                paras = self.paragraphs(m)
                self.assertTrue(all(p.text.strip() for p in paras))
                self.assertEqual([p.text for p in paras], bm.paragraphs(m))
                location_type, units = self.units(m)
                self.assertEqual(location_type, "docx_paragraph")
                self.assertEqual([n for n, _ in units], list(range(1, len(paras) + 1)))

    def test_headings_are_bold_and_others_are_not(self):
        for m in self.of_format("docx"):
            with self.subTest(m.id):
                headings = 0
                for p in self.paragraphs(m):
                    bold = all(r.bold for r in p.runs)
                    if bm.is_heading(p.text):
                        headings += 1
                        self.assertTrue(bold, p.text)
                    else:
                        self.assertFalse(any(r.bold for r in p.runs), p.text[:20])
                self.assertGreaterEqual(headings, 3)

    def test_east_asian_font_is_set(self):
        for m in self.of_format("docx"):
            path = MATERIALS_DIR / m.relative_path
            with zipfile.ZipFile(path) as zf:
                document = zf.read("word/document.xml").decode("utf-8")
                styles = zf.read("word/styles.xml").decode("utf-8")
            self.assertIn(f'w:eastAsia="{bm.DOCX_FONT}"', document, m.id)
            self.assertIn(f'w:eastAsia="{bm.DOCX_FONT}"', styles, m.id)

    def test_title_is_metadata_only(self):
        from docx import Document

        for m in self.of_format("docx"):
            doc = Document(str(MATERIALS_DIR / m.relative_path))
            self.assertEqual(doc.core_properties.title, m.title, m.id)
            self.assertNotIn(m.title, [p.text for p in doc.paragraphs], m.id)


class TxtTests(GeneratedFilesTestCase):
    def test_bytes_are_plain_utf8_with_lf(self):
        for m in self.of_format("txt"):
            data = (MATERIALS_DIR / m.relative_path).read_bytes()
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), m.id)
            self.assertNotIn(b"\r", data, m.id)
            data.decode("utf-8")

    def test_lines_correspond_to_source_lines_and_paragraphs(self):
        for m in self.of_format("txt"):
            with self.subTest(m.id):
                path = MATERIALS_DIR / m.relative_path
                lines = path.read_bytes().decode("utf-8").splitlines()
                self.assertEqual(lines, list(m.body_lines))
                # 非空行就是段落，一段一行；空行占行号
                self.assertEqual([ln for ln in lines if ln.strip()], bm.paragraphs(m))
                location_type, units = self.units(m)
                self.assertEqual(location_type, "txt_line")
                self.assertEqual([n for n, _ in units], [i for i, ln in enumerate(lines, 1) if ln.strip()])
                self.assertGreater(len(lines), len(units))  # 确实保留了空行

    def test_paragraphs_are_not_hard_wrapped(self):
        for m in self.of_format("txt"):
            lines = (MATERIALS_DIR / m.relative_path).read_bytes().decode("utf-8").splitlines()
            for prev, cur in zip(lines, lines[1:]):
                self.assertFalse(prev and cur, f"{m.id} 有相邻的两个非空行")


class KeyFactTests(GeneratedFilesTestCase):
    def test_all_key_facts_are_locatable(self):
        total = 0
        for m in self.materials:
            _, units = self.units(m)
            for fact in m.facts:
                total += 1
                self.assertIsNotNone(bm.locate_fact(units, fact.text), f"{m.id} #{fact.no}: {fact.text}")
        self.assertGreaterEqual(total, 200)

    def test_jsonl_matches_fresh_location_and_covers_every_fact(self):
        path = MATERIALS_DIR / "key_facts.jsonl"
        self.assertTrue(path.exists(), "缺少 key_facts.jsonl")
        records = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]
        by_key = {(r["doc_id"], r["fact_no"]): r for r in records}
        self.assertEqual(len(by_key), len(records), "key_facts.jsonl 有重复记录")
        self.assertEqual(len(records), sum(len(m.facts) for m in self.materials))
        for m in self.materials:
            location_type, units = self.units(m)
            for fact in m.facts:
                rec = by_key[(m.id, fact.no)]
                hit = bm.locate_fact(units, fact.text)
                self.assertEqual(rec["text"], fact.text)
                self.assertEqual(rec["locator"], {"type": location_type, "start": hit["start"], "end": hit["end"]})
                self.assertLessEqual(rec["locator"]["start"], rec["locator"]["end"])

    def test_cross_page_paragraph_facts_are_placed_correctly(self):
        reports = []
        for m in self.of_format("pdf"):
            _, units = self.units(m)
            located = {f.no: bm.locate_fact(units, f.text) for f in m.facts}
            reports.extend(bm.cross_page_facts(m, located))
        self.assertTrue(reports)
        self.assertEqual({r["doc_id"] for r in reports}, {"DB-04", "NET-04", "PY-04"})
        for r in reports:
            self.assertTrue(r["ok"], r)

    def test_no_fact_in_pdf_spans_two_pages_by_accident(self):
        # 事实表里不应出现"原句同时落在两页"的情况以外的跨单元定位；此处只确认首尾合法
        for m in self.of_format("pdf"):
            _, units = self.units(m)
            numbers = {n for n, _ in units}
            for fact in m.facts:
                hit = bm.locate_fact(units, fact.text)
                self.assertIn(hit["start"], numbers)
                self.assertIn(hit["end"], numbers)
                self.assertLessEqual(hit["end"] - hit["start"], 1, f"{m.id} #{fact.no}")


class ManifestTests(GeneratedFilesTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        path = MATERIALS_DIR / "manifest.json"
        if not path.exists():
            raise unittest.SkipTest("缺少 manifest.json，请先运行 scripts/build_materials.py")
        cls.manifest = json.loads(path.read_text(encoding="utf-8"))

    def test_one_entry_per_material_with_all_fields(self):
        self.assertEqual([e["id"] for e in self.manifest], [m.id for m in self.materials])
        required = {
            "id", "course", "type", "title", "format", "version", "relative_path", "size_bytes", "sha256",
            "page_or_unit_count", "char_count", "key_fact_count", "source", "license", "generated_by_script",
        }
        for e in self.manifest:
            self.assertEqual(set(e), required, e["id"])
            self.assertEqual(e["source"], bm.SOURCE_NOTE)
            self.assertEqual(e["license"], bm.LICENSE_NOTE)
            self.assertEqual(e["generated_by_script"], "scripts/build_materials.py")

    def test_sha256_size_and_counts_match_files(self):
        by_id = {m.id: m for m in self.materials}
        for e in self.manifest:
            m = by_id[e["id"]]
            data = (MATERIALS_DIR / e["relative_path"]).read_bytes()
            self.assertEqual(e["sha256"], hashlib.sha256(data).hexdigest(), e["id"])
            self.assertEqual(e["size_bytes"], len(data), e["id"])
            self.assertEqual(e["key_fact_count"], len(m.facts), e["id"])
            self.assertEqual(e["format"], m.format)
            self.assertEqual(e["relative_path"], m.relative_path)
            self.assertEqual(e["page_or_unit_count"], bm.physical_unit_count(m), e["id"])

    def test_upload_validation_accepts_every_file_with_matching_mime(self):
        for m in self.materials:
            path = MATERIALS_DIR / m.relative_path
            self.assertEqual(self.validate_content(path, path.name), bm.MIME_BY_FORMAT[m.format], m.id)


class RebuildTests(GeneratedFilesTestCase):
    def test_docx_and_txt_rebuild_is_byte_identical(self):
        for m in self.materials:
            if m.format in ("docx", "txt"):
                self.assertEqual(bm.build_bytes(m), (MATERIALS_DIR / m.relative_path).read_bytes(), m.id)

    def test_pdf_rebuild_is_byte_identical(self):
        m = next(m for m in self.materials if m.id == "DB-04")
        self.assertEqual(bm.build_bytes(m), (MATERIALS_DIR / m.relative_path).read_bytes())


if __name__ == "__main__":
    unittest.main()
