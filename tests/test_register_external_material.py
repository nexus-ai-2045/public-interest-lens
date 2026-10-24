import json
import tempfile
import unittest
from pathlib import Path

from scripts.register_external_material import (
    register_local_material,
    register_once,
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

    def test_symlinked_task_dir_does_not_receive_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "report.pdf"
            source.write_bytes(b"%PDF-test")
            storage = root / "storage"
            storage.mkdir()
            outside = root / "outside"
            outside.mkdir()
            task_dir = storage / "policy-review-001"
            task_dir.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "registration escaped storage root"):
                register_local_material(
                    input_path=source,
                    source_url="https://example.go.jp/report.pdf",
                    task_id="policy-review-001",
                    title="規制改革資料",
                    purpose="根拠確認",
                    storage_root=storage,
                    observed_at="2026-07-31T10:00:00+09:00",
                )
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(source.read_bytes(), b"%PDF-test")
            self.assertTrue(task_dir.is_symlink())



class RegisterOnceTests(unittest.TestCase):
    def test_same_body_from_two_urls_keeps_each_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "404.json"
            body.write_text("{}", encoding="utf-8")
            storage = Path(tmp) / "materials"
            args = dict(input_path=body, task_id="t", title="x", purpose="y", storage_root=storage)
            a = register_once(source_url="https://example.go.jp/a", **args)
            b = register_once(source_url="https://example.go.jp/b", **args)
            self.assertNotEqual(a, b)
            self.assertEqual(register_once(source_url="https://example.go.jp/a", **args), a)  # 同じ URL は登録し直さない
            sources = {r.parent.name: json.loads(r.read_text(encoding="utf-8"))["source_url"]
                       for r in (storage / "t").glob("*/record.json")}
            self.assertEqual(sources, {a: "https://example.go.jp/a", b: "https://example.go.jp/b"})
    def test_observed_at_is_the_fetch_time_or_the_copy_mtime(self) -> None:
        import os
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "a.json"
            body.write_text("{}", encoding="utf-8")
            os.utime(body, (1_600_000_000, 1_600_000_000))
            storage = Path(tmp) / "materials"
            args = dict(input_path=body, task_id="t", title="x", purpose="y", storage_root=storage)
            a = register_once(source_url="https://example.go.jp/a", observed_at="2026-10-18T01:02:03Z", **args)
            b = register_once(source_url="https://example.go.jp/b", **args)
            ra = json.loads((storage / "t" / a / "record.json").read_text(encoding="utf-8"))
            rb = json.loads((storage / "t" / b / "record.json").read_text(encoding="utf-8"))
            self.assertEqual((ra["observed_at"], ra["observed_at_basis"]), ("2026-10-18T01:02:03+00:00", "fetched_at"))
            self.assertTrue(rb["observed_at_basis"].startswith("file_mtime"))
            self.assertTrue(rb["observed_at"].startswith("2020-09-1"))  # 登録した日ではなく控えの更新時刻
            self.assertTrue(b.startswith("2020-09-1"))


if __name__ == "__main__":
    unittest.main()
