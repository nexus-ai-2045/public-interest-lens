"""未成立法案の向きの規則の検査。規則の外は不明、属性の語は規則に入れない、提出の点は ±1 の件数。"""
import csv
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import build_submitter_points as sp
import build_unenacted_direction as bd

DIR = Path("data/derived/unenacted-bills-v1/direction.csv")


class RuleTest(unittest.TestCase):
    def test_known_titles(self):
        self.assertEqual(bd.judge("日本たばこ産業株式会社の完全民営化等に関する法律案")[0], "プラス")
        self.assertEqual(bd.judge("鉄道の国有化に関する法律案")[0], "マイナス")
        self.assertEqual(bd.judge("高等学校等就学支援金の支給に関する法律案")[0], "不明")  # 採算は題名で決まらない
        self.assertEqual(bd.judge("郵政民営化の株式の処分の停止に関する法律案")[0], "不明")  # 停止は逆向き
        self.assertEqual(bd.judge("公職選挙法の一部を改正する法律案")[0], "不明")

    def test_no_attribute_words_in_rules(self):
        text = " ".join(p for _, _, p, _ in bd.RULES)
        for w in bd.FORBIDDEN_WORDS:
            self.assertNotIn(w, text)

    def test_rule_codes_unique_and_direction_valid(self):
        codes = [c for c, *_ in bd.RULES]
        self.assertEqual(len(codes), len(set(codes)))
        for _, d, p, why in bd.RULES:
            self.assertIn(d, ("プラス", "マイナス", "不明"))
            self.assertTrue(why)
            re.compile(p)

    def test_fiscal_type_has_no_direction(self):
        self.assertEqual(bd.BY["F1"][0], "不明")


@unittest.skipUnless(DIR.exists(), "direction.csv 未生成")
class OutputTest(unittest.TestCase):
    def test_output_consistent(self):
        rows = list(csv.DictReader(DIR.open(encoding="utf-8")))
        for r in rows:
            self.assertEqual(int(r["提出の点"]), {"プラス": 1, "マイナス": -1, "不明": 0}[r["向き"]])
            self.assertEqual(r["確かさ"], "低（題名の語）")
            if r["向き"] != "不明":
                self.assertTrue(r["規則"] and r["根拠"])
            self.assertEqual(bd.judge(r["題名"])[0], r["向き"])  # コミット済みが生成結果と同じ


class AggregateTest(unittest.TestCase):
    def test_aggregate(self):
        d = [{"id": "a", "向き": "プラス"}, {"id": "b", "向き": "マイナス"}, {"id": "c", "向き": "マイナス"}, {"id": "d", "向き": "不明"}]
        s = [{"id": "a", "筆頭の人物ID": "P1", "提出会派": "X"}, {"id": "b", "筆頭の人物ID": "P1", "提出会派": "X"},
             {"id": "c", "筆頭の人物ID": "", "提出会派": "Y"}, {"id": "d", "筆頭の人物ID": "P2", "提出会派": ""}]
        p, g = sp.aggregate(d, s)
        pm = {r["キー"]: r for r in p}
        self.assertEqual(pm["P1"]["提出の点"], 0)
        self.assertEqual(pm["P2"]["向き不明"], 1)
        self.assertEqual({r["キー"]: r["提出の点"] for r in g}, {"X": 0, "Y": -1})


if __name__ == "__main__":
    unittest.main()
