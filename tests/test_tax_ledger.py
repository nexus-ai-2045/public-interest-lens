"""税の帳簿（scripts/build_tax_ledger.py）：配布している表がいまの入力から作り直したものと一致し、乗数と向きが決まりどおりであること。"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts import build_tax_ledger as tl


class TaxLedgerTest(unittest.TestCase):
    def test_first_year(self) -> None:
        self.assertEqual(tl.first_year("2014-04-01"), 2014)
        self.assertEqual(tl.first_year("2019-10-01"), 2020)

    def test_committed_table_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out, tl.OUT = tl.OUT, Path(tmp) / "consumption-tax.csv"
            out_income, tl.OUT_INCOME = tl.OUT_INCOME, Path(tmp) / "income-corporate-tax.csv"
            try:
                tl.build()
                fresh, fresh_income = tl.OUT.read_text(encoding="utf-8"), tl.OUT_INCOME.read_text(encoding="utf-8")
            finally:
                tl.OUT, tl.OUT_INCOME = out, out_income
        self.assertEqual(out.read_text(encoding="utf-8"), fresh, "consumption-tax.csv が古い。python3 scripts/build_tax_ledger.py で作り直す")
        self.assertEqual(out_income.read_text(encoding="utf-8"), fresh_income, "income-corporate-tax.csv が古い。python3 scripts/build_tax_ledger.py で作り直す")
        with out.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            self.assertEqual(r["確かさ"], "低")
            self.assertEqual(float(r["乗数"]), tl.MULTIPLIER[int(r["何年目"])])
            # 引上げは損失、延期（避けた減少）は便益。
            self.assertEqual(int(r["額_円"]) < 0, r["種類"] == "引上げ", r)
            self.assertTrue(r["出典URL"].startswith("https://www.shugiin.go.jp/"))
        # 延期は、前の予定の1年目から新しい予定の1年目の前年までだけ数える。
        self.assertEqual([r["年"] for r in rows if r["法律ID"] == "閣法-192-3"], ["2017", "2018", "2019"])
        self.assertEqual([r["年"] for r in rows if r["法律ID"] == "閣法-189-3"], ["2016"])


    def test_income_corporate(self) -> None:
        with tl.OUT_INCOME.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(rows)
        for r in rows:
            kind = tl.TAX_KIND[r["税目"]]
            self.assertEqual(float(r["乗数"]), tl.CUT_MULTIPLIER[kind][int(r["何年目"])])
            # 減収（減税）は便益、増収（増税）は損失。
            self.assertEqual(int(r["額_円"]) > 0, int(r["増減収_平年度_億円"]) < 0, r)
            self.assertEqual(r["法律ID"], tl.REFORM_LAW[int(r["年"]) - int(r["何年目"]) + 1])
            self.assertTrue(r["出典URL"].startswith("https://www.mof.go.jp/") or r["出典URL"].startswith("https://www.cao.go.jp/"), r["出典URL"])
            self.assertTrue(r["外部資料ID"])
        # 一度きりの定額減税は1年目だけ。
        self.assertEqual([r["何年目"] for r in rows if r["法律ID"] == "閣法-213-1" and r["税目"] == "個人所得課税"], ["1"])

    def test_parse_revenue_table(self) -> None:
        from scripts import fetch_tax_revenue_estimates as fe
        text = """令和6年度の税制改正（内国税関係）による増減収見込額
１．個人所得課税
  定額減税                                ▲ 23,000     ▲ 23,000
  住宅ローン控除の拡充                       ▲ 330        ▲ 50
    個人所得課税 計                         ▲ 23,330    ▲ 23,050
２．法人課税
  研究開発税制の見直し                        ▲ 40        ▲ 30
                    合           計          ▲ 23,370    ▲ 23,080
令和６年度の税制改正（地方税関係）による増減収見込額
"""
        got = fe.parse(text)
        self.assertEqual([(r["税目"], r["平年度_億円"], r["決め方"]) for r in got],
                         [("個人所得課税", -23330, "計の行"), ("法人課税", -40, "改正事項が1行")])


if __name__ == "__main__":
    unittest.main()
