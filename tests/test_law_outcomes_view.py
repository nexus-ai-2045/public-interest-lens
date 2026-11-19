"""/history の法律の結果一覧（law-outcomes.json）が、額と向きを公開ランキング（ranking.json）に合わせているか。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import build_law_outcomes_view as view
from scripts.build_public_ranking import direction_undetermined

ROOT = Path(__file__).resolve().parents[1]
RANKING = ROOT / "app" / "public" / "distribution" / "ranking.json"


class LawOutcomesViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.items = view.build()["items"]
        cls.ranking = {law["id"]: law for law in json.loads(RANKING.read_text(encoding="utf-8"))["laws"]}

    def test_amounts_only_where_public_ranking_has_one(self) -> None:
        """公開ランキングが1本ごとの額を出さない法律（共有額の参考など）は、ここでも額を出さず理由を付ける。"""
        for item in self.items:
            if item["median"] is not None:
                law = self.ranking[item["id"]]
                self.assertEqual(item["median"], law["amountMedianYen"], item["id"])
            if item.get("amountWithheld"):
                self.assertIsNone(item["median"], item["id"])
                self.assertNotIn(item["id"], self.ranking)

    def test_undetermined_direction_is_not_split_into_sides(self) -> None:
        """向き未確定の印がある法律は side を undetermined にする（国賊側・国士側に分けない）。"""
        for item in self.items:
            if item["median"] is None:
                continue
            law = self.ranking[item["id"]]
            expected = "undetermined" if direction_undetermined(law["notes"]) else law["side"]
            self.assertEqual(item["side"], expected, item["id"])


if __name__ == "__main__":
    unittest.main()
