import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.fetch_diet_minutes import collect_pages
from scripts import fetch_diet_minutes as collector


class CollectPagesTests(unittest.TestCase):
    def test_registration_reused_after_checkpoint_write_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            args = dict(endpoint="speech", session_from=1, session_to=2,
                        output_dir=Path(temp), maximum_records=1,
                        delay_seconds=3, max_pages=1)
            response = {"numberOfRecords": 1, "numberOfReturn": 1, "startRecord": 1,
                        "speechRecord": [{"speechID": "a"}]}
            original = collector._write_json
            def fail_checkpoint(path, value):
                if path.name == "checkpoint.json":
                    raise OSError("injected checkpoint write failure")
                return original(path, value)
            with patch.object(collector, "_write_json", side_effect=fail_checkpoint):
                with self.assertRaises(OSError):
                    collect_pages(**args, fetch_json=lambda _: response)
            result = collect_pages(**args, fetch_json=lambda _: response)
            self.assertEqual(result["status"], "query_exhausted")
            self.assertEqual(len(list(Path(temp).glob("external-materials/**/record.json"))), 1)

    def test_resume_rejects_inconsistent_checkpoint_and_page_metadata(self):
        mutations = ("next_record", "complete", "startRecord", "numberOfReturn", "numberOfRecords")
        for field in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                args = dict(endpoint="speech", session_from=1, session_to=2,
                            output_dir=Path(temp), maximum_records=1,
                            delay_seconds=3, max_pages=1)
                response = {"numberOfRecords": 2, "numberOfReturn": 1, "startRecord": 1,
                            "nextRecordPosition": 2, "speechRecord": [{"speechID": "a"}]}
                collect_pages(**args, fetch_json=lambda _: response)
                checkpoint_path = Path(temp) / "checkpoint.json"
                checkpoint = json.loads(checkpoint_path.read_text())
                if field in ("next_record", "complete"):
                    checkpoint[field] = 9 if field == "next_record" else True
                else:
                    response[field] = 9
                    payload = collector._write_json(Path(temp) / "pages/000000001.json", response)
                    checkpoint["pages"][0]["sha256"] = collector.hashlib.sha256(payload).hexdigest()
                collector._write_json(checkpoint_path, checkpoint)
                with self.assertRaises(ValueError):
                    collect_pages(**args, fetch_json=lambda _: response)

    def test_saves_pages_hashes_and_resumes_from_checkpoint(self) -> None:
        responses = {
            1: {
                "startRecord": 1, "numberOfReturn": 2,
                "numberOfRecords": 3,
                "nextRecordPosition": 3,
                "meetingRecord": [{"issueID": "a"}, {"issueID": "b"}],
            },
            3: {
                "startRecord": 3, "numberOfReturn": 1,
                "numberOfRecords": 3,
                "meetingRecord": [{"issueID": "c"}],
            },
        }
        calls: list[int] = []

        def fetch_json(url: str) -> dict:
            start = int(url.split("startRecord=")[1].split("&")[0])
            calls.append(start)
            return responses[start]

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            manifest = collect_pages(
                endpoint="meeting_list",
                session_from=1,
                session_to=999,
                output_dir=output,
                maximum_records=2,
                delay_seconds=3,
                fetch_json=fetch_json,
                sleep=lambda _: None,
                all_pages=True,
            )

            self.assertEqual(calls, [1, 3])
            self.assertEqual(manifest["records_reported"], 3)
            self.assertEqual(manifest["records_saved"], 3)
            self.assertEqual(len(manifest["pages"]), 2)
            self.assertEqual(len(manifest["pages"][0]["sha256"]), 64)
            self.assertEqual(json.loads((output / "checkpoint.json").read_text())["next_record"], None)

            calls.clear()
            resumed = collect_pages(
                endpoint="meeting_list",
                session_from=1,
                session_to=999,
                output_dir=output,
                maximum_records=2,
                delay_seconds=3,
                fetch_json=fetch_json,
                sleep=lambda _: None,
                all_pages=True,
            )
            self.assertEqual(calls, [])
            self.assertEqual(resumed["records_saved"], 3)

    def test_completed_resume_preserves_observation_time_and_rebuilds_missing_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            args = dict(endpoint="speech", session_from=1, session_to=1,
                        output_dir=Path(temp), maximum_records=1,
                        delay_seconds=3, max_pages=1)
            response = {"numberOfRecords": 1, "numberOfReturn": 1, "startRecord": 1,
                        "speechRecord": [{"speechID": "a"}]}
            first = collect_pages(**args, fetch_json=lambda _: response)
            observed_at = first["observed_at"]
            checkpoint = json.loads((Path(temp) / "checkpoint.json").read_text())
            self.assertEqual(checkpoint["completed_at"], observed_at)
            repeated = collect_pages(**args, fetch_json=lambda _: self.fail("completed checkpoint must not refetch"))
            self.assertEqual(repeated["observed_at"], observed_at)
            self.assertEqual(repeated["recorded_at"], first["recorded_at"])
            (Path(temp) / "manifest.json").unlink()
            resumed = collect_pages(**args, fetch_json=lambda _: self.fail("completed checkpoint must not refetch"))
            self.assertEqual(resumed["observed_at"], observed_at)
            self.assertEqual(resumed["status"], "query_exhausted")

    def test_requires_explicit_page_limit_or_all_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            collect_pages(
                endpoint="speech",
                session_from=1,
                session_to=999,
                output_dir=Path(temp),
                maximum_records=100,
                delay_seconds=3,
                fetch_json=lambda _: {},
                sleep=lambda _: None,
                max_pages=None,
                all_pages=False,
            )

    def test_cap_resume_scope_failure_and_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            args = dict(endpoint="speech", session_from=1, session_to=2,
                        output_dir=Path(temp), maximum_records=1,
                        delay_seconds=3, max_pages=1, sleep=lambda _: None)
            first = {"numberOfRecords": 2, "numberOfReturn": 1, "startRecord": 1,
                     "nextRecordPosition": 2, "speechRecord": [{"speechID": "a"}]}
            result = collect_pages(**args, fetch_json=lambda _: first)
            self.assertEqual(result["status"], "capped")
            self.assertFalse(result["complete"])
            with self.assertRaises(ValueError):
                collect_pages(**{**args, "session_to": 3}, fetch_json=lambda _: {})
            duplicate = {**first, "startRecord": 2}
            duplicate.pop("nextRecordPosition")
            result = collect_pages(**args, fetch_json=lambda _: duplicate)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["records_saved"], 1)
            result = collect_pages(**args, fetch_json=lambda _: (_ for _ in ()).throw(TimeoutError()))
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["corpus_complete"])

    def test_invalid_pages_cannot_be_complete(self):
        for response in ({"message": "busy"},
                         {"numberOfRecords": 2, "numberOfReturn": 1, "startRecord": 1,
                          "speechRecord": [{"speechID": "a"}]},
                         {"numberOfRecords": 2, "numberOfReturn": 1, "startRecord": 1,
                          "nextRecordPosition": 1, "speechRecord": [{"speechID": "a"}]}):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as temp:
                result = collect_pages(endpoint="speech", session_from=1, session_to=2,
                                       output_dir=Path(temp), maximum_records=1,
                                       delay_seconds=3, max_pages=1,
                                       fetch_json=lambda _: response)
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["complete"])

    def test_tampered_page_rejected_before_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            args = dict(endpoint="speech", session_from=1, session_to=2,
                        output_dir=Path(temp), maximum_records=1,
                        delay_seconds=3, max_pages=1)
            response = {"numberOfRecords": 1, "numberOfReturn": 1, "startRecord": 1,
                        "speechRecord": [{"speechID": "a"}]}
            collect_pages(**args, fetch_json=lambda _: response)
            (Path(temp) / "pages/000000001.json").write_text("{}")
            with self.assertRaises(ValueError):
                collect_pages(**args, fetch_json=lambda _: response)


if __name__ == "__main__":
    unittest.main()
