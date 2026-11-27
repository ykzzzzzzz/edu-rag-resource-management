"""Regression checks for gold locations and thresholded retrieval metrics."""

import sys
import unittest
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.calibrate_retrieval import load_validation, measure, record_hits, selection_key
from app.qa_service import Hit


class RetrievalCalibrationTests(unittest.TestCase):
    def test_gold_matching_requires_the_same_document_and_locator_type(self):
        target = UUID(int=1)
        other = UUID(int=2)
        q = {
            "question_id": "VAL-A",
            "course": "Course",
            "answerable": True,
            "gold_sources": [{"doc_id": "A", "locator": {"type": "txt_line", "start": 4, "end": 7}}],
        }
        hits = [
            Hit(UUID(int=rank + 2), rid, rank, 0.6, "Text", locator, "Title", "Course")
            for rank, (rid, locator) in enumerate([
                (other, {"type": "txt_line", "start": 2, "end": 4}),
                (target, {"type": "docx_paragraph", "start": 2, "end": 4}),
                (target, {"type": "txt_line", "start": 2, "end": 4}),
            ], start=1)
        ]
        self.assertEqual(
            [hit["gold_match"] for hit in record_hits(q, hits, {target: "A", other: "B"})["hits"]],
            [False, False, True],
        )

    def test_gate_is_inclusive_and_counts_retrieval_misses_separately(self):
        records = [
            {"answerable": True, "hits": [
                {"rank": 1, "similarity": 0.73, "gold_match": False},
                {"rank": 2, "similarity": 0.60, "gold_match": True},
            ]},
            {"answerable": True, "hits": [{"rank": 1, "similarity": 0.59, "gold_match": True}]},
            {"answerable": False, "hits": [{"rank": 1, "similarity": 0.50, "gold_match": False}]},
        ]
        at_boundary = measure(records, 3, 0.60)
        self.assertAlmostEqual(at_boundary["hit_at_k"], 0.5)
        self.assertAlmostEqual(at_boundary["mrr"], 0.25)
        self.assertAlmostEqual(at_boundary["raw_hit_at_k"], 1.0)
        self.assertAlmostEqual(at_boundary["raw_mrr"], 0.75)
        self.assertAlmostEqual(at_boundary["false_evidence_refusal_rate"], 0.5)
        self.assertAlmostEqual(at_boundary["unanswerable_evidence_refusal_rate"], 1.0)
        above_boundary = measure(records, 3, 0.61)
        self.assertAlmostEqual(above_boundary["hit_at_k"], 0.0)
        self.assertAlmostEqual(above_boundary["false_evidence_refusal_rate"], 0.5)

    def test_ties_use_hit_then_mrr_then_smaller_k_then_lower_threshold(self):
        default = {"selection_score": 0.7, "hit_at_k": 0.5, "mrr": 0.3, "top_k": 5, "min_similarity": 0.6}
        for key, value in [("hit_at_k", 0.6), ("mrr", 0.4), ("top_k", 3), ("min_similarity", 0.55)]:
            with self.subTest(key=key):
                self.assertGreater(selection_key({**default, key: value}), selection_key(default))

    def test_rejects_questions_without_validation_id(self):
        from scripts.calibrate_retrieval import VALIDATION

        data = VALIDATION.read_bytes()
        self.assertEqual(len(load_validation(data)), 24)
        with self.assertRaises(ValueError):
            load_validation(data.replace(b"VAL-", b"TEST-", 1))


if __name__ == "__main__":
    unittest.main()
