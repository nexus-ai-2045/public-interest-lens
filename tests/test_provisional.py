"""暫定評価（provisional-v1）の政策カードと、日本の法律への当て方の形を確かめる。"""
import json
import math
import unittest
from pathlib import Path

from scripts import build_provisional as bp

ROOT = Path(__file__).resolve().parents[1]


class GrowthChangeTest(unittest.TestCase):
    def test_growth_series_difference(self):
        # 開始前3年は年2%、開始後2年は年5% → 変化は log(1.05) - log(1.02)
        series = {1998: 2, 1999: 2, 2000: 2, 2001: 5, 2002: 5}
        got = bp.growth_change(series, 2000, 3, 2, "wb_growth")
        self.assertAlmostEqual(got, math.log(1.05) - math.log(1.02))

    def test_missing_year_gives_none(self):
        self.assertIsNone(bp.growth_change({1998: 2, 2000: 2}, 2000, 3, 2, "wb_growth"))

    def test_level_series_difference(self):
        series = {1997: 100, 2000: 100 * math.e ** 0.3, 2002: 100 * math.e ** 0.3 * math.e ** 0.2}
        # 開始前の年率0.1、開始後の年率0.1 → 変化0
        self.assertAlmostEqual(bp.growth_change(series, 2000, 3, 2, "oecd_real"), 0.0)


class PublishedDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "app" / "public" / "distribution" / "provisional.json").read_text())

    def test_interval_keeps_sign_and_has_no_point_estimate(self):
        for card in self.data["cards"]:
            if card["status"] == "measured":
                self.assertLessEqual(card["effect"]["low"], card["effect"]["high"])
                self.assertNotIn("median", card["effect"])
                self.assertEqual(card["spansZero"], card["effect"]["low"] < 0 < card["effect"]["high"])

    def test_counts_add_up(self):
        counts = self.data["counts"]
        self.assertEqual(counts["provisional"] + counts["unmeasured"], counts["recent"])

    def test_items_only_use_applicable_measured_cards(self):
        cards = {card["id"]: card for card in self.data["cards"]}
        for item in self.data["items"]:
            for card_id in item["cards"]:
                self.assertTrue(cards[card_id]["applicableToJapan"])
                self.assertEqual(cards[card_id]["status"], "measured")
            self.assertLessEqual(item["amount"]["low"], item["amount"]["high"])

    def test_low_income_cards_not_applied_to_japan(self):
        for card in self.data["cards"]:
            if card["country"] in ("CHN", "VNM", "IND"):
                self.assertFalse(card["applicableToJapan"])


    def test_theory_values_keep_order_and_state_backtest(self):
        theory = self.data["theory"]
        self.assertEqual(theory["backtest"]["n"], 0)
        self.assertIsNone(theory["backtest"]["coverage"])
        for item in theory["items"]:
            self.assertLessEqual(item["low_yen"], item["high_yen"])
            expected_low = sum(i["count"] * i["hours"] * i["wage_in_assessment"] for i in item["inputs"])
            self.assertEqual(item["low_yen"], expected_low)
            expected_high = sum(i["count"] * i["hours"] for i in item["inputs"]) * 2543 * 1.5
            self.assertAlmostEqual(item["high_yen"], expected_high, delta=1)


if __name__ == "__main__":
    unittest.main()
