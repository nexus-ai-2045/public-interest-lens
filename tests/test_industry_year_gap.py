import csv
import io
import unittest
from pathlib import Path

from scripts import build_industry_year_gap as g

OUT = g.OUT


def synthetic_oecd(lr: dict[str, dict[int, float]], nominal: dict[int, float], industry: str = "X") -> g.Oecd:
    """国ごとの LR（年→値）と日本の名目 V だけを持つ小さな合成データ（ファイルは読まない）。"""
    oecd = g.Oecd(Path("/nonexistent/industry_va.csv"))
    for country, series in lr.items():
        oecd.series[(country, industry, "LR")] = dict(series)
    oecd.series[("JPN", industry, "V")] = dict(nominal)
    return oecd


# 比較国 A・B・C の 2000→2001 の伸び率は 1.05・1.06・1.07（中央値1.06、第1四分位1.055、第3四分位1.065）。
COMPARATORS = {"AAA": {2000: 100.0, 2001: 105.0}, "BBB": {2000: 100.0, 2001: 106.0}, "CCC": {2000: 100.0, 2001: 107.0}}


class IndustryYearGapTests(unittest.TestCase):
    def test_committed_csv_matches_regeneration(self):
        rows, _ = g.build(g.Oecd(g.OECD), g.covered_years(g.MACRO))
        self.assertEqual(OUT.read_text(encoding="utf-8"), g.render(rows))

    def test_low_median_high_ordered(self):
        rows = list(csv.DictReader(io.StringIO(OUT.read_text(encoding="utf-8"))))
        self.assertGreater(len(rows), 100)
        for r in rows:
            self.assertLessEqual(int(r["low"]), int(r["median"]), r)
            self.assertLessEqual(int(r["median"]), int(r["high"]), r)
            self.assertGreaterEqual(len(r["比較国"].split("・")), g.MIN_COUNTRIES)

    def test_no_duplicate_industry_year(self):
        rows = list(csv.DictReader(io.StringIO(OUT.read_text(encoding="utf-8"))))
        keys = [(r["産業"], r["年"]) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertNotIn("COVID", {r["産業"] for r in rows})


class BuildTests(unittest.TestCase):
    def test_sign_is_comparators_minus_japan_and_uses_previous_year_nominal(self):
        # 日本は 100→102（伸び率1.02）で、比較国の中央値1.06より伸びていない：正（伸び損ね）。
        oecd = synthetic_oecd({"JPN": {2000: 100.0, 2001: 102.0}, **COMPARATORS}, {2000: 500.0, 2001: 900.0})
        rows, skipped = g.build(oecd, {"X": {2001}})
        self.assertEqual(skipped, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # 名目は前年（2000年）の500百万円。当年の900ではない。
        self.assertEqual(row["前年の名目付加価値_百万円"], "500")
        self.assertAlmostEqual(int(row["median"]), (1.06 - 1.02) * 500 * 1_000_000, delta=1)
        self.assertAlmostEqual(int(row["low"]), (1.055 - 1.02) * 500 * 1_000_000, delta=1)
        self.assertAlmostEqual(int(row["high"]), (1.065 - 1.02) * 500 * 1_000_000, delta=1)
        self.assertGreater(int(row["median"]), 0)
        self.assertEqual(row["比較国"], "AAA・BBB・CCC")

    def test_negative_when_japan_grew_more_than_comparators(self):
        oecd = synthetic_oecd({"JPN": {2000: 100.0, 2001: 110.0}, **COMPARATORS}, {2000: 500.0})
        rows, _ = g.build(oecd, {"X": {2001}})
        self.assertLess(int(rows[0]["median"]), 0)
        self.assertAlmostEqual(int(rows[0]["median"]), (1.06 - 1.10) * 500 * 1_000_000, delta=1)

    def test_skips_year_without_previous_year(self):
        # 日本に1999年が無いので2000年は行を作らない。名目の前年が無い2001年（V は 2000 が無い）も作らない。
        oecd = synthetic_oecd({"JPN": {2000: 100.0, 2001: 102.0}, **COMPARATORS}, {2001: 900.0})
        rows, skipped = g.build(oecd, {"X": {2000, 2001}})
        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 2)
        self.assertTrue(all("日本の LR か前年の名目付加価値が無い" in s for s in skipped))

    def test_skips_year_with_fewer_than_three_comparators(self):
        two = {k: v for k, v in COMPARATORS.items() if k != "CCC"}
        oecd = synthetic_oecd({"JPN": {2000: 100.0, 2001: 102.0}, **two}, {2000: 500.0})
        rows, skipped = g.build(oecd, {"X": {2001}})
        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("2か国", skipped[0])

    def test_skips_year_when_japan_previous_lr_is_not_positive(self):
        for prev in (0.0, -5.0):
            oecd = synthetic_oecd({"JPN": {2000: prev, 2001: 102.0}, **COMPARATORS}, {2000: 500.0})
            rows, skipped = g.build(oecd, {"X": {2001}})
            self.assertEqual(rows, [], prev)
            self.assertEqual(len(skipped), 1)
            self.assertIn("0以下", skipped[0])


if __name__ == "__main__":
    unittest.main()
