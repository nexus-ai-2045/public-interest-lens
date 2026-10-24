"""全体指標の参考の額（macro-v1）：保存済みの出力が、額か理由のどちらかを必ず持ち、額は OECD 表6 から同じ値に計算し直せる。"""
import csv
import unittest

from scripts import build_macro_amounts as macro
from scripts.source_check import Oecd, recompute


class MacroAmountsTest(unittest.TestCase):
    def setUp(self):
        with macro.OUT.open(encoding="utf-8", newline="") as f:
            self.rows = list(csv.DictReader(f))

    def test_every_row_has_an_amount_or_a_reason(self):
        self.assertTrue(self.rows)
        for r in self.rows:
            self.assertIn(r["結果"], ("額", "理由"), r["id"])
            if r["結果"] == "額":
                self.assertTrue(r["中央値"] and r["窓"] and r["比較国"], r["id"])
            else:
                self.assertTrue(r["理由"], r["id"])
                self.assertEqual(r["中央値"], "", r["id"])

    def test_amounts_recompute_from_oecd(self):
        oecd = Oecd(macro.OECD)
        for r in [r for r in self.rows if r["結果"] == "額"][::50]:
            end = macro.COVID_START - 1 if int(r["施行日"][:4]) < macro.COVID_START else 9999
            got = recompute(oecd, r["産業"], r["施行日"], end, r["比較国"].split("・"))
            self.assertEqual(got["median"], int(r["中央値"]), r["id"])

    def test_pre_covid_windows_stop_at_2019(self):
        for r in self.rows:
            if r["結果"] == "額" and int(r["施行日"][:4]) < macro.COVID_START:
                self.assertLessEqual(int(r["窓"][-5:-1]), 2019, r["id"])

    def test_field_without_industry_falls_back_to_the_whole_economy(self):
        self.assertEqual(macro.pick("対応表なし", ""), ("経済全体", "対応表なし", "_T"))
        self.assertEqual(macro.pick("対応表なし", "金融"), ("金融", "AI 2系統", "K"))
        self.assertEqual(macro.pick("農林水産", "金融"), ("農林水産", "振り分け", "A"))

    def test_held_single_system_field_does_not_replace_the_ai_industry(self):
        self.assertEqual(macro.publication_field("金融", "農林水産", "保留"), ("農林水産", "AI 2系統", "A"))
        self.assertEqual(macro.publication_field("金融", "農林水産", "採用"), ("金融", "振り分け", "K"))
        self.assertEqual(macro.publication_field("金融", "", "保留"), ("金融", "振り分け", "K"))
        self.assertEqual(macro.publication_field("対応表なし", "農林水産", None), ("農林水産", "AI 2系統", "A"))

    def test_kaku_142_20_publishes_the_agreed_agriculture_field(self):
        row = next(r for r in self.rows if r["id"] == "閣法-142-20")
        self.assertEqual(row["分野"], "農林水産")
        self.assertEqual(row["分野の由来"], "AI 2系統")
        self.assertEqual(row["産業"], "A")
        self.assertEqual(row["施行日"], "1998-04-01")
        self.assertNotIn("金融", row["分野"])


if __name__ == "__main__":
    unittest.main()


class AlignByTitleTest(unittest.TestCase):
    def test_amendments_of_one_law_share_the_majority_industry(self):
        picks = {"a": ("教育", "AI 2系統", "P"), "b": ("教育", "AI 2系統", "P"), "c": ("経済全体", "AI 2系統", "_T"),
                 "d": ("経済全体", "振り分け", "_T"), "e": ("金融", "AI 2系統", "K"), "f": ("建設", "AI 2系統", "F")}
        titles = {"a": "学校教育法の一部を改正する法律案", "b": "学校教育法等の一部を改正する法律案", "c": "学校教育法の一部を改正する法律",
                  "d": "学校教育法の一部を改正する法律案", "e": "海岸法の一部を改正する法律案", "f": "海岸法の一部を改正する法律案"}
        out = macro.align_by_title(picks, titles)
        self.assertEqual(out["c"], ("教育", macro.ALIGNED, "P"))
        self.assertEqual(out["d"], picks["d"])  # 振り分けで決まった本は変えない
        self.assertEqual((out["e"], out["f"]), (picks["e"], picks["f"]))  # 同数はそのまま


class EstimatedStartTest(unittest.TestCase):
    def test_laws_without_an_enforcement_date_use_the_promulgation_date_and_say_so(self):
        import json
        from scripts.build_public_ranking import ESTIMATED, OUTPUT
        with macro.OUT.open(encoding="utf-8", newline="") as f:
            rows = {r["id"]: r for r in csv.DictReader(f)}
        laws = {law["id"]: law for law in json.loads(OUTPUT.read_text(encoding="utf-8"))["laws"]}
        estimated = [r for r in rows.values() if r["施行日の由来"] == ESTIMATED and r["結果"] == "額"]
        self.assertTrue(estimated)
        for r in estimated:
            if r["id"] in laws:
                self.assertIn(f"施行日は{ESTIMATED}", laws[r["id"]]["notes"], r["id"])
