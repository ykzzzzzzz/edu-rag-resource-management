"""Check the frozen evaluation inputs against the actual published source files."""

import hashlib
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from app.index_documents import DOCX, PDF, TXT, extract_units


class ExperimentDatasetTest(unittest.TestCase):
    def test_course_balance_and_source_locations(self):
        directory = ROOT / "data/samples/materials"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        sources = {}
        for doc in manifest:
            path = directory / doc["relative_path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), doc["sha256"])
            mime = {"docx": DOCX, "pdf": PDF, "txt": TXT}[doc["format"]]
            kind, units = extract_units(path, mime, Settings.model_construct())
            sources[doc["id"]] = (doc["course"], kind, dict(units))

        ids, questions = set(), set()
        for split, positives, negatives in [("validation", 6, 2), ("test", 15, 5)]:
            counts = Counter()
            path = ROOT / "evaluation" / f"{split}.jsonl"
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                with self.subTest(split=split, question=row["question_id"]):
                    self.assertNotIn(row["question_id"], ids)
                    ids.add(row["question_id"])
                    question = "".join(row["question"].split())
                    self.assertTrue(question)
                    self.assertNotIn(question, questions)
                    questions.add(question)
                    self.assertIsInstance(row["answerable"], bool)
                    self.assertIn(row["knowledge_type"], {"general", "institutional"})
                    self.assertIn(row["difficulty"], {"direct", "paraphrase_multi"})
                    self.assertEqual(bool(row["gold_sources"]), row["answerable"])
                    if row["answerable"]:
                        self.assertTrue(row["gold_answer"].strip())
                    counts[row["course"], row["answerable"]] += 1
                    for source in row["gold_sources"]:
                        course, kind, units = sources[source["doc_id"]]
                        loc = source["locator"]
                        self.assertEqual(row["course"], course)
                        self.assertEqual(loc["type"], kind)
                        self.assertLessEqual(loc["start"], loc["end"])
                        self.assertIn(loc["start"], units)
                        self.assertIn(loc["end"], units)
            courses = {doc["course"] for doc in manifest}
            expected = {(course, flag): n for course in courses
                        for flag, n in [(True, positives), (False, negatives)]}
            self.assertEqual(counts, expected)
