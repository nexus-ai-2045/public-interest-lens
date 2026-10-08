import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.official_raw import capture_url, host_lock, readback
from scripts.fetch_diet_minutes import collect_pages
from scripts.collect_official_raw import collect_plan
from scripts.fetch_law_inventory import collect_inventory, validate_page


URL = "https://kokkai.ndl.go.jp/api/meeting?sessionFrom=1&sessionTo=1&startRecord=1&maximumRecords=10&recordPacking=json"


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload = payload
        self.code = status
        self.headers = headers or {
            "Content-Type": "application/json",
            "Set-Cookie": "private",
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.payload[:limit]


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


class RawTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.local = Path(temp.name) / ".local"
        self.material = self.local / "external-materials"
        self.control = self.local / "full-acquisition"
        self.clock = [1800000000.0]
        self.waits = []

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.clock[0] += seconds

    def capture(self, opener, task="raw-test", url=URL):
        return capture_url(
            url,
            material_root=self.material,
            control_root=self.control,
            task_id=task,
            title="検査原本",
            allowed_hosts={"kokkai.ndl.go.jp"},
            opener=opener,
            now=lambda: self.clock[0],
            sleep=self.sleep,
        )

    def test_exact_bytes_headers_and_completed_resume_without_network(self):
        payload = b'{  "a": "\\u65e5" }\r\n'
        opener = Opener([Response(payload)])
        first = self.capture(opener)
        self.assertEqual(readback(first, self.material), payload)
        self.assertEqual(first["representation"], "http-response-body-bytes")
        self.assertNotIn("set-cookie", first["headers"])
        self.assertEqual(self.capture(opener), first)
        self.assertEqual(opener.calls, 1)

    def test_head_metadata_cannot_be_reused_as_get_body(self):
        args = dict(
            material_root=self.material,
            control_root=self.control,
            task_id="head-test",
            title="容量確認",
            allowed_hosts={"kokkai.ndl.go.jp"},
            now=lambda: self.clock[0],
            sleep=self.sleep,
        )
        receipt = capture_url(
            URL, **args, method="HEAD", opener=Opener([Response(b"")])
        )
        self.assertEqual(receipt["representation"], "http-head-metadata")
        self.assertEqual(receipt["bytes"], 0)
        with self.assertRaises(ValueError):
            capture_url(URL, **args, opener=Opener([]))

    def test_host_interval_survives_different_tasks(self):
        self.capture(Opener([Response(b"{}")]), task="first")
        self.capture(
            Opener([Response(b"{}")]), task="second", url=URL + "&from=1947-01-01"
        )
        self.assertEqual(self.waits, [3.0])

    def test_corrupted_original_stops_before_refetch(self):
        first = self.capture(Opener([Response(b"{}")]))
        record = json.loads(Path(first["record_path"]).read_text(encoding="utf-8"))
        (Path(first["record_path"]).parent / record["saved_filename"]).write_bytes(
            b"broken"
        )
        opener = Opener([])
        with self.assertRaises(ValueError):
            self.capture(opener)
        self.assertEqual(opener.calls, 0)

    def test_rate_limit_response_saved_and_long_retry_deferred(self):
        r = self.capture(Opener([Response(b"wait", 429, {"Retry-After": "120"})]))
        self.assertEqual(r["status"], 429)
        self.assertEqual(readback(r, self.material), b"wait")
        opener = Opener([])
        with self.assertRaises(OSError):
            self.capture(opener, task="other")
        self.assertEqual(opener.calls, 0)

    def test_bounded_retries_preserve_every_http_body(self):
        opener = Opener(
            [Response(b"failure", 503), Response(b"retry", 503), Response(b"{}")]
        )
        r = self.capture(opener)
        self.assertEqual((r["status"], r["attempt"], opener.calls), (200, 3, 3))
        self.assertEqual(self.waits, [3.0, 3.0])
        self.assertEqual(len(list((self.control / "attempts").glob("*.json"))), 3)

    def test_invalid_retry_after_preserves_raw_and_stops_retries(self):
        opener = Opener([Response(b"failure", 503, {"Retry-After": "invalid"})])
        receipt = self.capture(opener)
        self.assertTrue(receipt["retry_after_invalid"])
        self.assertEqual(readback(receipt, self.material), b"failure")
        self.assertEqual(opener.calls, 1)

    def plan(self, run="plan-test", item_id="body"):
        plan = {
            "run_id": run,
            "allowed_hosts": ["kokkai.ndl.go.jp"],
            "items": [
                {
                    "id": "robots",
                    "url": "https://kokkai.ndl.go.jp/robots.txt",
                    "title": "取得規則",
                    "kind": "robots",
                },
                {"id": item_id, "url": URL, "title": "本文", "kind": "document"},
            ],
        }
        path = self.local / "plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    def test_robots_disallow_and_http_403_survive_split_resume(self):
        for status, body in [
            (200, b"User-agent: *\nDisallow: /\n"),
            (403, b"Forbidden"),
        ]:
            with self.subTest(status=status):
                task = f"robots-{status}"
                receipt = self.capture(
                    Opener([Response(body, status)]),
                    task=task,
                    url="https://kokkai.ndl.go.jp/robots.txt",
                )
                path = self.plan(run=f"plan-{status}")
                with patch(
                    "scripts.collect_official_raw.capture_url", return_value=receipt
                ) as fetch:
                    first = collect_plan(path, material_root=self.material, limit=1)
                    second = collect_plan(path, material_root=self.material, limit=1)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(first["processed_items"], 1)
                self.assertEqual(second["outcomes"][-1]["status"], "robots_disallowed")

    def test_invalid_plan_identifiers_stop_before_network_or_batch_write(self):
        for run, item in [
            ("../escape", "body"),
            ("valid", "../escape"),
            ("C:/outside", "body"),
        ]:
            path = self.plan(run=run, item_id=item)
            with patch("scripts.collect_official_raw.capture_url") as fetch:
                with self.assertRaises(ValueError):
                    collect_plan(path, material_root=self.material)
            fetch.assert_not_called()
            self.assertFalse((self.control / "batches").exists())

    def test_robots_network_failure_stops_initial_and_resumed_body(self):
        path = self.plan()
        with patch(
            "scripts.collect_official_raw.capture_url", side_effect=OSError("offline")
        ) as fetch:
            first = collect_plan(path, material_root=self.material, limit=1)
            second = collect_plan(path, material_root=self.material, limit=1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(second["outcomes"][-1]["status"], "robots_disallowed")
        other = self.plan(run="plan-same-run")
        with patch(
            "scripts.collect_official_raw.capture_url", side_effect=OSError("offline")
        ) as fetch:
            result = collect_plan(other, material_root=self.material, limit=2)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["outcomes"][-1]["status"], "robots_disallowed")

    def test_reversed_plan_checks_robots_before_body(self):
        path = self.plan()
        plan = json.loads(path.read_text(encoding="utf-8"))
        plan["items"].reverse()
        path.write_text(json.dumps(plan), encoding="utf-8")
        receipt = self.capture(
            Opener([Response(b"User-agent: *\nDisallow: /\n")]),
            url="https://kokkai.ndl.go.jp/robots.txt",
        )
        with patch(
            "scripts.collect_official_raw.capture_url", return_value=receipt
        ) as fetch:
            result = collect_plan(path, material_root=self.material)
        self.assertEqual(
            [call.args[0] for call in fetch.call_args_list],
            ["https://kokkai.ndl.go.jp/robots.txt"],
        )
        body = next(o for o in result["outcomes"] if o["kind"] == "document")
        self.assertEqual(body["status"], "robots_disallowed")
        self.assertEqual(result["document_candidates_saved"], 0)

    def test_missing_robots_stops_body_without_network(self):
        path = self.plan()
        plan = json.loads(path.read_text(encoding="utf-8"))
        plan["items"] = [plan["items"][1]]
        path.write_text(json.dumps(plan), encoding="utf-8")
        with patch("scripts.collect_official_raw.capture_url") as fetch:
            result = collect_plan(path, material_root=self.material)
        fetch.assert_not_called()
        self.assertEqual(result["outcomes"][0]["status"], "robots_disallowed")
        self.assertEqual(result["document_candidates_saved"], 0)

    def test_reversed_plan_robots_failure_never_requests_body(self):
        path = self.plan()
        plan = json.loads(path.read_text(encoding="utf-8"))
        plan["items"].reverse()
        path.write_text(json.dumps(plan), encoding="utf-8")
        with patch(
            "scripts.collect_official_raw.capture_url", side_effect=OSError("offline")
        ) as fetch:
            result = collect_plan(path, material_root=self.material)
        self.assertEqual(
            [call.args[0] for call in fetch.call_args_list],
            ["https://kokkai.ndl.go.jp/robots.txt"],
        )
        body = next(o for o in result["outcomes"] if o["kind"] == "document")
        self.assertEqual(body["status"], "robots_disallowed")

    def test_allowed_robots_preserves_normal_body_capture(self):
        path = self.plan()
        robots = self.capture(
            Opener([Response(b"User-agent: *\nAllow: /\n")]),
            task="allowed-robots",
            url="https://kokkai.ndl.go.jp/robots.txt",
        )
        body = self.capture(Opener([Response(b"{}")]), task="allowed-body")
        with patch(
            "scripts.collect_official_raw.capture_url", side_effect=[robots, body]
        ) as fetch:
            result = collect_plan(path, material_root=self.material)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["document_candidates_saved"], 1)
        self.assertEqual(result["outcomes"][-1]["robots_status"], "parsed")

    def test_host_lock_rejects_another_writer(self):
        with host_lock(self.control, "kokkai.ndl.go.jp"):
            with self.assertRaises(OSError), host_lock(
                self.control, "kokkai.ndl.go.jp"
            ):
                self.fail("concurrent host lock unexpectedly allowed")

    def test_ndl_collector_keeps_received_spacing_and_resume(self):
        payload = b'{ "numberOfRecords": 1, "numberOfReturn":1, "startRecord":1, "meetingRecord":[{"issueID":"one"}] }\n'
        from scripts.fetch_diet_minutes import _build_url

        receipt = self.capture(
            Opener([Response(payload)]), url=_build_url("meeting", 1, 1, 1, 10)
        )
        args = dict(
            endpoint="meeting",
            session_from=1,
            session_to=1,
            output_dir=self.local / "diet" / "raw-shard",
            material_root=self.material,
            maximum_records=10,
            delay_seconds=3,
            max_pages=1,
        )
        result = collect_pages(**args, fetch_raw=lambda url: receipt)
        self.assertEqual(result["raw_response_pages"], 1)
        self.assertEqual(
            (args["output_dir"] / "pages" / "000000001.json").read_bytes(), payload
        )
        repeated = collect_pages(
            **args, fetch_raw=lambda url: self.fail("must not refetch")
        )
        self.assertEqual(result, repeated)

    def test_index_only_and_empty_bodies_are_not_readable(self):
        payload = b'{"numberOfRecords":1,"numberOfReturn":1,"startRecord":1,"meetingRecord":[{"issueID":"one"}]}'
        from scripts.fetch_diet_minutes import _build_url

        r = self.capture(
            Opener([Response(payload)]), url=_build_url("meeting_list", 1, 1, 1, 100)
        )
        result = collect_pages(
            endpoint="meeting_list",
            session_from=1,
            session_to=1,
            output_dir=self.local / "diet" / "index",
            material_root=self.material,
            maximum_records=100,
            delay_seconds=3,
            max_pages=1,
            fetch_raw=lambda url: r,
        )
        self.assertEqual(result["readable_body_count"], 0)
        self.assertFalse(result["corpus_complete"])

    def test_law_id_inventory_resume_and_not_text_completion(self):
        data = [
            {
                "total_count": 2,
                "count": 1,
                "next_offset": 1,
                "laws": [{"law_info": {"law_id": "a"}}],
            },
            {
                "total_count": 2,
                "count": 1,
                "next_offset": None,
                "laws": [{"law_info": {"law_id": "b"}}],
            },
        ]
        opener = Opener([Response(json.dumps(d).encode()) for d in data])

        def fetch(url):
            return capture_url(
                url,
                material_root=self.material,
                control_root=self.control,
                task_id=f"law-fixture-{opener.calls}",
                title="法令索引検査",
                allowed_hosts={"laws.e-gov.go.jp"},
                opener=opener,
                now=lambda: self.clock[0],
                sleep=self.sleep,
            )

        args = dict(
            material_root=self.material,
            as_of="2026-10-03",
            run_id="law-test",
            max_pages=1,
        )
        first = collect_inventory(**args, fetch=fetch)
        self.assertFalse(first["complete"])
        second = collect_inventory(**args, fetch=fetch)
        self.assertTrue(second["complete"])
        self.assertEqual(second["ids_saved"], 2)
        self.assertFalse(second["corpus_complete"])
        self.assertEqual(second["law_texts_saved"], 0)
        collect_inventory(
            **args, fetch=lambda url: self.fail("completed inventory refetched")
        )

    def test_law_inventory_count_drift_duplicate_and_loop_rejected(self):
        base = {
            "total_count": 2,
            "count": 1,
            "next_offset": 1,
            "laws": [{"law_info": {"law_id": "a"}}],
        }
        for changed, reported, seen in [
            ({**base, "total_count": 3}, 2, set()),
            (base, 2, {"a"}),
            ({**base, "next_offset": 0}, 2, set()),
        ]:
            with self.assertRaises(ValueError):
                validate_page(changed, offset=0, reported=reported, seen=seen)

    def test_law_resume_different_time_source_rejected_without_network(self):
        from scripts.fetch_law_inventory import inventory_url

        data = {
            "total_count": 1,
            "count": 1,
            "next_offset": None,
            "laws": [{"law_info": {"law_id": "a"}}],
        }
        receipt = capture_url(
            inventory_url("2026-10-02", 0),
            material_root=self.material,
            control_root=self.control,
            task_id="wrong-law-date",
            title="法令一覧検査",
            allowed_hosts={"laws.e-gov.go.jp"},
            opener=Opener([Response(json.dumps(data).encode())]),
            now=lambda: self.clock[0],
            sleep=self.sleep,
        )
        checkpoint = self.control / "law-inventory" / "wrong-date" / "checkpoint.json"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_text(
            json.dumps(
                {
                    "as_of": "2026-10-03",
                    "ids_saved": 1,
                    "complete": True,
                    "next_offset": None,
                    "pages": [{"offset": 0, "ids": ["a"], "receipt": receipt}],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            collect_inventory(
                material_root=self.material,
                as_of="2026-10-03",
                run_id="wrong-date",
                max_pages=1,
                fetch=lambda url: self.fail("source mismatch must not refetch"),
            )

    def test_corpus_round_budget_stops_on_complete_or_failed(self):
        from scripts import collect_diet_corpus

        for complete, status in [(True, "query_exhausted"), (False, "failed")]:
            result = {"corpus_complete": complete, "results": [{"status": status}]}
            argv = [
                "collect_diet_corpus",
                "--plan",
                "unused",
                "--material-root",
                "unused",
                "--rounds",
                "10",
            ]
            with patch("sys.argv", argv), patch.object(
                collect_diet_corpus, "collect_corpus", return_value=result
            ) as collect:
                collect_diet_corpus.main()
            self.assertEqual(collect.call_count, 1)

    def test_frozen_index_count_mismatch_keeps_raw_without_success_checkpoint(self):
        from scripts.fetch_diet_minutes import _build_url

        payload = b'{"numberOfRecords":2,"numberOfReturn":1,"startRecord":1,"nextRecordPosition":2,"meetingRecord":[{"issueID":"one"}]}'
        receipt = self.capture(
            Opener([Response(payload)]), url=_build_url("meeting", 1, 1, 1, 10)
        )
        output = self.local / "diet" / "changed-count"
        result = collect_pages(
            endpoint="meeting",
            session_from=1,
            session_to=1,
            output_dir=output,
            material_root=self.material,
            maximum_records=10,
            delay_seconds=3,
            max_pages=1,
            expected_records=1,
            fetch_raw=lambda url: receipt,
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["records_saved"], 0)
        self.assertFalse((output / "checkpoint.json").exists())
        self.assertEqual(readback(receipt, self.material), payload)

    def test_same_count_changed_meeting_identifier_is_not_released_complete(self):
        import hashlib
        from scripts.collect_diet_corpus import collect_corpus

        plan = {
            "run_id": "body-id-test",
            "shards": [
                {
                    "id": "one",
                    "endpoint": "meeting",
                    "session_from": 1,
                    "session_to": 1,
                    "date_from": "1947-05-03",
                    "date_to": "2026-10-03",
                    "house": "衆議院",
                    "expected_index_records": 1,
                    "expected_issue_ids_sha256": hashlib.sha256(
                        b"original"
                    ).hexdigest(),
                }
            ],
        }
        path = self.local / "body-plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan), encoding="utf-8")

        def complete(**args):
            page = args["output_dir"] / "pages" / "000000001.json"
            page.parent.mkdir(parents=True)
            page.write_text(
                json.dumps({"meetingRecord": [{"issueID": "changed"}]}),
                encoding="utf-8",
            )
            return {
                "complete": True,
                "status": "query_exhausted",
                "records_saved": 1,
                "records_reported": 1,
                "readable_body_count": 0,
                "raw_response_pages": 1,
                "pages": [{"start_record": 1}],
            }

        with patch("scripts.collect_diet_corpus.collect_pages", side_effect=complete):
            result = collect_corpus(
                path, material_root=self.material, max_shards=1, pages_per_shard=1
            )
        self.assertFalse(result["corpus_complete"])
        self.assertEqual(
            result["results"][0]["error_type"], "FrozenInventoryIdentifiersMismatch"
        )


if __name__ == "__main__":
    unittest.main()
