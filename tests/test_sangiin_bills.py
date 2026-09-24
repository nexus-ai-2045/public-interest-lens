"""参議院の限定法案ページ取得から保留データを作る契約。"""

import tempfile
import unittest
from pathlib import Path

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
    def test_three_official_bills_are_archived_and_held_without_score(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            responses = {url: html(number, f"研究開発の法案{number}")
                         for url, number in zip(URLS, ("53", "41", "26"))}
            result = fetch_bill_pages(URLS, root, as_of="2026-09-24",
                                      fetch_bytes=responses.__getitem__, sleep=lambda _: None)
            self.assertEqual(result["coverage"]["candidatePolicies"], 3)
            self.assertEqual(result["coverage"]["assessedPeople"], 0)
            self.assertEqual(result["policies"], [])
            self.assertEqual([item["reason"] for item in result["held"]], ["impact_unverified"] * 3)
            self.assertEqual([item["billId"] for item in result["held"]],
                             ["221-53", "221-41", "221-26"])
            self.assertEqual(len(list(root.glob("external-materials/**/record.json"))), 3)
            self.assertTrue(all(item["voteUrl"].startswith("https://www.sangiin.go.jp/")
                                for item in result["held"]))
            replay = fetch_bill_pages(URLS, root, as_of="2026-09-24",
                                      fetch_bytes=responses.__getitem__, sleep=lambda _: None)
            self.assertEqual(replay, result)
            self.assertEqual(len(list(root.glob("external-materials/**/record.json"))), 3)

    def test_title_number_or_date_mismatch_is_rejected(self):
        for bad in (html("53", ""), html("41", "研究開発の法案53"),
                    "<html><table><tr><th>件名</th><td>x</td></tr></table></html>".encode("utf-8")):
            with self.subTest(bad=bad[:30]), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(ValueError):
                    fetch_bill_pages([URLS[0]], Path(temp), as_of="2026-09-24",
                                     fetch_bytes=lambda _: bad, sleep=lambda _: None)

    def test_official_url_scope_and_size_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            for urls in (["https://example.com/bill.htm"], URLS + URLS[:1]):
                with self.subTest(urls=urls), self.assertRaises(ValueError):
                    fetch_bill_pages(urls, Path(temp), as_of="2026-09-24",
                                     fetch_bytes=lambda _: html("53", "研究開発の法案53"),
                                     sleep=lambda _: None)

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
