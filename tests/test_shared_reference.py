"""共有額の参考値：同じ額を共有する法律は1本ごとの額を出さず、共有された合計（総枠）と本数だけを持つ。順位・合計・議員配分に入れない。"""
import unittest
from types import MappingProxyType

from scripts import build_laws_catalog as catalog
from scripts.build_public_ranking import (
    MACRO_GROUP,
    OUTCOMES,
    hide_unreliable,
    shared_key,
    shared_reference,
)

CEILING = 10**15


def law(id_, group=f"{MACRO_GROUP}-J", median=10**12, window="2014〜2019年", side="loss"):
    return {"id": id_, "title": "題名" + id_, "side": side, "certainty": "参考", "notes": ["施行日は推定（公布日）"], "group": group, "field": "情報通信",
            "indicator": "情報通信業の実質付加価値", "window": window, "comparisonCountries": ["USA", "GBR"], "enforcedOn": "2015-04-01",
            "amountMedianYen": median, "amountLowYen": median // 2, "amountHighYen": median * 2, "sources": ["https://www.shugiin.go.jp/x"]}


class HideSharedTest(unittest.TestCase):
    def test_shared_laws_leave_the_ranking_and_go_to_shared_out(self):
        laws = [law("a", median=5), law("b", median=5), law("c", median=7)]
        shared: list[dict] = []
        kept, moved = hide_unreliable(laws, {}, CEILING, None, shared)
        self.assertEqual([k["id"] for k in kept], ["c"])
        self.assertEqual([m["id"] for m in moved], ["a", "b"])
        self.assertEqual([s["id"] for s in shared], ["a", "b"])
        self.assertTrue(all(m["outcome"] == OUTCOMES["hidden_shared"] for m in moved))

    def test_demoted_law_is_not_shared(self):
        laws = [law("a", median=5), law("b", median=5)]
        shared: list[dict] = []
        kept, _moved = hide_unreliable(laws, {"a": "x"}, CEILING, None, shared)
        self.assertEqual(shared, [])
        self.assertEqual({k["id"] for k in kept}, {"a", "b"})  # 同額は不合格の a を除いた1本だけなので共有ではない


class SharedReferenceTest(unittest.TestCase):
    def test_groups_carry_total_and_size_and_laws_carry_no_amount(self):
        shared = [law("a", median=5), law("b", median=5), law("c", median=9, window="2010〜2015年"), law("d", median=9, window="2010〜2015年"), law("e", median=9, window="2010〜2015年")]
        ref = shared_reference(shared)
        self.assertEqual({g["key"]: g["size"] for g in ref["groups"]}, {shared_key(shared[0]): 2, shared_key(shared[2]): 3})
        self.assertEqual(sum(g["size"] for g in ref["groups"]), len(ref["laws"]))
        for g in ref["groups"]:
            self.assertGreater(g["medianYen"], 0)
            self.assertEqual(g["industry"], "J")
        for item in ref["laws"]:
            self.assertEqual(set(item), {"id", "key", "field", "enforcedOn", "notes", "sources"})  # 1本ごとの額は持たない

    def test_whole_economy_industry_is_recorded(self):
        ref = shared_reference([law("a", group=f"{MACRO_GROUP}-_T", median=3), law("b", group=f"{MACRO_GROUP}-_T", median=3)])
        self.assertEqual(ref["groups"][0]["industry"], "_T")


class CatalogSharedTest(unittest.TestCase):
    group = MappingProxyType({"key": "k", "group": f"{MACRO_GROUP}-_T", "industry": "_T", "window": "2000〜2009年", "side": "loss", "indicator": "全産業の実質付加価値",
             "comparisonCountries": ["AUS", "FRA"], "medianYen": 50 * 10**12, "lowYen": 10 * 10**12, "highYen": 60 * 10**12, "size": 28})

    def test_ratio_to_japan_value_added_uses_year_before_window(self):
        out = catalog.shared_fields(self.group, {1999: 500 * 10**12})
        self.assertEqual((out["size"], out["median"], out["whole"], out["baseYear"], out["ratio"]), (28, 50 * 10**12, True, 1999, 0.1))
        self.assertNotIn("ratio", catalog.shared_fields(self.group, {}))

    def test_basis_names_premises(self):
        text = catalog.shared_basis(self.group, catalog.shared_fields(self.group, {}))
        for word in ("産業コード _T", "2000〜2009年", "OECD 表6", "28本", "モデルの判定はまだ無い", "配分はしていない"):
            self.assertIn(word, text)

    def test_shared_laws_are_grouped_for_the_list(self):
        items = [{"id": f"x{i}", "shared": {"key": "k"}} for i in (2, 1, 3)] + [{"id": "y", "shared": {"key": "j"}}]
        catalog.mark_shared_observations(items)
        by_id = {i["id"]: i["observation"] for i in items}
        self.assertTrue(by_id["x1"]["representative"])
        self.assertEqual((by_id["x2"]["representativeId"], by_id["x2"]["size"]), ("x1", 3))
        self.assertEqual(by_id["y"]["size"], 1)


if __name__ == "__main__":
    unittest.main()
