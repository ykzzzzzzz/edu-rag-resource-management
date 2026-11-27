"""End-to-end issue and restore checks using synthetic completed runs."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import blind_sheet


class BlindSheetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.questions, self.baseline, self.rag = (self.root / f"{name}.jsonl" for name in ("test", *blind_sheet.GROUPS))
        self.output = self.root / "issue"
        self.ids = [f"TEST-{i:02}" for i in range(60)]
        self.dump(self.questions, [
            {
                "question_id": qid, "course": "课程", "question": f"问题 {qid}",
                "answerable": index < 45, "gold_answer": "答案" if index < 45 else None,
            }
            for index, qid in enumerate(self.ids)
        ])
        self.dump(self.baseline, [
            {"question_id": qid, "group": "baseline", "mode": "cloud", "status": "answered", "answer": "回答[样例][27]"}
            for qid in self.ids
        ])
        self.dump(self.rag, [
            {
                "question_id": qid, "group": "rag", "mode": "cloud",
                "status": "answered", "answer": "回答[样例][27][1]", "citation_numbers": [1],
            }
            for qid in reversed(self.ids)
        ])

    def dump(self, path, records):
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")

    def issue(self, output=None):
        blind_sheet.create(self.questions, self.baseline, self.rag, output or self.output, 12)

    def read_csv(self, name):
        with (self.output / name).open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def score(self, name, rows):
        with (self.output / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=blind_sheet.FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_issues_reproducible_anonymous_sheets_with_independent_ids(self):
        self.issue()
        repeat = self.root / "repeat"
        self.issue(repeat)
        for path in self.output.iterdir():
            self.assertEqual(path.read_bytes(), (repeat / path.name).read_bytes())
        primary, second = self.read_csv("primary.csv"), self.read_csv("second.csv")
        self.assertEqual((len(primary), len(second)), (120, 40))
        self.assertEqual(len({row["question_id"] for row in second}), 20)
        self.assertTrue({row["blind_id"] for row in primary}.isdisjoint(row["blind_id"] for row in second))
        for row in primary + second:
            self.assertEqual(tuple(row), blind_sheet.FIELDS)
            self.assertEqual(row["answer"], "回答[样例][27]")
            self.assertEqual(row["judgment"], "")

    def test_restore_aligns_independent_raters_by_question_and_group(self):
        self.issue()
        primary, second = self.read_csv("primary.csv"), self.read_csv("second.csv")
        for row in primary + second:
            row["judgment"] = "1"
        second[0].update(judgment="0", note="独立评语")
        self.score("primary.csv", list(reversed(primary)))
        self.score("second.csv", second)
        result_path = self.root / "restored.json"
        blind_sheet.restore(
            self.output / "private_mapping.json", self.output / "primary.csv", self.output / "second.csv", result_path,
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        disagreement, = result["agreement"]["disagreements"]
        self.assertEqual(disagreement["question_id"], second[0]["question_id"])
        self.assertEqual(result["agreement"]["agreed_count"], 39)
        self.assertEqual(result["agreement"]["rate"], 39 / 40)
        judgment, = (row for row in result["second"] if row["judgment"] == 0)
        self.assertEqual(judgment["note"], "独立评语")

    def test_rejects_incomplete_or_invalid_runs_before_issue(self):
        original = list(blind_sheet.read_jsonl(self.rag).values())
        invalid = [original[:-1], [*original, original[0]]]
        for changes in (
            {"mode": "demo"}, {"group": "baseline"}, {"status": "llm_unavailable"},
            {"error_code": "timeout"}, {"citation_numbers": [99]}, {"answer": ""},
        ):
            invalid.append([{**original[0], **changes}, *original[1:]])
        for rows in invalid:
            with self.subTest(row_count=len(rows), first=rows[0]):
                self.dump(self.rag, rows)
                with self.assertRaises(ValueError):
                    self.issue()
                self.assertFalse(self.output.exists())

    def test_restore_rejects_unscored_rows(self):
        self.issue()
        with self.assertRaisesRegex(ValueError, "0 或 1"):
            blind_sheet.restore(
                self.output / "private_mapping.json", self.output / "primary.csv", self.output / "second.csv",
                self.root / "restored.json",
            )


if __name__ == "__main__":
    unittest.main()
