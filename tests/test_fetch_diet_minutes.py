import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from pathlib import Path

from scripts.fetch_diet_minutes import collect_pages
from scripts import fetch_diet_minutes as collector


class CollectPagesTests(unittest.TestCase):
    def test_each_page_keeps_response_observation_not_manifest_time(self):
        class Clock(datetime):
            ticks = iter(
                (
                    datetime(2026, 9, 24, 1, tzinfo=timezone.utc),
                    datetime(2026, 9, 24, 2, tzinfo=timezone.utc),
                    datetime(2026, 9, 24, 3, tzinfo=timezone.utc),
                )
            )

            @classmethod
            def now(cls, tz=None):
                return next(cls.ticks)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            material = Path(temp) / "materials"

            def fetch(url):
                start = int(url.split("startRecord=")[1].split("&")[0])
                return {
                    "numberOfRecords": 2,
                    "numberOfReturn": 1,
                    "startRecord": start,
                    **({"nextRecordPosition": 2} if start == 1 else {}),
                    "speechRecord": [{"speechID": str(start)}],
                }

            with patch.object(collector, "datetime", Clock):
                manifest = collect_pages(
                    endpoint="speech",
                    session_from=1,
                    session_to=1,
                    output_dir=output,
                    maximum_records=1,
                    delay_seconds=3,
                    max_pages=2,
                    material_root=material,
                    fetch_json=fetch,
                    sleep=lambda _: None,
                )
            times = [page["observed_at"] for page in manifest["pages"]]
            self.assertEqual(
                [
                    datetime.fromisoformat(value).astimezone(timezone.utc).hour
                    for value in times
                ],
                [1, 2],
            )
            self.assertEqual(manifest["observed_at"], times[-1])
            self.assertNotEqual(manifest["recorded_at"], times[-1])

    def test_cli_accepts_primary_repo_local_with_explicit_material_root(self):
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / "primary" / ".local"
            material = local / "external-materials"
            output = local / "diet" / "finite" / "speech"
            argv = [
                "fetch_diet_minutes.py",
                "speech",
                "--session-from",
                "221",
                "--session-to",
                "221",
                "--date-from",
                "2026-07-10",
                "--date-to",
                "2026-07-10",
                "--house",
                "参議院",
                "--output-dir",
                str(output),
                "--material-root",
                str(material),
                "--maximum-records",
                "10",
                "--max-pages",
                "1",
            ]
            with patch("sys.argv", argv), patch.object(
                collector, "collect_pages", return_value={"status": "capped"}
            ) as mocked:
                self.assertEqual(collector.main(), 0)
                self.assertEqual(mocked.call_args.kwargs["material_root"], material)
            other = Path(temp) / "other" / ".local" / "diet" / "finite" / "speech"
            argv[argv.index(str(output))] = str(other)
            with patch("sys.argv", argv), self.assertRaises(SystemExit):
                collector.main()

    def test_date_house_scope_and_readable_body_are_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            material = Path(temp) / "materials"
            pages = {
                1: {
                    "numberOfRecords": 2,
                    "numberOfReturn": 1,
                    "startRecord": 1,
                    "nextRecordPosition": 2,
                    "speechRecord": [
                        {
                            "speechID": "appendix",
                            "speech": "附録本文",
                            "date": "2025-01-01",
                            "imageKind": "附録",
                        }
                    ],
                },
                2: {
                    "numberOfRecords": 2,
                    "numberOfReturn": 1,
                    "startRecord": 2,
                    "speechRecord": [
                        {
                            "speechID": "readable",
                            "speech": "研究開発を審議した。",
                            "date": "2025-01-01",
                            "imageKind": "会議録",
                        }
                    ],
                },
            }
            urls = []

            def fetch(url):
                urls.append(url)
                return pages[int(url.split("startRecord=")[1].split("&")[0])]

            args = dict(
                endpoint="speech",
                session_from=210,
                session_to=220,
                output_dir=output,
                maximum_records=1,
                delay_seconds=3,
                max_pages=2,
                material_root=material,
                date_from="2022-09-24",
                date_to="2026-09-24",
                house="参議院",
                sleep=lambda _: None,
            )
            result = collect_pages(**args, fetch_json=fetch)
            self.assertEqual(result["records_saved"], 2)
            self.assertEqual(result["readable_body_count"], 1)
            self.assertEqual(result["confirmed_action_evidence_count"], 0)
            self.assertTrue(
                all(
                    "from=2022-09-24" in url
                    and "until=2026-09-24" in url
                    and "nameOfHouse=" in url
                    for url in urls
                )
            )
            with self.assertRaisesRegex(ValueError, "scope mismatch"):
                collect_pages(**{**args, "house": "衆議院"}, fetch_json=fetch)
            self.assertEqual(len(list(material.glob("**/record.json"))), 2)

    def test_missing_date_and_missing_observation_do_not_pass_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            material = Path(temp) / "materials"
            response = {
                "numberOfRecords": 1,
                "numberOfReturn": 1,
                "startRecord": 1,
                "speechRecord": [{"speechID": "a", "speech": "本文", "date": None}],
            }
            args = dict(
                endpoint="speech",
                session_from=1,
                session_to=1,
                output_dir=output,
                maximum_records=1,
                delay_seconds=3,
                max_pages=1,
                material_root=material,
            )
            result = collect_pages(**args, fetch_json=lambda _: response)
            self.assertEqual(result["readable_body_count"], 0)
            record_path = next(material.glob("**/record.json"))
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record.pop("observed_at")
            record_path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(ValueError):
                collect_pages(
                    **args, fetch_json=lambda _: self.fail("must not refetch")
                )

    def test_meeting_body_inherits_parent_date_but_excludes_appendix(self):
        records = [
            {
                "issueID": "meeting-1",
                "date": "2025-01-01",
                "imageKind": "会議録",
                "speechRecord": [
                    {"speechID": "spoken", "speech": "議案について発言した。"}
                ],
            },
            {
                "issueID": "appendix-1",
                "date": "2025-01-01",
                "imageKind": "附録",
                "speechRecord": [{"speechID": "appendix", "speech": "資料本文"}],
            },
        ]
        self.assertEqual(collector._readable_body_count("meeting", records), 1)
        self.assertEqual(collector._readable_body_count("meeting_list", records), 0)

    def test_registration_reused_after_checkpoint_write_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            args = dict(
                endpoint="speech",
                session_from=1,
                session_to=2,
                output_dir=Path(temp) / "run",
                maximum_records=1,
                delay_seconds=3,
                max_pages=1,
                material_root=Path(temp) / "external-materials",
            )
            response = {
                "numberOfRecords": 1,
                "numberOfReturn": 1,
                "startRecord": 1,
                "speechRecord": [{"speechID": "a"}],
            }
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
            self.assertEqual(len(list(args["material_root"].glob("**/record.json"))), 1)

    def test_resume_rejects_inconsistent_checkpoint_and_page_metadata(self):
        mutations = (
            "next_record",
            "complete",
            "startRecord",
            "numberOfReturn",
            "numberOfRecords",
        )
        for field in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                args = dict(
                    endpoint="speech",
                    session_from=1,
                    session_to=2,
                    output_dir=Path(temp),
                    maximum_records=1,
                    delay_seconds=3,
                    max_pages=1,
                )
                response = {
                    "numberOfRecords": 2,
                    "numberOfReturn": 1,
                    "startRecord": 1,
                    "nextRecordPosition": 2,
                    "speechRecord": [{"speechID": "a"}],
                }
                collect_pages(**args, fetch_json=lambda _: response)
                checkpoint_path = Path(temp) / "checkpoint.json"
                checkpoint = json.loads(checkpoint_path.read_text())
                if field in ("next_record", "complete"):
                    checkpoint[field] = 9 if field == "next_record" else True
                else:
                    response[field] = 9
                    payload = collector._write_json(
                        Path(temp) / "pages/000000001.json", response
                    )
                    checkpoint["pages"][0]["sha256"] = collector.hashlib.sha256(
                        payload
                    ).hexdigest()
                collector._write_json(checkpoint_path, checkpoint)
                with self.assertRaises(ValueError):
                    collect_pages(**args, fetch_json=lambda _: response)

    def test_saves_pages_hashes_and_resumes_from_checkpoint(self) -> None:
        responses = {
            1: {
                "startRecord": 1,
                "numberOfReturn": 2,
                "numberOfRecords": 3,
                "nextRecordPosition": 3,
                "meetingRecord": [{"issueID": "a"}, {"issueID": "b"}],
            },
            3: {
                "startRecord": 3,
                "numberOfReturn": 1,
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
            self.assertEqual(
                json.loads((output / "checkpoint.json").read_text())["next_record"],
                None,
            )

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

    def test_completed_resume_preserves_observation_time_and_rebuilds_missing_manifest(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            args = dict(
                endpoint="speech",
                session_from=1,
                session_to=1,
                output_dir=Path(temp),
                maximum_records=1,
                delay_seconds=3,
                max_pages=1,
            )
            response = {
                "numberOfRecords": 1,
                "numberOfReturn": 1,
                "startRecord": 1,
                "speechRecord": [{"speechID": "a"}],
            }
            first = collect_pages(**args, fetch_json=lambda _: response)
            observed_at = first["observed_at"]
            checkpoint = json.loads((Path(temp) / "checkpoint.json").read_text())
            self.assertEqual(checkpoint["completed_at"], observed_at)
            repeated = collect_pages(
                **args,
                fetch_json=lambda _: self.fail("completed checkpoint must not refetch")
            )
            self.assertEqual(repeated["observed_at"], observed_at)
            self.assertEqual(repeated["recorded_at"], first["recorded_at"])
            (Path(temp) / "manifest.json").unlink()
            resumed = collect_pages(
                **args,
                fetch_json=lambda _: self.fail("completed checkpoint must not refetch")
            )
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
            args = dict(
                endpoint="speech",
                session_from=1,
                session_to=2,
                output_dir=Path(temp),
                maximum_records=1,
                delay_seconds=3,
                max_pages=1,
                sleep=lambda _: None,
            )
            first = {
                "numberOfRecords": 2,
                "numberOfReturn": 1,
                "startRecord": 1,
                "nextRecordPosition": 2,
                "speechRecord": [{"speechID": "a"}],
            }
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
            result = collect_pages(
                **args, fetch_json=lambda _: (_ for _ in ()).throw(TimeoutError())
            )
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["corpus_complete"])

    def test_invalid_pages_cannot_be_complete(self):
        for response in (
            {"message": "busy"},
            {
                "numberOfRecords": 2,
                "numberOfReturn": 1,
                "startRecord": 1,
                "speechRecord": [{"speechID": "a"}],
            },
            {
                "numberOfRecords": 2,
                "numberOfReturn": 1,
                "startRecord": 1,
                "nextRecordPosition": 1,
                "speechRecord": [{"speechID": "a"}],
            },
        ):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as temp:
                result = collect_pages(
                    endpoint="speech",
                    session_from=1,
                    session_to=2,
                    output_dir=Path(temp),
                    maximum_records=1,
                    delay_seconds=3,
                    max_pages=1,
                    fetch_json=lambda _: response,
                )
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["complete"])

    def test_tampered_page_rejected_before_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            args = dict(
                endpoint="speech",
                session_from=1,
                session_to=2,
                output_dir=Path(temp),
                maximum_records=1,
                delay_seconds=3,
                max_pages=1,
            )
            response = {
                "numberOfRecords": 1,
                "numberOfReturn": 1,
                "startRecord": 1,
                "speechRecord": [{"speechID": "a"}],
            }
            collect_pages(**args, fetch_json=lambda _: response)
            (Path(temp) / "pages/000000001.json").write_text("{}")
            with self.assertRaises(ValueError):
                collect_pages(**args, fetch_json=lambda _: response)


if __name__ == "__main__":
    unittest.main()
