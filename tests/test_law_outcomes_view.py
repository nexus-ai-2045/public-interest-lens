"""/history の法律の結果一覧（law-outcomes.json）が、額と向きを公開ランキング（ranking.json）に合わせているか。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import build_law_outcomes_view as view
from scripts.build_public_ranking import MACRO_DIRECTION_NOTE, direction_undetermined

ROOT = Path(__file__).resolve().parents[1]
RANKING = ROOT / "app" / "public" / "distribution" / "ranking.json"


class LawOutcomesViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ranking_doc = json.loads(RANKING.read_text(encoding="utf-8"))
        cls.ranking = {law["id"]: law for law in cls.ranking_doc["laws"]}
        cls.items = view.build(cls.ranking_doc)["items"]

    def test_amounts_are_exactly_the_public_ranking_amounts(self) -> None:
        """額のある行は公開ランキングの法律と1対1で、額・確かさも同じ。ほかの行は額を出さない。"""
        amounted = {item["id"]: item for item in self.items if item["median"] is not None}
        self.assertEqual(set(amounted), set(self.ranking))
        for law_id, item in amounted.items():
            self.assertEqual(item["result"], "額あり")
            self.assertEqual(item["median"], self.ranking[law_id]["amountMedianYen"])
            self.assertEqual(item["certainty"], self.ranking[law_id]["certainty"])
        self.assertTrue(all(item["result"] != "額あり" for item in self.items if item["median"] is None))

    def test_undetermined_direction_is_not_split_into_sides(self) -> None:
        """向き未確定の印がある法律は side を undetermined にし、向きの欄も出さない。"""
        for item in self.items:
            if item["median"] is None:
                continue
            law = self.ranking[item["id"]]
            undetermined = direction_undetermined(law["notes"])
            self.assertEqual(item["side"], "undetermined" if undetermined else law["side"], item["id"])
            if undetermined:
                self.assertEqual(item["direction"], "", item["id"])

    def test_fixture_undetermined_and_withheld(self) -> None:
        """入力の印だけで判定が変わることを、作った ranking で確かめる（実データに該当が無くても落ちる）。"""
        law_id = next(item["id"] for item in self.items if item["median"] is not None)
        base = dict(self.ranking[law_id])
        flipped = {**self.ranking_doc, "laws": [{**law, "notes": [MACRO_DIRECTION_NOTE]} if law["id"] == law_id else law for law in self.ranking_doc["laws"]]}
        row = next(item for item in view.build(flipped)["items"] if item["id"] == law_id)
        self.assertEqual((row["side"], row["direction"]), ("undetermined", ""))
        withheld = {**self.ranking_doc, "laws": [law for law in self.ranking_doc["laws"] if law["id"] != law_id], "others": self.ranking_doc["others"] + [{"id": law_id, "title": base["title"], "outcome": "共有額の参考（1本ごとの額は出さない）", "reason": "x"}]}
        row = next(item for item in view.build(withheld)["items"] if item["id"] == law_id)
        self.assertIsNone(row["median"])
        self.assertEqual(row["result"], "保留")


if __name__ == "__main__":
    unittest.main()
