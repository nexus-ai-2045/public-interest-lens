import csv
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_unenacted_bills_scale as m  # noqa: E402


class UnenactedScaleTest(unittest.TestCase):
    def test_guess_kind(self):
        self.assertEqual(m.guess_kind("道路法の一部を改正する法律案"), "実質改正")
        self.assertEqual(m.guess_kind("情報公開法案"), "新規")

    def test_shares_are_percent_of_total(self):
        share, year = m.shares()
        self.assertGreater(year, 2020)
        for code, v in share.items():
            self.assertTrue(0 < v < 40, (code, v))

    def test_output_has_no_enacted_and_no_amount_or_direction(self):
        m.main()
        rows = list(csv.DictReader(m.DST.open(encoding="utf-8")))
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(r["審議状況"] != "成立" for r in rows))
        for r in rows:
            if r["規模点"]:
                self.assertEqual((r["確かさ"], r["向き"]), ("参考", "不明"))


if __name__ == "__main__":
    unittest.main()
