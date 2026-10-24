"""参議院投票取得の有限範囲と失敗時の原本保全。"""

import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.fetch_sangiin_votes import (
    CANONICAL,
    _default_fetch,
    collect_votes,
    parse_vote_page,
)


TITLES = {
    "221-53": "架空の行政法案",
    "221-41": "架空の科学法案",
    "221-26": "架空の産業法案",
}


def fixture(bill_id="221-53", *, yes=2, no=1, rows=True, date_text=None):
    slug = CANONICAL[bill_id].rsplit("/", 1)[-1]
    date_text = date_text or f"2026年 {int(slug[4:6])}月 {int(slug[6:8])}日"
    members = (
        (
            "<li class='giin'><span class='pros'>賛成</span><span class='cons'></span>"
            "<span class='names'>架空一郎</span></li>"
            "<li class='giin'><span class='pros'>賛成</span><span class='cons'></span>"
            "<span class='names'>架空二郎</span></li>"
            "<li class='giin'><span class='pros'></span><span class='cons'>反対</span>"
            "<span class='names'>架空三郎</span></li>"
            "<li class='giin'><span class='novote'><span>投票</span><span>なし</span></span>"
            "<span class='names'>架空四郎</span></li>"
        )
        if rows
        else ""
    )
    return (
        f"<html><meta charset='utf-8'><h2 class='kaiji_nichiji'>第221回国会<br>{date_text}</h2>"
        f"<dl class='ankenmei'><dt>案件名：</dt><dd>日程第一　{TITLES[bill_id]}（内閣提出）</dd></dl>"
        f"<h3 class='tohyosousu'>投票総数 {yes+no}<br><span>賛成票 {yes}　反対票 {no}</span></h3>"
        f"<h4 class='party'>架空会派(4名)</h4><dl class='sanpilist'>"
        f"<dt class='party'>賛成票 2　反対票 1</dt><dd><ul>{members}</ul></dd></dl>"
        "</html>"
    ).encode("utf-8")


def legacy_fixture():
    title = "架空の情報処理法案"
    return (
        "<html><meta charset='utf-8'>第200回国会 2019年 11月 29日"
        f"<table><tr><th>案件名：</th><td>日程第４　{title}（内閣提出）</td></tr></table>"
        "<p>投票総数 2　賛成票 1　反対票 1</p>"
        "<table><caption class='party'>架空会派(3名)<br>賛成票 1　反対票 1</caption>"
        "<tr><td class='pro'><img src='../images/sansei.jpg' alt='票'></td>"
        "<td class='con'>　</td><td class='nam'>架空一郎</td>"
        "<td class='pro'>　</td><td class='con'><img src='../images/hantai.jpg' alt='票'></td>"
        "<td class='nam'>架空二郎</td>"
        "<td class='pro'>　</td><td class='con'>　</td>"
        "<td class='nam'><img src='../images/spacer.gif' alt='投票なし'>架空三郎</td></tr>"
        "</table></html>"
    ).encode("utf-8"), title


