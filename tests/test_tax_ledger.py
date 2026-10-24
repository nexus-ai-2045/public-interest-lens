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
            try:
                tl.build()
                fresh = tl.OUT.read_text(encoding="utf-8")
            finally:
                tl.OUT = out
        self.assertEqual(out.read_text(encoding="utf-8"), fresh, "consumption-tax.csv が古い。python3 scripts/build_tax_ledger.py で作り直す")
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


if __name__ == "__main__":
    unittest.main()
