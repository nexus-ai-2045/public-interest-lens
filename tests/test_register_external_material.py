import json
import tempfile
import unittest
from pathlib import Path

from scripts.register_external_material import (
    register_local_material,
    validate_source_url,
)


class ValidateSourceUrlTests(unittest.TestCase):
    def test_accepts_public_https_url(self) -> None:
        self.assertEqual(
            validate_source_url("https://example.go.jp/report.pdf"),
            "https://example.go.jp/report.pdf",
        )

    def test_rejects_local_or_non_http_url(self) -> None:
        for url in (
            "file:///C:/secret.txt",
            "http://localhost/admin",
            "http://127.0.0.1/private",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_source_url(url)


class RegisterLocalMaterialTests(unittest.TestCase):
    def test_copies_material_and_writes_provenance_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "report.pdf"
            source.write_bytes(b"%PDF-test")

            record_path = register_local_material(
                input_path=source,
                source_url="https://example.go.jp/report.pdf",
                task_id="policy-review-001",
                title="規制改革資料",
                purpose="根拠確認",
                storage_root=root / "storage",
                observed_at="2026-07-31T10:00:00+09:00",
            )

            record = json.loads(record_path.read_text(encoding="utf-8"))
            saved_file = record_path.parent / record["saved_filename"]

            self.assertTrue(saved_file.exists())
            self.assertEqual(saved_file.read_bytes(), b"%PDF-test")
            self.assertEqual(record["schema_version"], "external-material/v1")
            self.assertEqual(record["task_id"], "policy-review-001")
            self.assertEqual(record["source_url"], "https://example.go.jp/report.pdf")
            self.assertEqual(record["content_verification"], "unverified")
            self.assertEqual(record["sha256"], "3c87d37f1dbea6909f917ce437c390fb8e655a774387d9e69301c0b2283d5b63")

    def test_rejects_unsafe_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.pdf"
            source.write_bytes(b"x")

            with self.assertRaises(ValueError):
                register_local_material(
                    input_path=source,
                    source_url="https://example.go.jp/report.pdf",
                    task_id="../escape",
                    title="資料",
                    purpose="確認",
                    storage_root=Path(temp) / "storage",
                )

    def test_rejects_unsafe_or_timezone_free_observed_at(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.pdf"
            source.write_bytes(b"x")

            for observed_at in ("../../escape", "2026-07-31T10:00:00"):
                with self.subTest(observed_at=observed_at), self.assertRaises(ValueError):
                    register_local_material(
                        input_path=source,
                        source_url="https://example.go.jp/report.pdf",
                        task_id="task-001",
                        title="資料",
                        purpose="確認",
                        storage_root=Path(temp) / "storage",
                        observed_at=observed_at,
                    )

    def test_dry_run_plans_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "report.pdf"
            source.write_bytes(b"dry-run")
            storage = root / "storage"

            record_path = register_local_material(
                input_path=source,
                source_url="https://example.go.jp/report.pdf",
                task_id="task-001",
                title="資料",
                purpose="確認",
                storage_root=storage,
                observed_at="2026-07-31T10:00:00+09:00",
                dry_run=True,
            )

            self.assertFalse(record_path.exists())
            self.assertFalse(storage.exists())


if __name__ == "__main__":
    unittest.main()