class VotesTests(unittest.TestCase):
    def test_legacy_table_keeps_every_position_and_rejects_changed_mark(self):
        payload, title = legacy_fixture()
        result = parse_vote_page(
            payload, bill_id="200-8", title=title, url=CANONICAL["200-8"]
        )
        self.assertTrue(result["allPublishedRowsConfirmed"])
        self.assertEqual(result["rowCounts"], {"yes": 1, "no": 1, "noVote": 1})
        self.assertEqual(
            [row["voteText"] for row in result["rows"]],
            ["賛成", "反対", "投票なし"],
        )
        self.assertEqual(result["rows"][0]["rowText"], "架空一郎")
        self.assertNotIn("賛成", result["rows"][0]["rowText"])
        with self.assertRaises(ValueError):
            parse_vote_page(
                payload.replace(b"sansei.jpg", b"other.jpg"),
                bill_id="200-8",
                title=title,
                url=CANONICAL["200-8"],
            )
        with self.assertRaises(ValueError):
            parse_vote_page(
                payload.replace(b"spacer.gif", b"unknown.jpg"),
                bill_id="200-8",
                title=title,
                url=CANONICAL["200-8"],
            )
        with self.assertRaises(ValueError):
            parse_vote_page(
                payload.replace(
                    "sansei.jpg' alt='票'>".encode(),
                    "sansei.jpg' alt='票'><img src='unknown.jpg' alt='票'>".encode(),
                    1,
                ),
                bill_id="200-8",
                title=title,
                url=CANONICAL["200-8"],
            )
        with self.assertRaises(ValueError):
            parse_vote_page(
                payload,
                bill_id="200-8",
                title=title[2:7],
                url=CANONICAL["200-8"],
            )
        extra = (
            "<tr><td class='pro'>UNKNOWN MARK</td><td class='con'>　</td>"
            "<td class='nam'>　</td></tr></table></html>"
        ).encode()
        with self.assertRaises(ValueError):
            parse_vote_page(
                payload.replace(b"</table></html>", extra),
                bill_id="200-8",
                title=title,
                url=CANONICAL["200-8"],
            )

    def test_partial_title_does_not_identify_the_official_bill(self):
        with self.assertRaises(ValueError):
            parse_vote_page(
                fixture(), bill_id="221-53", title="行政", url=CANONICAL["221-53"]
            )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        local = Path(self.tmp.name) / ".local"
        self.source = local / "mvp" / "bills"
        self.output = local / "diet" / "votes"
        self.material = local / "external-materials"
        self.source.mkdir(parents=True)
        self.source.joinpath("current.json").write_text(
            json.dumps(
                {
                    "asOf": "2026-09-24",
                    "held": [
                        {
                            "billId": bill,
                            "title": title,
                            "voteUrl": url.replace(
                                "/touhyoulist/", "/joho1/kousei/vote/"
                            ),
                        }
                        for bill, title in TITLES.items()
                        for url in [CANONICAL[bill]]
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def run_collect(self, urls=None, fetch=None, sleep=None):
        return collect_votes(
            urls or [CANONICAL["221-53"]],
            source_root=self.source,
            output_dir=self.output,
            material_root=self.material,
            run_id="test-run",
            fetch_bytes=fetch or (lambda url: fixture()),
            sleep=sleep or (lambda seconds: None),
            clock=lambda: datetime(2026, 9, 30, tzinfo=timezone.utc),
        )

    def test_single_success_and_literal_rows_are_private(self):
        result = self.run_collect()
        self.assertEqual(
            (
                result["sourceRecords"],
                result["structuredAvailable"],
                result["confirmedActionEvidence"],
            ),
            (1, 1, 0),
        )
        item = json.loads((self.output / "221-53.json").read_text(encoding="utf-8"))
        self.assertEqual(item["rowCounts"], {"yes": 2, "no": 1, "noVote": 1})
        self.assertEqual(
            [row["voteText"] for row in item["rows"]],
            ["賛成", "賛成", "反対", "投票なし"],
        )
        self.assertEqual(item["factions"][0]["partyText"], "架空会派(4名)")
        self.assertIn("賛成票 2", item["rows"][0]["partyPublishedCountText"])
        self.assertTrue(all(row["sourceLine"] > 0 for row in item["rows"]))
        self.assertEqual(item["contentVerification"], "unverified")
        self.assertEqual(len(list(self.material.rglob("record.json"))), 1)
        self.assertNotIn("架空一郎", json.dumps(result, ensure_ascii=False))

    def test_three_urls_maximum_duplicate_and_official_scope(self):
        urls = [CANONICAL[bill] for bill in TITLES]
        result = self.run_collect(
            urls, fetch=lambda url: fixture({v: k for k, v in CANONICAL.items()}[url])
        )
        self.assertEqual(result["structuredAvailable"], 3)
        for invalid in (
            urls + urls[:1],
            [urls[0], urls[0]],
            [urls[0].replace("www.sangiin.go.jp", "example.com")],
            [urls[0].replace("/touhyoulist/", "/joho1/kousei/vote/")],
            [urls[0] + "?x=1"],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.run_collect(invalid)

    def test_network_failure_retries_three_times_and_preserves_completed_target(self):
        calls = []
        urls = [CANONICAL[bill] for bill in TITLES][:2]

        def broken(url):
            calls.append(url)
            if url == urls[1]:
                raise OSError("network")
            return fixture()

        with self.assertRaises(OSError):
            self.run_collect(urls, fetch=broken)
        self.assertEqual(calls, [urls[0], urls[1], urls[1], urls[1]])
        record = next(self.material.rglob("record.json"))
        before = record.stat().st_mtime_ns
        calls.clear()
        self.run_collect(urls, fetch=lambda url: calls.append(url) or fixture("221-41"))
        self.assertEqual(calls, [urls[1]])
        self.assertEqual(record.stat().st_mtime_ns, before)

    def test_empty_rows_or_mismatch_never_claims_available(self):
        for payload in (
            fixture(rows=False),
            fixture(yes=3, no=1),
            fixture().replace(b"class='names'", b"class='other'", 1),
        ):
            with self.subTest(payload=payload[-80:]):
                parsed = parse_vote_page(
                    payload,
                    bill_id="221-53",
                    title=TITLES["221-53"],
                    url=CANONICAL["221-53"],
                )
                self.assertFalse(parsed["available"])
                self.assertFalse(parsed.get("allPublishedRowsConfirmed", True))

    def test_nonvoting_rows_require_complete_published_faction_membership(self):
        base = fixture().decode()
        last = base.index("<li class='giin'><span class='novote'>")
        end = base.index("</li>", last) + len("</li>")
        for broken in (
            base[:last] + base[end:],
            base[:end] + base[last:end] + base[end:],
            base.replace("(4名)", ""),
            base.replace("架空二郎", "架空一郎"),
        ):
            with self.subTest(broken=broken[-150:]):
                result = parse_vote_page(
                    broken.encode(),
                    bill_id="221-53",
                    title=TITLES["221-53"],
                    url=CANONICAL["221-53"],
                )
                self.assertFalse(result["available"])
                self.assertFalse(result.get("allPublishedRowsConfirmed", True))

    def test_unknown_rows_preserve_valid_rows_and_raw_diagnostics(self):
        payload = fixture().replace("架空四郎".encode(), b"")
        result = parse_vote_page(
            payload, bill_id="221-53", title=TITLES["221-53"], url=CANONICAL["221-53"]
        )
        self.assertFalse(result["available"])
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(len(result.get("diagnosticRows", [])), 1)

    def test_record_path_checked_before_any_read(self):
        from scripts.fetch_sangiin_votes import _registered

        outside = Path(self.tmp.name) / "record.json"
        outside.write_text("{}", encoding="utf-8")
        with patch.object(
            Path, "read_text", side_effect=AssertionError("read before containment")
        ):
            with self.assertRaises(ValueError):
                _registered(outside, self.material, CANONICAL["221-53"])

    def test_symlink_record_escape_rejected_before_read(self):
        from scripts.fetch_sangiin_votes import _registered

        outside = Path(self.tmp.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        self.material.mkdir(parents=True)
        linked = self.material / "linked.json"
        try:
            linked.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation unavailable on this host")
        with patch.object(
            Path, "read_text", side_effect=AssertionError("read before containment")
        ):
            with self.assertRaises(ValueError):
                _registered(linked, self.material, CANONICAL["221-53"])

    def test_conflicting_mark_preserved_only_as_diagnostic(self):
        payload = fixture().replace(
            b"class='cons'></span>", "class='cons'>反対</span>".encode(), 1
        )
        result = parse_vote_page(
            payload, bill_id="221-53", title=TITLES["221-53"], url=CANONICAL["221-53"]
        )
        self.assertFalse(result["available"])
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(len(result["diagnosticRows"]), 1)

    def test_unrecognized_mark_cannot_hide_beside_known_vote(self):
        payload = fixture().replace(
            b"class='cons'></span>", "class='cons'>不明</span>".encode(), 1
        )
        result = parse_vote_page(
            payload, bill_id="221-53", title=TITLES["221-53"], url=CANONICAL["221-53"]
        )
        self.assertFalse(result["available"])
        self.assertEqual(len(result["diagnosticRows"]), 1)

    def test_faction_counts_mismatch_without_changing_global_counts(self):
        payload = (
            fixture()
            .decode()
            .replace("<dt class='party'>賛成票 2", "<dt class='party'>賛成票 1")
            .encode()
        )
        result = parse_vote_page(
            payload, bill_id="221-53", title=TITLES["221-53"], url=CANONICAL["221-53"]
        )
        self.assertTrue(result["voteCountMatched"])
        self.assertFalse(result["allPublishedRowsConfirmed"])
        self.assertFalse(result["available"])

    def test_offline_registered_reuse_without_new_artifact(self):
        from scripts import fetch_sangiin_votes as votes

        self.run_collect()
        record = next(self.material.rglob("record.json"))
        before = sorted(str(p) for p in Path(self.tmp.name).rglob("*"))
        self.assertTrue(hasattr(votes, "read_registered_votes"))
        result = votes.read_registered_votes(
            record,
            material_root=self.material,
            bill_id="221-53",
            title=TITLES["221-53"],
            url=CANONICAL["221-53"],
            as_of="2026-09-24",
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["confirmedActionEvidence"], 0)
        self.assertEqual(before, sorted(str(p) for p in Path(self.tmp.name).rglob("*")))

    def test_date_title_and_published_totals_are_fail_closed(self):
        base = fixture()
        for payload in (
            fixture(date_text="2026年 7月 9日"),
            base.replace("架空の行政法案".encode(), "別法案".encode()),
            base.replace("反対票 1".encode(), "反対票 2".encode()).replace(
                "投票総数 3".encode(), "投票総数 3".encode()
            ),
        ):
            with self.subTest(payload=payload[:100]), self.assertRaises(ValueError):
                parse_vote_page(
                    payload,
                    bill_id="221-53",
                    title=TITLES["221-53"],
                    url=CANONICAL["221-53"],
                )

    def test_hash_tampering_stops_without_refetch(self):
        self.run_collect()
        original = next(self.material.rglob("original.html"))
        original.write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.run_collect(fetch=lambda url: self.fail("network must not be called"))

    def test_noncommunication_failure_not_retried_and_original_preserved(self):
        calls = []
        with self.assertRaises(ValueError):
            self.run_collect(
                fetch=lambda url: calls.append(url)
                or fixture(date_text="2026年 7月 9日")
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(list(self.material.rglob("original.html"))), 1)
        self.assertFalse((self.output / "221-53.json").exists())
        with self.assertRaises(ValueError):
            self.run_collect(
                fetch=lambda url: self.fail("must preserve failed registered attempt")
            )

    def test_missing_event_date_and_out_of_scope_are_not_available(self):
        with self.assertRaises(ValueError):
            self.run_collect(fetch=lambda url: fixture(date_text="日付不明"))
        self.assertEqual(len(list(self.material.rglob("original.html"))), 1)
        (self.output / "221-53.json").unlink(missing_ok=True)
        # 別runにして過去の失敗原本には触れない。
        source_file = self.source / "current.json"
        source = json.loads(source_file.read_text(encoding="utf-8"))
        source["asOf"] = "2025-09-24"
        source_file.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            collect_votes(
                [CANONICAL["221-53"]],
                source_root=self.source,
                output_dir=self.output / "new-run",
                material_root=self.material,
                run_id="other-run",
                fetch_bytes=lambda url: fixture(),
                sleep=lambda _: None,
                clock=lambda: datetime(2026, 9, 30, tzinfo=timezone.utc),
            )

    def test_partial_registration_is_preserved_without_refetch(self):
        partial = self.material / "diet-vote-221-53-test-run" / "2026-09-30-partial"
        partial.mkdir(parents=True)
        partial.joinpath("original.html").write_bytes(b"partial")
        with self.assertRaises(ValueError):
            self.run_collect(
                fetch=lambda url: self.fail("must not refetch unknown partial")
            )
        self.assertEqual(partial.joinpath("original.html").read_bytes(), b"partial")

    def test_http_404_is_nonretryable_failure(self):
        class Opener:
            def open(self, request, timeout):
                raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)

        with patch(
            "scripts.fetch_sangiin_votes.urllib.request.build_opener",
            return_value=Opener(),
        ):
            with self.assertRaises(ValueError):
                _default_fetch(CANONICAL["221-53"])

    def test_second_request_waits_at_least_three_seconds(self):
        waits = []
        urls = [CANONICAL[bill] for bill in TITLES][:2]
        with patch(
            "scripts.fetch_sangiin_votes.time.monotonic",
            side_effect=[10.0, 10.05, 13.0],
        ):
            self.run_collect(
                urls,
                fetch=lambda url: fixture({v: k for k, v in CANONICAL.items()}[url]),
                sleep=waits.append,
            )
        self.assertEqual(len(waits), 1)
        self.assertGreater(waits[0], 2.9)

    def test_later_invalid_page_keeps_last_good_manifest_and_checkpoint(self):
        first = CANONICAL["221-53"]
        second = CANONICAL["221-41"]
        self.run_collect([first])
        manifest = (self.output / "manifest.json").read_bytes()
        checkpoint = (self.output / "221-53.json").read_bytes()
        with self.assertRaises(ValueError):
            self.run_collect(
                [first, second],
                fetch=lambda url: fixture("221-41", date_text="日付不明"),
            )
        self.assertEqual((self.output / "manifest.json").read_bytes(), manifest)
        self.assertEqual((self.output / "221-53.json").read_bytes(), checkpoint)
        self.assertFalse((self.output / "221-41.json").exists())
        self.assertEqual(len(list(self.material.rglob("original.html"))), 2)


if __name__ == "__main__":
    unittest.main()
