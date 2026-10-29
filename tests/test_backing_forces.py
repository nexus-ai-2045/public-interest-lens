"""背後の力の結び付け（scripts/build_backing_forces.py、設計決定0017）：規則と、点数・個人名に触れない不変条件。"""
from __future__ import annotations

import csv
import unittest

from scripts import build_backing_forces as bf
from scripts import build_org_ledger as ledger


def law(i: str, title: str, date: str) -> dict:
    return {"id": i, "title": title, "date": date, "heads": bf.law_heads(title)}


class HeadsTest(unittest.TestCase):
    def test_heads(self) -> None:
        self.assertEqual(bf.law_heads("貸金業法の一部を改正する法律案"), ["貸金業法"])
        self.assertIn("銀行法", bf.law_heads("銀行法等の一部を改正する法律案"))
        self.assertIn("消防法", bf.law_heads("消防法及び石油コンビナート等災害防止法の一部を改正する法律案"))
        self.assertIn("住宅宿泊事業法", bf.law_heads("住宅宿泊事業法案"))
        self.assertEqual(bf.law_heads("中央省庁等改革の施行に伴う関係法律の整備等に関する法律案"), [])

    def test_dates(self) -> None:
        self.assertEqual(bf.iso_date("平成27年11月2日（推定）"), "2015-11-02")
        self.assertEqual(bf.iso_date("令和元年5月1日"), "2019-05-01")
        self.assertEqual(bf.iso_date("2014-04-25"), "2014-04-25")
        self.assertEqual(bf.iso_date(""), "")


class MatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.laws = [law("閣法-1-1", "医師法の一部を改正する法律案", "2010-01-01"), law("閣法-2-1", "歯科医師法の一部を改正する法律案", "2011-01-01"),
                     law("閣法-3-1", "医師法の一部を改正する法律案", "2020-01-01")]
        self.heads: dict = {}
        for x in self.laws:
            for h in x["heads"]:
                self.heads.setdefault(h, []).append(x)

    def test_prefix_kanji_is_not_a_match(self) -> None:
        names, _ = bf.mentioned_names("歯科医師法第17条", {"医師法"}, {})
        self.assertEqual(names, [])  # 歯科医師法の中の「医師法」を取らない

    def test_alias_and_reason(self) -> None:
        names, _ = bf.mentioned_names("薬機法（医薬品の販売制度）", {"薬事法"}, bf.load_aliases())
        self.assertIn("薬事法", names)
        self.assertEqual(bf.mentioned_names("記載なし", set(), {})[1], "法令名の記載なし")
        self.assertIn("法令名ではない", bf.mentioned_names("食品表示基準のガイドライン", {"医師法"}, {})[1])

    def test_order_only_no_window(self) -> None:
        got = dict(bf.candidate_laws("医師法", self.heads, "2015-06-01"))
        self.assertEqual(got[bf.BEFORE]["id"], "閣法-3-1")
        self.assertEqual(got[bf.AFTER]["id"], "閣法-1-1")
        self.assertEqual([p for p, _ in bf.candidate_laws("医師法", self.heads, "")], ["不明", "不明"])


class ContactsTest(unittest.TestCase):
    def test_individuals_and_unnamed_excluded(self) -> None:
        recs = [{"帳簿": "団体", "団体": "日本薬剤師会", "区分": "業界団体", "立場": "慎重", "日付": "2013-01-01", "法令": "薬事法", "技術": "ネット販売", "出典URL": "https://x/1"},
                {"帳簿": "団体", "団体": "（学者・名前は出さない）", "区分": "学者", "立場": "慎重", "日付": "2013-01-01", "法令": "薬事法", "技術": "", "出典URL": "https://x/2"}]
        laws = [law("閣法-9-9", "薬事法の一部を改正する法律案", "2013-11-20")]
        rel = [{"区分": "受けた寄附", "相手方種別": "団体", "人物ID": "P1", "団体名キー": "日本薬剤師会", "年分": "2020", "金額": "100", "PDF_URL": "https://x/p"},
               {"区分": "受けた寄附", "相手方種別": "個人", "人物ID": "P1", "団体名キー": "日本薬剤師会", "年分": "2020", "金額": "5", "PDF_URL": ""},
               {"区分": "受けた寄附", "相手方種別": "団体", "人物ID": "", "団体名キー": "日本薬剤師会", "年分": "2020", "金額": "7", "PDF_URL": ""}]
        rows = bf.build_contacts(rel, recs, laws, bf.load_aliases())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["金額の合計"], 100)
        self.assertEqual(rows[0]["関連法律ID"], "閣法-9-9")


class DistributedTablesTest(unittest.TestCase):
    def test_tables_match_inputs(self) -> None:
        self.assertEqual(bf.main(["--check"]), 0)

    def test_invariants(self) -> None:
        rows = bf.read_csv(bf.OUT_LINKS)
        self.assertTrue(rows)
        recs = [r for r in ledger.records() if not (r["帳簿"] == "省庁" and r["種類"] == "回答")]
        for r in rows:
            self.assertTrue(r["出典URL"].startswith("https://"), r)  # 出典の無い結び付けは無い
            self.assertIn(r["時期"], (bf.BEFORE, bf.AFTER, "不明"))
            self.assertGreater(int(r["件数"]), 0)
        # 個人名は出さない：団体の主体は帳簿の団体名か「（区分・名前は出さない）」だけ。
        names = {r["団体"] for r in recs if r["帳簿"] == "団体"} | {r["省庁"] for r in recs if r["帳簿"] == "省庁"}
        for r in rows:
            self.assertIn(r["主体"], names)
        # 突き合わせ：結べた＋結べない＝帳簿の記録（取りこぼしを数で見つける）。
        manifest_counts = bf.compute()["manifest"]["counts"]
        self.assertEqual(manifest_counts["結べた"] + manifest_counts["結べない"], manifest_counts["記録"])
        self.assertEqual(manifest_counts["記録"], len(recs))


if __name__ == "__main__":
    unittest.main()
