"""限定取得から表示データへ進む際の来歴・停止線。"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_local_mvp as runner
from scripts.run_local_mvp import _fetch_with_retries, build_dataset, run_local_mvp


def save_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


class LocalMvpTests(unittest.TestCase):
    def test_legacy_relative_record_resolves_from_source_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp) / "main-checkout"
            source = self.make_source(repo_root / ".local")
            manifest_path = source / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pages"][0]["record_path"] = str(
                Path(".local") / "diet" / "external-materials" / "page-1" / "record" / "record.json")
            save_json(manifest_path, manifest)
            dataset = build_dataset(source, as_of="2026-09-24")
            self.assertEqual(dataset["held"][0]["observedAt"], "2026-09-24T12:00:00+09:00")

    def test_missing_registered_size_or_time_rejects_source(self):
        for field in ("bytes", "observed_at"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                source = self.make_source(Path(temp))
                record_path = source / "external-materials/page-1/record/record.json"
                record = json.loads(record_path.read_text(encoding="utf-8"))
                record.pop(field)
                save_json(record_path, record)
                with self.assertRaises(ValueError):
                    build_dataset(source, as_of="2026-09-24")

    def test_page_observation_must_match_registered_time(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_source(Path(temp))
            manifest_path = source / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pages"][0]["observed_at"] = "2026-09-24T13:00:00+09:00"
            save_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "observation"):
                build_dataset(source, as_of="2026-09-24")

    def test_non_object_registered_speech_writes_failure_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            record_path = source / "external-materials/page-1/record/record.json"
            record_path.write_text("[]", encoding="utf-8")
            output = root / "output"
            result = run_local_mvp(source, output, as_of="2026-09-24")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error_type"], "ValueError")
            self.assertFalse((output / "current.json").exists())
            self.assertEqual(json.loads((output / "run-manifest.json").read_text(encoding="utf-8")), result)

    def test_dot_record_path_writes_failure_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root / ".local")
            manifest_path = source / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pages"][0]["record_path"] = "."
            save_json(manifest_path, manifest)
            output = root / "output"
            result = run_local_mvp(source, output, as_of="2026-09-24")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error_type"], "ValueError")
            self.assertFalse((output / "current.json").exists())
            self.assertEqual(json.loads((output / "run-manifest.json").read_text(encoding="utf-8")), result)

    def test_bill_url_mode_writes_manifest_and_preserves_last_good_on_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / ".local" / "mvp"
            output.mkdir(parents=True)
            current = output / "current.json"
            current.write_text('{"previous":"good"}', encoding="utf-8")
            argv = ["run_local_mvp.py", "--output-dir", str(output), "--as-of", "2026-09-24",
                    "--bill-url", "https://www.sangiin.go.jp/japanese/joho1/kousei/gian/221/meisai/m221080221053.htm"]
            with patch("sys.argv", argv), patch.object(Path, "is_relative_to", return_value=True), \
                 patch.object(runner, "fetch_bill_pages", side_effect=ValueError("redirect rejected")):
                self.assertEqual(runner.main(), 1)
            self.assertEqual(current.read_text(encoding="utf-8"), '{"previous":"good"}')
            receipt = json.loads((output / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["source_status"], "failed")
            self.assertEqual(receipt["error_type"], "ValueError")

    def test_failed_source_fetch_writes_run_receipt_and_keeps_last_good(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / ".local" / "mvp"
            output.mkdir(parents=True)
            current = output / "current.json"
            current.write_text('{"previous":"good"}', encoding="utf-8")
            argv = ["run_local_mvp.py", "--output-dir", str(output),
                    "--session-from", "1", "--session-to", "1", "--max-pages", "1"]
            with patch.object(runner, "collect_pages", return_value={"status": "failed",
                                                                   "error_type": "TimeoutError"}), \
                 patch("sys.argv", argv):
                # main normally restricts output to repo .local; isolate just that path check.
                with patch.object(Path, "is_relative_to", return_value=True):
                    self.assertEqual(runner.main(), 1)
            self.assertEqual(current.read_text(encoding="utf-8"), '{"previous":"good"}')
            receipt = json.loads((output / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["source_status"], "failed")
            self.assertTrue(receipt["last_good_preserved"])

    def test_network_retry_is_bounded_and_sequential(self):
        attempts = []
        waits = []

        def fetch(url):
            attempts.append(url)
            if len(attempts) < 3:
                raise OSError("temporary network failure")
            return {"ok": True}

        self.assertEqual(_fetch_with_retries("https://kokkai.ndl.go.jp/api/speech", fetch, waits.append),
                         {"ok": True})
        self.assertEqual(len(attempts), 3)
        self.assertEqual(waits, [3.0, 3.0])

    def make_source(self, root: Path) -> Path:
        source = root / "diet"
        speech = {
            "speechID": "speech-1", "speaker": "架空でない発言者", "speech": "研究開発を進めます。",
            "date": "2024-04-01", "speechURL": "https://kokkai.ndl.go.jp/txt/example/1",
            "issueID": "issue-1",
        }
        page_hash = save_json(source / "pages" / "000000001.json", {
            "numberOfRecords": 1, "numberOfReturn": 1, "startRecord": 1,
            "speechRecord": [speech],
        })
        material = source / "external-materials" / "page-1" / "record"
        material.mkdir(parents=True)
        (material / "original.json").write_bytes((source / "pages" / "000000001.json").read_bytes())
        save_json(material / "record.json", {
            "schema_version": "external-material/v1", "saved_filename": "original.json",
            "source_url": "https://kokkai.ndl.go.jp/api/speech?sessionFrom=1",
            "sha256": page_hash, "bytes": (material / "original.json").stat().st_size,
            "observed_at": "2026-09-24T12:00:00+09:00",
        })
        save_json(source / "manifest.json", {
            "schema_version": "diet-api-manifest/v1", "endpoint": "speech",
            "status": "query_exhausted", "complete": True,
            "records_saved": 1, "records_reported": 1,
            "observed_at": "2026-09-24T12:00:00+09:00",
            "pages": [{"start_record": 1, "record_count": 1, "sha256": page_hash,
                       "source_url": "https://kokkai.ndl.go.jp/api/speech?sessionFrom=1",
                       "record_path": str(material / "record.json")}],
        })
        return source

    def test_official_speech_without_bill_vote_or_impact_is_held(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_source(Path(temp))
            dataset = build_dataset(source, as_of="2026-09-24")
            self.assertFalse(dataset["fictional"])
            self.assertEqual(dataset["policies"], [])
            self.assertEqual(dataset["involvements"], [])
            self.assertEqual(dataset["coverage"]["assessedPeople"], 0)
            self.assertEqual(dataset["held"][0]["reason"], "speech_is_not_action_or_impact")
            self.assertEqual(dataset["held"][0]["sourceUrl"],
                             "https://kokkai.ndl.go.jp/txt/example/1")

    def test_quote_must_match_hashed_original_before_promotion(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_source(Path(temp))
            pack = {"policies": [{"id": "bill-1", "title": "研究開発法案", "action_date": "2024-04-01",
                                  "source_speech_id": "speech-1", "quote": "存在しない引用"}]}
            pack_path = Path(temp) / "pack.json"
            save_json(pack_path, pack)
            dataset = build_dataset(source, as_of="2026-09-24", candidate_pack=pack_path)
            self.assertEqual(dataset["policies"], [])
            self.assertEqual(dataset["held"][0]["reason"], "quote_mismatch")

    def test_recent_policy_leads_are_limited_to_newest_three(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_source(Path(temp))
            pack_path = Path(temp) / "pack.json"
            save_json(pack_path, {"policies": [
                {"id": item, "action_date": action_date, "source_speech_id": "speech-1",
                 "quote": "研究開発を進めます。"}
                for item, action_date in (("old", "2019-01-01"), ("p1", "2023-01-01"),
                                          ("p2", "2024-01-01"), ("p3", "2025-01-01"),
                                          ("p4", "2026-01-01"))
            ]})
            dataset = build_dataset(source, as_of="2026-09-24", candidate_pack=pack_path)
            self.assertEqual(dataset["coverage"]["candidatePolicies"], 3)
            self.assertEqual([item["id"] for item in dataset["held"][:3]], ["p4", "p3", "p2"])
            self.assertIn({"id": "old", "reason": "outside_recent_four_years",
                           "sourceSpeechId": "speech-1"}, dataset["held"])

    def test_corrupt_source_preserves_previous_good_published_dataset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            output = root / "output"
            first = run_local_mvp(source, output, as_of="2026-09-24")
            self.assertEqual(first["status"], "ready")
            before = (output / "current.json").read_bytes()
            (source / "pages" / "000000001.json").write_text("{}", encoding="utf-8")
            second = run_local_mvp(source, output, as_of="2026-09-24")
            self.assertEqual(second["status"], "failed")
            self.assertEqual((output / "current.json").read_bytes(), before)

    def test_tampered_registered_original_rejects_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_source(Path(temp))
            (source / "external-materials" / "page-1" / "record" / "original.json").write_text(
                "{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "registered original hash mismatch"):
                build_dataset(source, as_of="2026-09-24")

    def test_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            output = root / "output"
            run_local_mvp(source, output, as_of="2026-09-24")
            before = (output / "current.json").read_bytes()
            run_local_mvp(source, output, as_of="2026-09-24")
            self.assertEqual((output / "current.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
