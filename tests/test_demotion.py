"""不合格ゼロの降格規則：不合格の法律は額を消さず、参考値に下げて理由と根拠を付ける。"""
import unittest

from scripts.build_evaluation_ledger import SAMPLED_STATES, VERIFY_STATES, summarize, verify_state
from scripts.build_public_ranking import COVID_BENEFIT_GROUP, MACRO_GROUP, demoted_basis, hide_unreliable
from scripts.evaluation_rules import STATE_DEMOTED, STATE_FAILED, is_demoted

CEILING = 10**15


def law(id_, certainty="高", group="観測G", side="benefit", median=10**12, indicator="通信業の付加価値", window="2014〜2019年"):
    return {"id": id_, "title": "題名" + id_, "side": side, "certainty": certainty, "notes": [], "group": group,
            "indicator": indicator, "window": window, "comparisonCountries": ["USA", "GBR"],
            "amountMedianYen": median, "amountLowYen": median // 2, "amountHighYen": median * 2}


class IsDemotedTest(unittest.TestCase):
    def test_pass_is_never_demoted(self):
        self.assertFalse(is_demoted("合格", "参考額（産業の付加価値の差）", "参考", in_ranking=True))

    def test_high_certainty_not_evaluated_law_is_demoted(self):
        # 衆法-186-35 型：台帳は評価対象外、確かさ高の額が画面に出ている
        self.assertTrue(is_demoted("不合格", "評価対象外"))
        self.assertTrue(is_demoted("不合格", "評価対象外", "高", in_ranking=True))

    def test_covid_type_is_demoted(self):
        self.assertTrue(is_demoted("不合格", "参考額（産業の付加価値の差）", "低（マクロ指標で代理）"))

    def test_ordinary_reference_amount_is_demoted(self):
        self.assertTrue(is_demoted("不合格", "参考額（産業の付加価値の差）", "参考"))

    def test_no_amount_reach_stays_failed(self):
        for reach in ("保留", "測定できない", "効果なし（定例）", "国の収支の額（GDP とは別欄）"):
            self.assertFalse(is_demoted("不合格", reach, ""), reach)


class RankingDemotionTest(unittest.TestCase):
    def test_failed_high_certainty_keeps_amount_as_reference(self):
        laws = [law("衆法-186-35", "高", median=19_446_249_328_385)]
        kept, moved = hide_unreliable(laws, {"衆法-186-35": "分類：サイト対象／独立判定制度のみ"}, CEILING)
        self.assertEqual(moved, [])
        self.assertEqual(kept[0]["amountMedianYen"], 19_446_249_328_385)
        self.assertEqual(kept[0]["side"], "benefit")
        self.assertEqual(kept[0]["certainty"], "参考")
        self.assertEqual(kept[0]["demotedReason"], "分類：サイト対象／独立判定制度のみ")
        self.assertIn("通信業の付加価値 2014〜2019年", kept[0]["demotedBasis"])

    def test_failed_covid_benefit_is_demoted_with_basis(self):
        g = f"{COVID_BENEFIT_GROUP}閣法-201-54"
        laws = [law("閣法-201-54", "参考", group=g, median=257_999_990_000)]
        basis = "特例猶予1.52兆円×消費に回る割合12〜22%。猶予は繰延べで恒久便益ではない"
        kept, moved = hide_unreliable(laws, {"閣法-201-54": "範囲：産業を特定できない"}, CEILING, {"閣法-201-54": basis})
        self.assertEqual(moved, [])
        self.assertEqual(kept[0]["demotedBasis"], basis)
        self.assertEqual(kept[0]["amountMedianYen"], 257_999_990_000)

    def test_failed_oversize_or_shared_reference_is_kept_not_hidden(self):
        laws = [law("a", "参考", group=f"{MACRO_GROUP}-J", median=2 * CEILING), law("b", "参考", median=5), law("c", "参考", median=5)]
        kept, moved = hide_unreliable(laws, {"a": "x", "b": "y"}, CEILING)
        self.assertEqual({k["id"] for k in kept}, {"a", "b", "c"} - {i["id"] for i in moved})
        self.assertTrue(all("demotedReason" in k for k in kept if k["id"] in ("a", "b")))
        self.assertIn("a", {k["id"] for k in kept})
        self.assertIn("b", {k["id"] for k in kept})

    def test_not_failed_laws_are_untouched(self):
        laws = [law("ok", "高"), law("ref", "参考", median=7)]
        kept, moved = hide_unreliable(laws, {"other": "x"}, CEILING)
        self.assertEqual(moved, [])
        self.assertTrue(all("demotedReason" not in k for k in kept))
        self.assertEqual(kept[0]["certainty"], "高")

    def test_basis_for_macro_law_names_oecd_median(self):
        text = demoted_basis(law("m", "参考", group=f"{MACRO_GROUP}-J"))
        self.assertIn("OECD 同産業の中央値との差", text)


class LedgerStateTest(unittest.TestCase):
    sample = {
        "A": {"判定": "不合格", "食い違い": "理由A"},
        "B": {"判定": "不合格", "食い違い": "理由B"},
        "C": {"判定": "合格", "食い違い": ""},
    }

    def test_states_split(self):
        self.assertEqual(verify_state("A", "", self.sample, "参考額（産業の付加価値の差）", "参考"), (STATE_DEMOTED, "理由A"))
        self.assertEqual(verify_state("B", "", self.sample, "保留", ""), (STATE_FAILED, "理由B"))
        self.assertEqual(verify_state("C", "", self.sample, "評価対象外", ""), ("抜き取り検証で合格", ""))
        self.assertIn(STATE_DEMOTED, VERIFY_STATES)

    def test_summary_counts_demoted_as_sampled_failures(self):
        def row(state, reach):
            return {"検証状態": state, "到達点": reach, "額（円）": "1", "分類の方法": "", "分野の方法": "", "額の方法": "", "確かさ": "",
                    "ロジック検査": "違反なし", "常識検査③": "", "頑健性④": "", "同型の誤り候補⑤": "", "付加価値の変化（円）": "", "付加価値の由来": "",
                    "国の収支（億円）": "", "採算（付加価値÷国の支出）": ""}
        rows = [row("抜き取り検証で合格", "r"), row(STATE_DEMOTED, "r"), row(STATE_FAILED, "r"), row("未検証", "r")]
        s = summarize(rows)
        self.assertEqual(s["sample"], {"n": 3, "pass": 1, "fail": 2, "demoted": 1, "failed_kept": 1})
        self.assertEqual(s["by_reach"]["r"]["抜き取り"], 3)
        self.assertEqual(s["by_reach"]["r"]["参考に下げた"], 1)
        self.assertEqual(s["by_verify_state"][STATE_DEMOTED], 1)
        self.assertTrue(set(SAMPLED_STATES) <= set(VERIFY_STATES))


if __name__ == "__main__":
    unittest.main()
