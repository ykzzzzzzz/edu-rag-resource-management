"""实验资料导入的清单校验和可重跑行为。"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import import_experiment_materials as importer


class ExperimentImportTests(unittest.TestCase):
    data = b"sample evidence"

    def setUp(self):
        self.material = importer.Material(
            "DB-01", "Database", "Example", "sample.txt", "text/plain", hashlib.sha256(self.data).hexdigest(), self.data
        )

    def test_manifest_verifies_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / self.material.filename
            sample.write_bytes(self.data)
            manifest = root / "manifest.json"
            entry = {
                "id": self.material.id,
                "title": self.material.title,
                "course": self.material.course,
                "relative_path": self.material.filename,
                "format": "txt",
                "sha256": self.material.sha256,
                "size_bytes": len(self.data),
            }
            manifest.write_text(json.dumps([entry]), encoding="utf-8")
            self.assertEqual(importer.load_materials(manifest), [self.material])
            sample.write_bytes(b"x" * len(self.data))
            with self.assertRaisesRegex(importer.ImportFailure, "SHA-256"):
                importer.load_materials(manifest)

    def _clients(self, initial_status=None, existing_data=None, description=None):
        material = self.material
        resource = {
            "id": "resource-id",
            "course_id": "course-id",
            "title": material.title,
            "original_filename": material.filename,
            "size_bytes": len(material.data),
            "owner_id": "teacher-id",
            "description": material.description if description is None else description,
            "review_status": initial_status,
        }
        mutations = []

        def handle(request):
            labels = {
                "/api/v1/resources": ("upload", "teacher", "draft", 201),
                "/api/v1/resources/resource-id/submit": ("submit", "teacher", "pending", 200),
                "/api/v1/admin/resources/resource-id/review": ("review", "admin", "published", 200),
            }
            path = request.url.path
            if request.method == "POST":
                mutation, role, status, code = labels[path]
                self.assertEqual(request.headers["x-test-role"], role)
                if mutation == "upload":
                    self.assertIn(material.data, request.content)
                mutations.append(mutation)
                resource["review_status"] = status
                return httpx.Response(code, json=resource)
            if path == "/api/v1/courses":
                return httpx.Response(200, json={"items": [{"id": "course-id", "name": material.course}]})
            if path == "/api/v1/admin/resources":
                items = [resource] if resource["review_status"] else []
                return httpx.Response(200, json={"items": items, "total": len(items)})
            if path == "/api/v1/resources/resource-id/download":
                return httpx.Response(200, content=material.data if existing_data is None else existing_data)
            raise AssertionError(f"Unexpected request {request.method} {path}")

        transport = httpx.MockTransport(handle)
        teacher = httpx.Client(transport=transport, base_url="http://localhost", headers={"x-test-role": "teacher"})
        admin = httpx.Client(transport=transport, base_url="http://localhost", headers={"x-test-role": "admin"})
        self.addCleanup(teacher.close)
        self.addCleanup(admin.close)
        return teacher, admin, mutations

    def test_new_upload_and_repeat_uses_same_resource(self):
        teacher, admin, mutations = self._clients()
        for _ in range(2):
            self.assertEqual(importer.import_materials(teacher, admin, [self.material], "teacher-id"), {
                "DB-01": "resource-id",
            })
        self.assertEqual(mutations, ["upload", "submit", "review"])

    def test_resume_draft_and_pending(self):
        for status, expected in (("draft", ["submit", "review"]), ("pending", ["review"])):
            with self.subTest(status=status):
                teacher, admin, mutations = self._clients(initial_status=status)
                importer.import_materials(teacher, admin, [self.material], "teacher-id")
                self.assertEqual(mutations, expected)

    def test_target_resource_conflict_aborts_before_mutation(self):
        teacher, admin, mutations = self._clients(initial_status="published", existing_data=b"different")
        with self.assertRaisesRegex(importer.ImportFailure, "SHA-256"):
            importer.import_materials(teacher, admin, [self.material], "teacher-id")
        self.assertEqual(mutations, [])

    def test_unrelated_resource_aborts_before_mutation(self):
        teacher, admin, mutations = self._clients(initial_status="published", description="Not an experiment resource")
        with self.assertRaisesRegex(importer.ImportFailure, "独立实验库"):
            importer.import_materials(teacher, admin, [self.material], "teacher-id")
        self.assertEqual(mutations, [])
