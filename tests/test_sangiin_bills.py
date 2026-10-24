"""参議院の限定法案ページ取得から保留データを作る契約。"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts.sangiin_bills import fetch_bill_pages, parse_bill_page


URLS = [
    f"https://www.sangiin.go.jp/japanese/joho1/kousei/gian/221/meisai/m2210802210{number}.htm"
    for number in ("53", "41", "26")
]


def html(number: str, title: str) -> bytes:
    return f"""<html><meta charset="UTF-8"><table summary="議案審議情報一覧">
    <tr><th>件名</th><td>{title}</td></tr><tr><th>提出回次</th><td>221回</td>
    <th>提出番号</th><td>{int(number)}</td></tr>
    <tr><th>提出日</th><td>令和8年3月{int(number) % 20 + 1}日</td></tr>
    <tr><th>採決方法</th><td>押しボタン<a href="/japanese/joho1/kousei/vote/221/v{number}.htm">投票結果はこちら</a></td></tr>
    </table></html>""".encode("utf-8")


class BillPageTests(unittest.TestCase):
    def test_resolved_registration_uses_only_verified_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "run"
            storage = root / "materials"
            initial = fetch_bill_pages([URLS[0]], output, as_of="2026-09-24",
                                       fetch_bytes=lambda _: html("53", "検証済み法案"),
                                       sleep=lambda _: None, storage_root=storage)
            existing = next((storage / "bill-221-53").glob("*/record.json"))
            record = json.loads(existing.read_text(encoding="utf-8"))
            verified = storage / "verified" / "record.json"
            verified.parent.mkdir()
            verified.write_bytes(existing.read_bytes())
            original = existing.parent / record["saved_filename"]
            (verified.parent / record["saved_filename"]).write_bytes(original.read_bytes())
            original.write_bytes(html("53", "未検査の隣接法案"))
            resolve = Path.resolve

            def redirected_resolve(path, *args, **kwargs):
                return resolve(verified if path == existing else path, *args, **kwargs)

            calls = []
            with patch.object(Path, "resolve", redirected_resolve):
                replay = fetch_bill_pages([URLS[0]], root / "replay", as_of="2026-09-24",
                                          fetch_bytes=lambda url: calls.append(url) or b"unexpected",
                                          sleep=lambda _: None, storage_root=storage)
            self.assertEqual(calls, [])
            self.assertEqual(replay, initial)

    def test_non_object_registration_rejects_source_with_value_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "run"
            storage = root / "materials"
            fetch_bill_pages([URLS[0]], output, as_of="2026-09-24",
                             fetch_bytes=lambda _: html("53", "研究開発の法案53"),
                             sleep=lambda _: None, storage_root=storage)
            existing = next((storage / "bill-221-53").glob("*/record.json"))
            existing.write_text("[]", encoding="utf-8")
            calls = []
            with self.assertRaisesRegex(ValueError, "registration is invalid"):
                fetch_bill_pages([URLS[0]], output, as_of="2026-09-24",
                                 fetch_bytes=lambda url: calls.append(url) or b"unexpected",
                                 sleep=lambda _: None, storage_root=storage)
            self.assertEqual(calls, [])

    def test_second_failure_resumes_first_without_refetch_or_rewrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "run"
            materials = root / "materials"
            calls = []

            def failing_fetch(url):
                calls.append(url)
                if url == URLS[1]:
                    raise OSError("temporary failure")
                return html("53", "研究開発の法案53")

            with self.assertRaises(OSError):
                fetch_bill_pages(URLS[:2], output, as_of="2026-09-24",
                                 fetch_bytes=failing_fetch, sleep=lambda _: None,
                                 storage_root=materials)
            self.assertEqual(calls, [URLS[0], URLS[1], URLS[1], URLS[1]])
            first_record = next((materials / "bill-221-53").glob("*/record.json"))
            record = json.loads(first_record.read_text(encoding="utf-8"))
            original = first_record.parent / record["saved_filename"]
            stage = next((output / "source" / "bills").glob("*.html"))
            preserved = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                         for path in (first_record, original, stage)}
            calls.clear()
            result = fetch_bill_pages(URLS[:2], output, as_of="2026-09-24",
                                      fetch_bytes=lambda url: calls.append(url) or html("41", "研究開発の法案41"),
                                      sleep=lambda _: None, storage_root=materials)
            self.assertEqual(calls, [URLS[1]])
            for path, before in preserved.items():
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            self.assertEqual(result["coverage"]["sourceRecords"], 2)
            self.assertEqual(result["held"][0]["observedAt"], record["observed_at"])
            self.assertEqual(result["held"][0]["sha256"], record["sha256"])

    def test_three_official_bills_are_archived_and_held_without_score(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storage = root / "canonical-external-materials"
            responses = {url: html(number, f"研究開発の法案{number}")
                         for url, number in zip(URLS, ("53", "41", "26"))}
            result = fetch_bill_pages(URLS, root / "mvp-output", as_of="2026-09-24",
                                      fetch_bytes=responses.__getitem__, sleep=lambda _: None,
                                      storage_root=storage)
            self.assertEqual(result["coverage"]["candidatePolicies"], 3)
            self.assertEqual(result["coverage"]["assessedPeople"], 0)
            self.assertEqual(result["policies"], [])
            self.assertEqual([item["reason"] for item in result["held"]], ["impact_unverified"] * 3)
            self.assertEqual([item["billId"] for item in result["held"]],
                             ["221-53", "221-41", "221-26"])
            records = list(storage.glob("bill-*/**/record.json"))
            self.assertEqual(len(records), 3)
            self.assertEqual(list((root / "mvp-output").glob("external-materials/**/record.json")), [])
            by_task = {
                json.loads(path.read_text(encoding="utf-8"))["task_id"]: path
                for path in records
            }
            for item in result["held"]:
                record = json.loads(by_task[f"bill-{item['billId']}"].read_text(encoding="utf-8"))
                self.assertEqual(item["observedAt"], record["observed_at"])
                # asOf は評価基準日。観測時刻はタイムゾーン付き日時として保持する。
                parsed = datetime.fromisoformat(item["observedAt"])
                self.assertIsNotNone(parsed.tzinfo)
                self.assertIsNotNone(parsed.utcoffset())
            self.assertTrue(all(item["voteUrl"].startswith("https://www.sangiin.go.jp/")
                                for item in result["held"]))
            replay = fetch_bill_pages(URLS, root / "mvp-output", as_of="2026-09-24",
                                      fetch_bytes=responses.__getitem__, sleep=lambda _: None,
                                      storage_root=storage)
            self.assertEqual(replay, result)
            self.assertEqual(len(list(storage.glob("bill-*/**/record.json"))), 3)

    def test_invalid_registered_bill_is_rejected_without_refetch(self):
        for field in ("bytes", "observed_at", "original"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                output = root / "run"
                storage = root / "materials"
                fetch_bill_pages([URLS[0]], output, as_of="2026-09-24",
                                 fetch_bytes=lambda _: html("53", "研究開発の法案53"),
                                 sleep=lambda _: None, storage_root=storage)
                record_path = next((storage / "bill-221-53").glob("*/record.json"))
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if field == "original":
                    (record_path.parent / record["saved_filename"]).write_bytes(b"corrupt")
                else:
                    record.pop(field)
                    record_path.write_text(json.dumps(record), encoding="utf-8")
                calls = []
                with self.assertRaisesRegex(ValueError, "registration is invalid"):
                    fetch_bill_pages([URLS[0]], output, as_of="2026-09-24",
                                     fetch_bytes=lambda url: calls.append(url) or b"unexpected",
                                     sleep=lambda _: None, storage_root=storage)
                self.assertEqual(calls, [])

    def test_title_number_or_date_mismatch_is_rejected(self):
        for bad in (html("53", ""), html("41", "研究開発の法案53"),
                    "<html><table><tr><th>件名</th><td>x</td></tr></table></html>".encode("utf-8")):
            with self.subTest(bad=bad[:30]), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with self.assertRaises(ValueError):
                    fetch_bill_pages([URLS[0]], root / "out", as_of="2026-09-24",
                                     fetch_bytes=lambda _: bad, sleep=lambda _: None,
                                     storage_root=root / "storage")

    def test_official_url_scope_and_size_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for urls in (["https://example.com/bill.htm"], URLS + URLS[:1]):
                with self.subTest(urls=urls), self.assertRaises(ValueError):
                    fetch_bill_pages(urls, root / "out", as_of="2026-09-24",
                                     fetch_bytes=lambda _: html("53", "研究開発の法案53"),
                                     sleep=lambda _: None, storage_root=root / "storage")

    def test_parser_extracts_only_bounded_fields(self):
        parsed = parse_bill_page(html("53", "研究開発の法案53"), URLS[0])
        self.assertEqual(parsed["title"], "研究開発の法案53")
        self.assertEqual(parsed["submittedAt"], "2026-03-14")
        self.assertEqual(parsed["billId"], "221-53")
        self.assertEqual(parsed["voteUrl"], "https://www.sangiin.go.jp/japanese/joho1/kousei/vote/221/v53.htm")

    def test_senate_vote_link_survives_later_house_vote_method_row(self):
        page = html("53", "研究開発の法案53").decode("utf-8")
        page = page.replace("</table>", "<tr><th>採決方法</th><td>起立</td></tr></table>")
        parsed = parse_bill_page(page.encode("utf-8"), URLS[0])
        self.assertEqual(parsed["voteUrl"],
                         "https://www.sangiin.go.jp/japanese/joho1/kousei/vote/221/v53.htm")


if __name__ == "__main__":
    unittest.main()
