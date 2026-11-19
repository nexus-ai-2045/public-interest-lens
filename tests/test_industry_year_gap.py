import csv
import io
import unittest

from scripts import build_industry_year_gap as g

OUT = g.OUT


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


if __name__ == "__main__":
    unittest.main()
