"""コロナ対応の費用便益（covid-benefit-v1）：支出は一次資料つきで、額は式どおりに計算し直せて、macro.csv と同じになる。"""
import csv
import unittest

from scripts import build_covid_benefit as cb
from scripts import build_macro_amounts as macro


def _read(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class CovidBenefitTest(unittest.TestCase):
    def setUp(self):
        self.spending = _read(cb.SPENDING)
        self.rules = _read(cb.RULES)
        self.saved = {r["id"]: r for r in _read(cb.OUT)}

    def test_every_spending_item_has_an_official_source_and_a_quote(self):
        self.assertTrue(self.spending)
        for r in self.spending:
            self.assertTrue(r["出典URL"].startswith("https://"), r["項目ID"])
            self.assertTrue(r["原文の抜粋"].strip(), r["項目ID"])
            self.assertIn(r["法律に直接"], ("はい", "いいえ"), r["項目ID"])

    def test_every_covid_law_has_exactly_one_rule(self):
        covid = {r["id"] for r in _read(cb.LABELS) if r["コロナ対応"] == "はい"}
        ids = [r["id"] for r in self.rules]
        self.assertEqual(len(ids), len(set(ids)))
        # 閣法-203-1 は成立法の台帳（outcomes）に無く、macro.csv の対象外。規模だけ spending.csv に残す。
        self.assertEqual(set(ids), covid - {"閣法-203-1"})

    def test_saved_output_is_what_the_rules_compute(self):
        self.assertEqual({r["id"]: r for r in cb.build()}, self.saved)

    def test_amounts_are_benefits_with_ordered_ranges_and_a_basis(self):
        amounted = [r for r in self.saved.values() if r["結果"] == "額"]
        self.assertTrue(amounted)
        for r in amounted:
            median, q1, q3 = int(r["中央値"]), int(r["第1四分位"]), int(r["第3四分位"])
            self.assertTrue(q1 <= median <= q3 < 0, r["id"])  # 負が便益（macro-v1 と同じ符号）
            self.assertTrue(r["根拠"] and r["窓"], r["id"])
        for r in self.saved.values():
            if r["結果"] == "理由":
                self.assertTrue(r["理由"] and not r["中央値"], r["id"])

    def test_macro_rows_follow_the_covid_benefit_output(self):
        rows = {r["id"]: r for r in _read(macro.OUT)}
        for law_id, r in self.saved.items():
            m = rows[law_id]
            self.assertEqual(m["結果"], r["結果"], law_id)
            if r["結果"] == "額":
                self.assertEqual((m["中央値"], m["産業"]), (r["中央値"], macro.COVID_INDUSTRY), law_id)
            else:
                self.assertEqual(m["理由"], r["理由"], law_id)

    def test_expressions_only_allow_arithmetic_on_known_items(self):
        self.assertEqual(cb.evaluate("([a#1]+[a#2])/2", {"a#1": 4, "a#2": 6}), 5)
        with self.assertRaises(ValueError):
            cb.evaluate("[x#1]", {})
        with self.assertRaises(ValueError):
            cb.evaluate("__import__('os')", {})


if __name__ == "__main__":
    unittest.main()
