"""経済界の帳簿（scripts/build_business_ledger.py）：表がいまの入力から作り直したものと一致し、個人を名指しせず、結ぶ範囲が約束どおりであること。"""
from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import build_business_ledger as bl


class BusinessLedgerTest(unittest.TestCase):
    def test_request_date_prefers_receipt_number(self) -> None:
        self.assertEqual(bl.request_date("290608002", "平成29年6月8日"), ("2017-06-08", "受付番号"))
        self.assertEqual(bl.request_date("280720003", "平成27年11月2日（推定）"), ("2016-07-20", "受付番号"))
        self.assertEqual(bl.request_date("x", "2014-04-25"), ("2014-04-25", "受付日"))
        self.assertEqual(bl.request_date("x", "3月22日（年の記載なし）"), ("", ""))

    def test_statutes(self) -> None:
        self.assertEqual(bl.statutes("銀行法第10条第2項、金融機関の信託業務の兼営等に関する法律第1条"), ["銀行法", "金融機関の信託業務の兼営等に関する法律"])
        self.assertEqual(bl.statutes("信託業法施行令第1条の2"), [])
        self.assertEqual(bl.statutes("独占禁止法第3条"), ["私的独占の禁止及び公正取引の確保に関する法律"])
        self.assertEqual(bl.statutes("医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律第77条の2"),
                         ["医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律"])
        self.assertEqual(bl.statutes("記載なし"), [])

    def test_title_has_rejects_longer_law_names(self) -> None:
        self.assertTrue(bl.title_has("銀行法等の一部を改正する法律案", "銀行法"))
        self.assertTrue(bl.title_has("信託業法、銀行法の一部を改正する法律案", "銀行法"))
        self.assertTrue(bl.title_has("医療法及び医師法の一部を改正する法律案", "医師法"))
        self.assertFalse(bl.title_has("日本銀行法の一部を改正する法律案", "銀行法"))

    def test_proposer_kinds(self) -> None:
        self.assertEqual(bl.proposer_kind("個人"), ("（個人・名前は出さない）", "個人"))
        self.assertEqual(bl.proposer_kind("日本商工会議所")[1], "経済団体")
        self.assertEqual(bl.proposer_kind("（一社）日本フランチャイズチェーン協会")[1], "業界団体")

    def test_committed_tables_are_current(self) -> None:
        names = ("requests.csv", "chain.csv", "by-proposer.csv", "summary.json")
        committed = {n: (bl.OUT_DIR / n).read_text(encoding="utf-8") for n in names}
        with tempfile.TemporaryDirectory() as tmp:
            saved = bl.OUT_DIR
            bl.OUT_DIR = Path(tmp)
            try:
                bl.build()
                fresh = {n: (bl.OUT_DIR / n).read_text(encoding="utf-8") for n in names}
            finally:
                bl.OUT_DIR = saved
        self.assertEqual(committed, fresh, "business-ledger-v1 の表が古い。python3 scripts/build_business_ledger.py で作り直す")

    def test_chain_only_links_within_window_and_after_request(self) -> None:
        reqs = {r["要望ID"]: r for r in csv.DictReader((bl.OUT_DIR / "requests.csv").open(encoding="utf-8", newline=""))}
        rows = list(csv.DictReader((bl.OUT_DIR / "chain.csv").open(encoding="utf-8", newline="")))
        self.assertTrue(rows)
        for c in rows:
            days = (date.fromisoformat(c["公布日"]) - date.fromisoformat(reqs[c["要望ID"]]["受付日"])).days
            self.assertTrue(0 < days <= bl.WINDOW_DAYS, c)
            self.assertIn("要望が原因とは読まない", c["対応の確かさ"])

    def test_amounts_are_not_truncated(self) -> None:
        for c in csv.DictReader((bl.OUT_DIR / "chain.csv").open(encoding="utf-8", newline="")):
            if c["額の表示"].startswith(("損失", "便益")):
                self.assertIn("第3四分位=", c["額の表示"], c)
                self.assertRegex(c["額の表示"], r"第3四分位=-?\d{10,}$|第3四分位=-?\d+", c)

    def test_individuals_are_not_named(self) -> None:
        for name in ("requests.csv", "by-proposer.csv"):
            for r in csv.DictReader((bl.OUT_DIR / name).open(encoding="utf-8", newline="")):
                if r["区分"] in ("個人", "民間企業", "民間団体"):
                    self.assertIn("名前は出さない", r["提案主体"], r)


if __name__ == "__main__":
    unittest.main()
