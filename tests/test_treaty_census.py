import csv
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_treaty_outcomes as o  # noqa: E402
import fetch_treaty_census as f  # noqa: E402

PAGE = """
<caption class="txt04b">閣法の一覧</caption>
<table><tr><td>1</td><td>1</td><td>x</td><td>成立</td></tr></table>
<caption class="txt04b">条約の一覧</caption>
<tr valign="top"><th>提出回次</th></tr>
<tr valign="top"><td>190</td><td>1</td><td>航空業務に関する日本国とラオス人民民主共和国との間の協定の締結について承認を求めるの件</td><td>両院承認</td>
<td><a href="./keika/1DBE112.htm">経過</a></td></tr>
<caption class="txt04b">承諾の一覧</caption>
<tr valign="top"><td>190</td><td>平成二十七年度一般会計予備費使用総調書</td><td>両院承諾</td><td><a href="./keika/1DBE156.htm">経過</a></td></tr>
"""


class ParseListingTest(unittest.TestCase):
    def test_takes_only_treaty_and_approval_tables(self):
        rows, other = f.parse_listing(PAGE, 190, "https://example.invalid/kaiji190.htm")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["種別"], rows[0]["提出回次"], rows[0]["番号"], rows[0]["審議状況"]), ("条約", "190", "1", "両院承認"))
        self.assertTrue(rows[0]["経過URL"].endswith("/keika/1DBE112.htm"))
        # 閣法の表は法律の取得の範囲、承諾（予備費）は財政の範囲。件数だけ数えて取らない
        self.assertEqual(other, {"閣法": 1, "承諾": 1})


class ClassifyTest(unittest.TestCase):
    def kind(self, title):
        return o.classify(title)[:3]

    def test_economic_channels_are_held_for_later_calculation(self):
        self.assertEqual(self.kind("経済上の連携の強化に関する日本国とメキシコ合衆国との間の協定の締結について承認を求めるの件")[2], "保留")
        self.assertEqual(self.kind("所得に対する租税に関する二重課税の回避及び脱税の防止のための日本国と大韓民国との間の条約の締結について承認を求めるの件")[1], "租税条約")
        self.assertEqual(self.kind("航空業務に関する日本国とラオス人民民主共和国との間の協定の締結について承認を求めるの件")[1], "航空協定")
        self.assertEqual(self.kind("投資の促進、円滑化及び保護に関する日本国政府、大韓民国政府及び中華人民共和国政府の間の協定の締結について承認を求めるの件")[1], "投資協定")

    def test_trade_ban_approval_is_economic_not_procedure(self):
        code, kind, result = self.kind("外国為替及び外国貿易法第十条第二項の規定に基づき、北朝鮮からの貨物につき輸入承認義務を課する等の措置を講じたことについて承認を求めるの件")
        self.assertEqual((code, result), ("TR0", "保留"))

    def test_procedural_approvals_and_non_economic_are_out_of_scope(self):
        self.assertEqual(self.kind("放送法第三十七条第二項の規定に基づき、承認を求めるの件")[2], "評価対象外")
        self.assertEqual(self.kind("放送法第七十条第二項の規定に基づき、承認を求めるの件")[0], "TR1")
        self.assertEqual(self.kind("拷問及び他の残虐な、非人道的な又は品位を傷つける取扱い又は刑罰に関する条約の締結について承認を求めるの件")[2], "評価対象外")

    def test_unmatched_title_is_kept_not_dropped(self):
        code, kind, result = self.kind("まったく知らない題名の件")
        self.assertEqual((code, result), ("TR99", "測定できない"))

    def test_first_rule_wins(self):
        # 「航空」でも国際民間航空条約は国際規格。航空協定（路線の自由度）と混ぜない
        self.assertEqual(self.kind("国際民間航空条約の改正に関する議定書の締結について承認を求めるの件")[0], "TR12b")


SRC = Path(o.SRC)


@unittest.skipUnless(SRC.exists(), "treaty-census が無い")
class CommittedOutcomesTest(unittest.TestCase):
    def test_every_row_has_a_result_and_a_reason(self):
        rows = o.build()
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        for r in rows:
            self.assertIn(r["結果"], ("保留", "測定できない", "評価対象外"))
            self.assertTrue(r["理由"])

    def test_committed_file_matches_generated(self):
        with Path(o.OUT).open(encoding="utf-8", newline="") as fh:
            committed = list(csv.DictReader(fh))
        self.assertEqual(committed, [{k: str(v) for k, v in r.items()} for r in o.build()])

    def test_most_titles_match_a_rule(self):
        rows = o.build()
        other = sum(r["経路"] == "TR99" for r in rows)
        self.assertLess(other / len(rows), 0.05, "規則に当たらない題名が5%を超えた。規則の語を足す")


if __name__ == "__main__":
    unittest.main()
