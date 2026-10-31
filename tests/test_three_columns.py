"""額の物差し三欄（設計決定0024）：符号の扱い、採算、国の収支が付加価値の本線に混ざらないこと、規則の共有。"""
import csv
import unittest
from pathlib import Path

from scripts import build_three_columns as tc
from scripts import evaluation_rules as rules

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ROOT / "data" / "derived" / "three-columns-v1" / "columns.csv"


class RulesTest(unittest.TestCase):
    def test_sign_conflict_detects_opposite_sign_only(self):
        self.assertEqual(rules.sign_conflict("貢献", "便益：中央値=-1"), "便益")
        self.assertEqual(rules.sign_conflict("悪影響", "損失：中央値=-1"), "損失")
        self.assertEqual(rules.sign_conflict("悪影響", "便益：中央値=1"), "便益")
        self.assertIsNone(rules.sign_conflict("貢献", "便益：中央値=1"))
        self.assertIsNone(rules.sign_conflict("悪影響", "損失：中央値=1"))
        self.assertIsNone(rules.sign_conflict("貢献", "額なし"))

    def test_narrow_title_with_whole_economy_only(self):
        self.assertTrue(rules.narrow_whole_economy("臨時措置法案", "_T", "金融"))
        self.assertTrue(rules.narrow_whole_economy("臨時措置法案", "K", "経済全体"))
        self.assertFalse(rules.narrow_whole_economy("臨時措置法案", "K", "金融"))
        self.assertFalse(rules.narrow_whole_economy("預金保険法案", "_T", "経済全体"))


class ColumnsTest(unittest.TestCase):
    def test_loss_is_negative_and_benefit_is_positive(self):
        self.assertEqual(tc.signed_median("損失：中央値=500;第1四分位=1"), -500)
        self.assertEqual(tc.signed_median("便益：中央値=500;第1四分位=1"), 500)
        self.assertIsNone(tc.signed_median(""))

    def test_middle_of_three(self):
        self.assertEqual(tc.middle("1・2・3"), 2)
        self.assertIsNone(tc.middle("1・2"))

    def test_table_is_complete_and_columns_are_separate(self):
        with COLUMNS.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 3415)
        self.assertEqual(len({r["id"] for r in rows}), 3415)
        for r in rows:
            # 順位に使うのは個別の因果の鎖の付加価値だけ。国の収支・参考の額は使わない
            if r["順位に使う"] == "はい":
                self.assertEqual(r["付加価値の由来"], tc.ORIGIN_CHAIN, r["id"])
            if r["付加価値の由来"] in (tc.ORIGIN_COVID, tc.ORIGIN_MACRO):
                self.assertEqual(r["順位に使う"], "いいえ", r["id"])
            if r["国の収支（億円）"]:
                self.assertEqual(r["国の収支の由来"], tc.ORIGIN_FISCAL, r["id"])
                self.assertEqual(r["順位に使う"], "", r["id"])  # 税制改正は付加価値の本線に入らない
            if r["採算（付加価値÷国の支出）"]:
                self.assertTrue(r["国の支出（円）"] and r["付加価値の変化（円）"], r["id"])


if __name__ == "__main__":
    unittest.main()
